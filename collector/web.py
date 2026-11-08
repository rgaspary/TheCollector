"""Local web server: paste a Spotify playlist link, resolve close matches, build the playlist."""
import json
import mimetypes
import secrets
import threading
import urllib.parse
from collections import OrderedDict
from dataclasses import asdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import config as config_mod
from .choices import MISSING, Choices
from .library import LocalTrack, load_library
from .matching import MatchResult, match_playlist
from .playlist import write_m3u8
from .spotify import Playlist, SpotifyClient, SpotifyError
from .vault import write_missing_note

STATIC = config_mod.ROOT / "static"
MAX_ANALYSES = 10


class App:
    def __init__(self, cfg: config_mod.Config):
        self.cfg = cfg
        self.spotify = SpotifyClient(cfg)
        self.choices = Choices()
        self.lock = threading.Lock()
        self.analyses: OrderedDict[str, tuple[Playlist, list[MatchResult]]] = OrderedDict()
        self._config_mtime = self._mtime()

    @staticmethod
    def _mtime() -> float:
        try:
            return config_mod.CONFIG_PATH.stat().st_mtime
        except OSError:
            return 0.0

    def reload_config_if_changed(self):
        """Pick up config.toml edits (like a new Client ID) without restarting the server."""
        mtime = self._mtime()
        if mtime == self._config_mtime:
            return
        self._config_mtime = mtime
        try:
            new = config_mod.load()
        except Exception as e:  # half-saved or invalid file: keep the old settings
            print(f"Couldn't reload config.toml, keeping the previous settings: {e}", flush=True)
            return
        new.host, new.port = self.cfg.host, self.cfg.port  # the server is already bound to these
        self.cfg = new
        self.spotify.config = new
        print("Reloaded config.toml", flush=True)

    def status(self) -> dict:
        return {
            "client_id_set": bool(self.cfg.client_id),
            "logged_in": self.spotify.logged_in,
            "redirect_uri": self.cfg.redirect_uri,
            "playlist_dir": str(self.cfg.playlist_dir),
            "notes_folder": self.cfg.notes_folder,
        }

    def analyze(self, link: str) -> dict:
        playlist = self.spotify.get_playlist(link)
        library = load_library(self.cfg.strawberry_db)
        results = match_playlist(playlist.tracks, library)
        aid = secrets.token_urlsafe(8)
        with self.lock:
            self.analyses[aid] = (playlist, results)
            while len(self.analyses) > MAX_ANALYSES:
                self.analyses.popitem(last=False)

        tracks = []
        for i, r in enumerate(results):
            remembered = self.choices.get(r.spotify.id) if r.status == "close" else None
            paths = {c.track.path for c in r.candidates}
            if remembered and remembered != MISSING and remembered not in paths:
                remembered = None  # that file is gone or no longer a candidate
            tracks.append({
                "index": i,
                "spotify": asdict(r.spotify) | {"artist": r.spotify.artist},
                "status": r.status,
                "remembered": remembered,
                "candidates": [asdict(c.track) | {"reason": c.reason, "score": c.score} for c in r.candidates],
            })
        return {
            "analysis_id": aid,
            "playlist": {"name": playlist.name, "url": playlist.url, "count": len(results)},
            "library_count": len(library),
            "tracks": tracks,
        }

    def build(self, aid: str, decisions: dict[str, str]) -> dict:
        with self.lock:
            entry = self.analyses.get(aid)
        if not entry:
            raise ValueError("This result has expired. Analyze the playlist again.")
        playlist, results = entry

        chosen: list[LocalTrack] = []
        missing, found = [], []
        remember: dict[str, str] = {}
        for i, r in enumerate(results):
            if r.status == "exact":
                chosen.append(r.best)
                found.append(r.spotify)
            elif r.status == "missing":
                missing.append(r.spotify)
            else:
                pick = decisions.get(str(i))
                by_path = {c.track.path: c.track for c in r.candidates}
                if pick in by_path:
                    chosen.append(by_path[pick])
                    found.append(r.spotify)
                    remember[r.spotify.id] = pick
                elif pick == MISSING:
                    missing.append(r.spotify)
                    remember[r.spotify.id] = MISSING
                else:
                    raise ValueError(f'Choose an option for "{r.spotify.title}".')

        m3u = write_m3u8(playlist.name, chosen, self.cfg.playlist_dir) if chosen else None
        note = write_missing_note(self.cfg.vault_path, self.cfg.notes_folder, self.cfg.area,
                                  playlist.name, playlist.url, missing, found)
        self.choices.update(remember)

        obsidian = None
        if note.path:
            rel = note.path.relative_to(self.cfg.vault_path).with_suffix("").as_posix()
            obsidian = "obsidian://open?" + urllib.parse.urlencode(
                {"vault": self.cfg.vault_name, "file": rel}, quote_via=urllib.parse.quote)
        return {
            "playlist_path": str(m3u) if m3u else None,
            "added": len(chosen),
            "missing": len(missing),
            "note_path": str(note.path) if note.path else None,
            "note_added": note.added,
            "note_ticked": note.ticked,
            "obsidian_url": obsidian,
        }


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        # ---- helpers ---------------------------------------------------------------
        def _send(self, status: int, body: bytes, ctype: str, headers: dict | None = None):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, data, status=200):
            self._send(status, json.dumps(data).encode(), "application/json")

        def _redirect(self, url: str):
            self._send(HTTPStatus.FOUND, b"", "text/plain", {"Location": url})

        def _same_origin(self) -> bool:
            origin = self.headers.get("Origin")
            allowed = {f"http://{app.cfg.host}:{app.cfg.port}", f"http://localhost:{app.cfg.port}"}
            return (origin is None or origin in allowed) and \
                self.headers.get("Content-Type", "").startswith("application/json")

        # ---- routes ----------------------------------------------------------------
        def do_GET(self):
            app.reload_config_if_changed()
            url = urllib.parse.urlparse(self.path)
            if url.path == "/":
                return self._static("index.html")
            if url.path.startswith("/static/"):
                return self._static(url.path[len("/static/"):])
            if url.path == "/api/status":
                return self._json(app.status())
            if url.path == "/login":
                try:
                    return self._redirect(app.spotify.login_url())
                except SpotifyError as e:
                    return self._redirect("/?error=" + urllib.parse.quote(str(e)))
            if url.path == "/callback":
                q = urllib.parse.parse_qs(url.query)
                if "error" in q:
                    return self._redirect("/?error=" + urllib.parse.quote("Spotify login was cancelled."))
                try:
                    app.spotify.finish_login(q.get("code", [""])[0], q.get("state", [""])[0])
                except SpotifyError as e:
                    return self._redirect("/?error=" + urllib.parse.quote(str(e)))
                return self._redirect("/?connected=1")
            self._send(404, b"Not found", "text/plain")

        def do_POST(self):
            app.reload_config_if_changed()
            if self.path == "/api/shutdown":
                # Used by collector-launch.sh stop. Browsers always send Origin on POSTs from pages,
                # so refusing any Origin keeps web pages from stopping the app.
                if self.headers.get("Origin") is not None:
                    return self._json({"error": "Forbidden"}, 403)
                self._json({"ok": True})
                return threading.Thread(target=self.server.shutdown, daemon=True).start()
            if not self._same_origin():
                return self._json({"error": "Forbidden"}, 403)
            try:
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                return self._json({"error": "Bad request"}, 400)
            try:
                if self.path == "/api/analyze":
                    return self._json(app.analyze(str(body.get("url", ""))))
                if self.path == "/api/build":
                    return self._json(app.build(str(body.get("analysis_id", "")), body.get("decisions") or {}))
                if self.path == "/api/logout":
                    app.spotify.logout()
                    return self._json({"ok": True})
            except (SpotifyError, ValueError, FileNotFoundError) as e:
                return self._json({"error": str(e)}, 400)
            except OSError as e:
                return self._json({"error": f"Couldn't write a file: {e}"}, 500)
            self._json({"error": "Not found"}, 404)

        def _static(self, name: str):
            path = (STATIC / name).resolve()
            if not path.is_relative_to(STATIC.resolve()) or not path.is_file():
                return self._send(404, b"Not found", "text/plain")
            ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype.endswith("javascript"):
                ctype += "; charset=utf-8"
            self._send(200, path.read_bytes(), ctype)

    return Handler


def serve(cfg: config_mod.Config) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((cfg.host, cfg.port), make_handler(App(cfg)))
