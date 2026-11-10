"""Local web server: the JSON API the screens call, plus the static files.

All POSTs must be same-origin JSON. Secret credential values never leave the server.
"""
import json
import mimetypes
import re
import secrets
import subprocess
import sys
import threading
import urllib.parse
from collections import OrderedDict
from dataclasses import asdict, dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import __version__, folder_picker, platform_paths
from . import config as config_mod
from .choices import MISSING, Choices
from .credentials import CredentialStore
from .exporters import MISSING_FORMATS, PLAYLIST_FORMATS, ExportItem, export_missing, export_playlist
from .exporters.players import PLAYERS, default_player
from .libraries import LIBRARIES, LibraryError, get_library
from .matching import MatchResult, match_playlist
from .sources import REGISTRY, CredentialError, SourceError, detect
from .sources.base import Source
from .sources.spotify import V1_TOKEN_FILE, migrate_v1
from .tracks import LocalTrack, Playlist, SourceTrack
from .vault import NoteResult, write_missing_note

STATIC = config_mod.ROOT / "static"
MAX_ANALYSES = 10
MAX_BODY = 1024 * 1024
PATH_STYLES = ("absolute", "relative", "name")


class ApiError(Exception):
    """An error answered as JSON with this HTTP status and payload."""

    def __init__(self, status: int, payload: dict):
        super().__init__(payload.get("error", ""))
        self.status = status
        self.payload = payload


def not_found(what: str = "That") -> ApiError:
    return ApiError(404, {"error": f"{what} wasn't found."})


@dataclass
class Resolution:
    items: list[ExportItem]
    missing: list[SourceTrack]
    found: list[SourceTrack]


@dataclass
class Analysis:
    playlist: Playlist
    results: list[MatchResult]
    resolution: Resolution | None = None


@dataclass
class App:
    cfg: config_mod.Config
    config_path: Path = config_mod.CONFIG_PATH
    store: CredentialStore = field(default_factory=CredentialStore)
    choices: Choices = field(default_factory=Choices)
    v1_token_file: Path = V1_TOKEN_FILE

    def __post_init__(self):
        migrate_v1(self.store, self.cfg, self.v1_token_file)
        self.lock = threading.Lock()
        self.analyses: OrderedDict[str, Analysis] = OrderedDict()
        self.written: set[Path] = set()
        self._config_mtime = self._mtime()

    # ---- config ----------------------------------------------------------------------------
    def _mtime(self) -> float:
        try:
            return self.config_path.stat().st_mtime
        except OSError:
            return 0.0

    def reload_config_if_changed(self) -> None:
        """Pick up config.toml edits without restarting the server."""
        mtime = self._mtime()
        if mtime == self._config_mtime:
            return
        self._config_mtime = mtime
        try:
            new = config_mod.load(self.config_path)
        except Exception as e:  # half-saved or invalid file: keep the old settings
            print(f"Couldn't reload config.toml, keeping the previous settings: {e}", flush=True)
            return
        new.host, new.port = self.cfg.host, self.cfg.port  # the server is already bound to these
        self.cfg = new
        if new.legacy_spotify_client_id and not self.store.get("spotify").get("client_id"):
            self.store.save("spotify", {"client_id": new.legacy_spotify_client_id})

    # ---- status, libraries, players -----------------------------------------------------------
    def status(self) -> dict:
        return {
            "version": __version__,
            "platform": sys.platform,
            "nextup_enabled": self.cfg.nextup_enabled,
            "missing_dir": str(self.cfg.missing_dir),
            "playlist_dir": str(self.cfg.playlist_dir),
            "library": self.library_info(),
            "redirect_uri": self.cfg.redirect_uri,
        }

    def library_info(self) -> dict:
        reader = LIBRARIES.get(self.cfg.library_type)
        path = self.cfg.library_path or (reader.detect() if reader else None)
        return {
            "id": self.cfg.library_type,
            "name": reader.name if reader else self.cfg.library_type,
            "path": str(path) if path else "",
            "folders": [str(f) for f in self.cfg.library_folders],
            "configured": self.cfg.library_configured,
        }

    @staticmethod
    def libraries() -> list[dict]:
        out = []
        for lib in LIBRARIES.values():
            detected = lib.detect()
            out.append({"id": lib.id, "name": lib.name, "subtitle": lib.subtitle, "icon": lib.icon,
                        "needs": lib.needs, "help_text": lib.help_text,
                        "detected_path": str(detected) if detected else None})
        return out

    @staticmethod
    def _library_args(body: dict) -> tuple:
        lib_id = str(body.get("id", ""))
        if lib_id not in LIBRARIES:
            raise not_found("That library type")
        raw_path = str(body.get("path") or "").strip()
        folders = [Path(str(f)).expanduser() for f in body.get("folders") or [] if str(f).strip()]
        return LIBRARIES[lib_id], Path(raw_path).expanduser() if raw_path else None, folders

    def test_library(self, body: dict) -> dict:
        reader, path, folders = self._library_args(body)
        try:
            result = {"ok": True, "message": reader.test(path, folders)}
            if warning := reader.warning(path, folders):
                result["warning"] = warning
            return result
        except LibraryError as e:
            return {"ok": False, "error": str(e), "fix": e.fix}

    def save_library(self, body: dict) -> dict:
        reader, path, folders = self._library_args(body)
        config_mod.save_library(reader.id, path, folders, self.config_path)
        self._reload_config()
        return {"library": self.library_info()}

    def save_folders(self, body: dict) -> dict:
        folders = []
        for key, what in (("playlist_dir", "playlists"), ("missing_dir", "missing-song lists")):
            raw = str(body.get(key) or "").strip()
            path = Path(raw).expanduser() if raw else None
            if path is None or not path.is_absolute():
                raise ValueError(f"Give the full path of the folder for {what}, like {Path.home() / 'Music'}.")
            folders.append(path)
        config_mod.save_folders(*folders, self.config_path)
        self._reload_config()
        return {"playlist_dir": str(self.cfg.playlist_dir), "missing_dir": str(self.cfg.missing_dir)}

    def _reload_config(self) -> None:
        new = config_mod.load(self.config_path)
        new.host, new.port = self.cfg.host, self.cfg.port
        self.cfg = new
        self._config_mtime = self._mtime()

    def players(self) -> dict:
        return {
            "players": [asdict(p) | {"platforms": sorted(p.platforms)} for p in PLAYERS.values()],
            "default": default_player(self.cfg.library_type, sys.platform),
            "formats": [{"key": f.key, "label": f.label, "ext": f.ext} for f in PLAYLIST_FORMATS.values()],
            "missing_formats": [{"key": f.key, "label": f.label, "ext": f.ext} for f in MISSING_FORMATS.values()],
        }

    # ---- sources and credentials --------------------------------------------------------------
    @staticmethod
    def source(source_id: str) -> Source:
        try:
            return REGISTRY[source_id]
        except KeyError:
            raise not_found("That music service") from None

    def sources(self) -> list[dict]:
        return [self.source_info(s) for s in REGISTRY.values()]

    def source_info(self, s: Source) -> dict:
        return {
            "id": s.id, "name": s.name, "icon": s.icon, "help_url": s.help_url, "help_text": s.help_text,
            "link_example": s.link_example, "limits": s.limits, "uses_oauth": s.uses_oauth, "input": s.input,
            "fields": [{"key": f.key, "label": f.label, "secret": f.secret, "help": f.help,
                        "placeholder": f.placeholder, "multiline": f.multiline} for f in s.fields],
            "setup_steps": [self._fill(t) for t in s.setup_steps],
            "setup_notes": [self._fill(t) for t in s.setup_notes],
            "values": self.store.public_view(s),
            "status": self.store.status(s),
        }

    def _fill(self, text: str) -> str:
        return text.replace("{redirect_uri}", self.cfg.redirect_uri)

    @staticmethod
    def _typed_values(s: Source, body: dict) -> dict:
        """Only the source's own fields, as strings. Blank values mean "keep what's saved"."""
        values = body.get("values") or {}
        if not isinstance(values, dict):
            raise ValueError("Bad request")
        keys = {f.key for f in s.fields}
        return {k: str(v).strip() for k, v in values.items() if k in keys and v is not None}

    def save_credentials(self, source_id: str, body: dict) -> dict:
        s = self.source(source_id)
        self.store.save(s.id, self._typed_values(s, body))
        self.store.mark_ok(s.id)
        return {"status": self.store.status(s)}

    def _keep_tokens(self, s: Source, creds: dict) -> None:
        """Save refreshed sign-in tokens. A refresh can replace the old token, so it's never thrown away."""
        tokens = {k: creds[k] for k in s.token_keys if creds.get(k)}
        if tokens:
            self.store.save(s.id, tokens)

    def test_credentials(self, source_id: str, body: dict) -> dict:
        s = self.source(source_id)
        typed = {k: v for k, v in self._typed_values(s, body).items() if v != ""}
        creds = self.store.get(s.id) | typed
        try:
            message = s.test(creds)
        except CredentialError as e:
            return {"ok": False, "error": str(e), "fix": e.fix}
        except SourceError as e:
            return {"ok": False, "error": str(e), "fix": ""}
        self._keep_tokens(s, creds)
        if not typed:
            self.store.mark_ok(s.id)
        return {"ok": True, "message": message}

    def disconnect(self, source_id: str) -> dict:
        s = self.source(source_id)
        self.store.remove(s.id, s.token_keys)
        return {"status": self.store.status(s)}

    # ---- analyze, resolve, export -------------------------------------------------------------
    def load_library(self) -> list[LocalTrack]:
        try:
            reader = get_library(self.cfg.library_type)
        except KeyError:
            raise LibraryError(f'"{self.cfg.library_type}" isn\'t a library type TheCollector knows.',
                               fix="Choose your music library again.") from None
        return reader.load(self.cfg.library_path, self.cfg.library_folders)

    def library_warning(self) -> str:
        reader = LIBRARIES.get(self.cfg.library_type)
        return reader.warning(self.cfg.library_path, self.cfg.library_folders) if reader else ""

    def analyze(self, body: dict) -> dict:
        link = str(body.get("url", "")).strip()
        detected = detect(link)
        s = self.source(str(body.get("source") or detected or "spotify"))
        if detected and detected != s.id:
            name = REGISTRY[detected].name
            raise ApiError(400, {"error": f"That's a {name} link. Switch to {name} to use it.",
                                 "code": "wrong_source", "detected": detected})
        creds = self.store.get(s.id)
        try:
            playlist = s.get_playlist(link, creds)
        except CredentialError as e:
            self.store.mark_invalid(s.id, str(e), e.fix)
            if s.uses_oauth:
                self.store.remove(s.id, s.token_keys)
            raise ApiError(401, {"error": str(e), "fix": e.fix, "code": "credentials", "source": s.id}) from e
        self._keep_tokens(s, creds)
        self.store.mark_ok(s.id)

        library = self.load_library()
        results = match_playlist(playlist.tracks, library)
        aid = secrets.token_urlsafe(8)
        with self.lock:
            self.analyses[aid] = Analysis(playlist, results)
            while len(self.analyses) > MAX_ANALYSES:
                self.analyses.popitem(last=False)

        tracks = []
        for i, r in enumerate(results):
            remembered = self.choices.get(playlist.source, r.spotify.id) if r.status == "close" else None
            paths = {c.track.path for c in r.candidates}
            if remembered and remembered != MISSING and remembered not in paths:
                remembered = None  # that file is gone or no longer a candidate
            track = asdict(r.spotify) | {"artist": r.spotify.artist}
            tracks.append({
                "index": i,
                "track": track,
                "status": r.status,
                "remembered": remembered,
                "candidates": [asdict(c.track) | {"reason": c.reason, "score": c.score} for c in r.candidates],
            })
        return {
            "analysis_id": aid,
            "playlist": {"name": playlist.name, "url": playlist.url, "count": len(results),
                         "source": playlist.source, "service": s.name},
            "library_count": len(library),
            "library_warning": self.library_warning(),
            "tracks": tracks,
        }

    def _analysis(self, body: dict) -> Analysis:
        with self.lock:
            entry = self.analyses.get(str(body.get("analysis_id", "")))
        if not entry:
            raise ValueError("This result has expired. Analyze the playlist again.")
        return entry

    def resolve(self, body: dict) -> dict:
        analysis = self._analysis(body)
        decisions = body.get("decisions") or {}
        items: list[ExportItem] = []
        missing, found = [], []
        remember: dict[str, str] = {}
        for i, r in enumerate(analysis.results):
            if r.status == "exact":
                items.append(ExportItem(r.best, r.spotify))
                found.append(r.spotify)
            elif r.status == "missing":
                missing.append(r.spotify)
            else:
                pick = decisions.get(str(i))
                by_path = {c.track.path: c.track for c in r.candidates}
                if pick in by_path:
                    items.append(ExportItem(by_path[pick], r.spotify))
                    found.append(r.spotify)
                    remember[r.spotify.id] = pick
                elif pick == MISSING:
                    missing.append(r.spotify)
                    remember[r.spotify.id] = MISSING
                else:
                    raise ValueError(f'Choose an option for "{r.spotify.title}".')
        analysis.resolution = Resolution(items, missing, found)
        self.choices.update(analysis.playlist.source, remember)
        return {"matched": len(items), "missing": len(missing)}

    def _resolved(self, body: dict) -> Analysis:
        analysis = self._analysis(body)
        if analysis.resolution is None:
            raise ValueError("Finish reviewing the matches first.")
        return analysis

    def _remember_written(self, paths: list[Path]) -> None:
        with self.lock:
            self.written.update(p.resolve() for p in paths)

    def export_playlist(self, body: dict) -> dict:
        analysis = self._resolved(body)
        formats = body.get("formats") or []
        if not isinstance(formats, list) or not formats:
            raise ValueError("Choose at least one format.")
        unknown = [f for f in formats if f not in PLAYLIST_FORMATS]
        if unknown:
            raise ValueError(f"Unknown format: {unknown[0]}.")
        style = body.get("path_style") or "absolute"
        if style not in PATH_STYLES:
            raise ValueError(f"Unknown path style: {style}.")
        if not analysis.resolution.items:
            raise ValueError("No songs matched, so there's no playlist to export.")
        folder = str(body.get("folder") or "").strip()
        target = Path(folder).expanduser() if folder else self.cfg.playlist_dir
        files = export_playlist(analysis.playlist, analysis.resolution.items, formats, target, style)
        self._remember_written(files)
        return {"files": [str(p) for p in files]}

    def export_missing(self, body: dict) -> dict:
        analysis = self._resolved(body)
        res, playlist = analysis.resolution, analysis.playlist
        service = self.source(playlist.source).name
        fmt = body.get("format") or None
        if fmt is not None and fmt not in MISSING_FORMATS:
            raise ValueError(f"Unknown format: {fmt}.")
        file = None
        if fmt and res.missing:
            folder = str(body.get("folder") or "").strip()
            file = export_missing(playlist, res.missing, fmt, Path(folder).expanduser() if folder else
                                  self.cfg.missing_dir, service)
            self._remember_written([file])
        note = NoteResult(None, 0, 0)
        if body.get("nextup") and self.cfg.nextup_enabled:
            note = write_missing_note(self.cfg.vault_path, self.cfg.notes_folder, self.cfg.area,
                                      playlist, service, res.missing, res.found)
            if note.path:
                self._remember_written([note.path])
        return {"file": str(file) if file else None, **self._note_payload(note)}

    def _note_payload(self, note: NoteResult) -> dict:
        obsidian = None
        if note.path:
            rel = note.path.relative_to(self.cfg.vault_path).with_suffix("").as_posix()
            obsidian = "obsidian://open?" + urllib.parse.urlencode(
                {"vault": self.cfg.vault_name, "file": rel}, quote_via=urllib.parse.quote)
        return {"note_path": str(note.path) if note.path else None, "note_added": note.added,
                "note_ticked": note.ticked, "obsidian_url": obsidian}

    @staticmethod
    def choose_folder(body: dict) -> dict:
        try:
            return {"folder": folder_picker.choose_folder(str(body.get("start") or ""))}
        except folder_picker.PickerUnavailable as e:
            raise ApiError(501, {"error": str(e)}) from e

    def reveal(self, body: dict) -> dict:
        try:
            path = Path(str(body.get("path", ""))).resolve()
        except (OSError, ValueError):
            path = None
        with self.lock:
            allowed = path in self.written
        if not allowed:
            raise ApiError(403, {"error": "TheCollector can only show files it saved."})
        subprocess.Popen(platform_paths.open_folder_command(path.parent),
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {"ok": True}


_SOURCE_ACTION = re.compile(r"^/api/sources/([a-z0-9_]+)/(credentials|test|disconnect)$")


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
            port = self.server.server_address[1]
            allowed = {f"http://{app.cfg.host}:{port}", f"http://localhost:{port}", f"http://127.0.0.1:{port}"}
            return (origin is None or origin in allowed) and \
                self.headers.get("Content-Type", "").startswith("application/json")

        # ---- routes ----------------------------------------------------------------
        def do_GET(self):
            app.reload_config_if_changed()
            url = urllib.parse.urlparse(self.path)
            path = url.path
            try:
                if path == "/":
                    return self._static("index.html")
                if path.startswith("/static/"):
                    return self._static(path[len("/static/"):])
                if path == "/api/status":
                    return self._json(app.status())
                if path == "/api/libraries":
                    return self._json(app.libraries())
                if path == "/api/players":
                    return self._json(app.players())
                if path == "/api/sources":
                    return self._json(app.sources())
                if path.startswith("/login/"):
                    return self._login(path[len("/login/"):])
                if path == "/callback":
                    return self._callback(urllib.parse.parse_qs(url.query))
            except ApiError as e:
                return self._json(e.payload, e.status)
            self._send(404, b"Not found", "text/plain")

        def _login(self, source_id: str):
            s = app.source(source_id)
            if not s.uses_oauth:
                raise not_found("A browser sign-in for that service")
            try:
                return self._redirect(s.login_url(app.store.get(s.id), app.cfg.redirect_uri))
            except SourceError as e:
                return self._redirect("/?error=" + urllib.parse.quote(str(e)))

        def _callback(self, q: dict):
            spotify = REGISTRY["spotify"]  # the only source with a browser sign-in
            if "error" in q:
                return self._redirect("/?error=" + urllib.parse.quote("Spotify sign-in was cancelled."))
            try:
                tokens = spotify.finish_login(app.store.get("spotify"), q.get("code", [""])[0],
                                              q.get("state", [""])[0], app.cfg.redirect_uri)
                app.store.save("spotify", tokens)
                app.store.mark_ok("spotify")
            except SourceError as e:
                return self._redirect("/?error=" + urllib.parse.quote(str(e)))
            return self._redirect("/?connected=spotify")

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
                if length > MAX_BODY:
                    return self._json({"error": "That request is too big."}, 413)
                body = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError
            except ValueError:
                return self._json({"error": "Bad request"}, 400)
            try:
                result = self._post(body)
                if result is None:
                    return self._json({"error": "Not found"}, 404)
                return self._json(result)
            except ApiError as e:
                return self._json(e.payload, e.status)
            except LibraryError as e:
                return self._json({"error": f"{e} {e.fix}".strip(), "fix": e.fix, "code": "library"}, 400)
            except (SourceError, ValueError) as e:
                return self._json({"error": str(e)}, 400)
            except OSError as e:
                return self._json({"error": f"Couldn't write a file: {e}"}, 500)

        def _post(self, body: dict) -> dict | None:
            routes = {
                "/api/library/test": app.test_library,
                "/api/library": app.save_library,
                "/api/choose-folder": app.choose_folder,
                "/api/settings/folders": app.save_folders,
                "/api/analyze": app.analyze,
                "/api/resolve": app.resolve,
                "/api/export/playlist": app.export_playlist,
                "/api/export/missing": app.export_missing,
                "/api/reveal": app.reveal,
            }
            if self.path in routes:
                return routes[self.path](body)
            m = _SOURCE_ACTION.match(self.path)
            if m:
                source_id, action = m.groups()
                return {"credentials": app.save_credentials, "test": app.test_credentials,
                        "disconnect": lambda sid, _body: app.disconnect(sid)}[action](source_id, body)
            return None

        def _static(self, name: str):
            path = (STATIC / name).resolve()
            if not path.is_relative_to(STATIC.resolve()) or not path.is_file():
                return self._send(404, b"Not found", "text/plain")
            ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype.endswith("javascript"):
                ctype += "; charset=utf-8"
            self._send(200, path.read_bytes(), ctype)

    return Handler


def serve(cfg: config_mod.Config, app: App | None = None) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((cfg.host, cfg.port), make_handler(app or App(cfg)))
