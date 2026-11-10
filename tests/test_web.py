"""The HTTP API, tested against a real server on a free port with a fake music service."""
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from collector import config as config_mod
from collector import web
from collector.choices import Choices
from collector.credentials import CredentialStore
from collector.sources import REGISTRY
from collector.sources.base import CredentialError, Field, Source, SourceError
from collector.tracks import LocalTrack, Playlist, SourceTrack

SECRET = "s3cret-value-never-shown"


class FakeSource(Source):
    id = "fake"
    name = "Fake Music"
    icon = "fake.svg"
    fields = [Field("token", "Token", secret=True), Field("user", "User name")]
    help_url = "https://fake.test/dev"
    link_example = "https://fake.test/playlist/…"
    link_patterns = (r"fake\.test/playlist/",)

    def parse_link(self, text: str) -> str:
        return text.rsplit("/", 1)[-1]

    def test(self, creds: dict) -> str:
        if creds.get("token") == "bad":
            raise CredentialError("Fake didn't accept the token.", fix="Copy the token again.")
        if not creds.get("token"):
            raise SourceError("No token")
        return "Fake Music accepted the token."

    def get_playlist(self, link: str, creds: dict) -> Playlist:
        self.test(creds)
        tracks = [
            SourceTrack("t1", "Creep", ["Radiohead"], "Pablo Honey", 239, "https://fake.test/track/t1"),
            SourceTrack("t2", "Smells Like Teen Spirit", ["Nirvana"], "From the Muddy Banks", 300,
                        "https://fake.test/track/t2"),
            SourceTrack("t3", "Karma Police", ["Radiohead"], "OK Computer", 264, "https://fake.test/track/t3"),
        ]
        return Playlist("fake", self.parse_link(link), "Road: Trip?", link, tracks)


class OtherSource(FakeSource):
    id = "other"
    name = "Other Music"
    link_patterns = (r"other\.test/",)


LIBRARY = [
    LocalTrack(1, "Creep", "Radiohead", "Pablo Honey", 239, "/music/Radiohead/Creep.flac"),
    LocalTrack(2, "Smells Like Teen Spirit (Live)", "Nirvana", "From the Muddy Banks", 300, "/music/Nirvana/Teen.flac"),
]
CONFIG = """# my settings
[library]
# which library
type = "strawberry"
path = "{db}"
playlist_dir = "{playlists}"

[export]
missing_dir = "{exports}"

[server]
host = "127.0.0.1"
port = 0
"""
LINK = "https://fake.test/playlist/p1"


class ApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        self.playlists, self.exports = d / "Playlists", d / "Exports"
        self.config_path = d / "config.toml"
        self.config_path.write_text(CONFIG.format(db=d / "strawberry.db", playlists=self.playlists,
                                                  exports=self.exports))
        patcher = mock.patch.dict(REGISTRY, {"fake": FakeSource(), "other": OtherSource()})
        patcher.start()
        self.addCleanup(patcher.stop)
        lib = mock.patch.object(web.App, "load_library", lambda app: list(LIBRARY))
        lib.start()
        self.addCleanup(lib.stop)

        cfg = config_mod.load(self.config_path)
        self.store = CredentialStore(d / "credentials.json")
        self.app = web.App(cfg, config_path=self.config_path, store=self.store,
                           choices=Choices(d / "choices.json"), v1_token_file=d / "no-token.json")
        self.server = web.serve(cfg, self.app)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    # ---- helpers -------------------------------------------------------------------------------
    def call(self, method: str, path: str, body=None, headers=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json", **(headers or {})})
        try:
            with urllib.request.urlopen(req) as resp:
                raw = resp.read()
                return resp.status, json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw)
            except ValueError:
                return e.code, raw.decode()

    def get(self, path: str):
        return self.call("GET", path)

    def post(self, path: str, body=None, **kw):
        return self.call("POST", path, body or {}, **kw)

    def ready_fake(self):
        self.store.save("fake", {"token": "good", "user": "me"})

    def analyzed(self) -> dict:
        self.ready_fake()
        status, data = self.post("/api/analyze", {"source": "fake", "url": LINK})
        self.assertEqual(status, 200, data)
        return data

    def resolved(self) -> str:
        data = self.analyzed()
        close = next(t["index"] for t in data["tracks"] if t["status"] == "close")
        status, _ = self.post("/api/resolve", {"analysis_id": data["analysis_id"],
                                               "decisions": {str(close): "/music/Nirvana/Teen.flac"}})
        self.assertEqual(status, 200)
        return data["analysis_id"]


class Task16(ApiTest):
    def test_status_shape(self):
        status, data = self.get("/api/status")
        self.assertEqual(status, 200)
        for key in ("version", "platform", "nextup_enabled", "missing_dir", "playlist_dir", "library"):
            self.assertIn(key, data)
        self.assertEqual(data["library"]["id"], "strawberry")
        self.assertTrue(data["library"]["configured"])
        self.assertFalse(data["nextup_enabled"])

    def test_libraries(self):
        status, data = self.get("/api/libraries")
        self.assertEqual([l["id"] for l in data], ["strawberry", "itunes", "mediamonkey", "folder"])
        self.assertTrue(all("detected_path" in l and l["help_text"] for l in data))

    def test_library_test_does_not_save(self):
        before = self.config_path.read_text()
        music = Path(self.tmp.name) / "Music"
        music.mkdir()
        (music / "Artist - Song.mp3").write_bytes(b"")
        status, data = self.post("/api/library/test", {"id": "folder", "folders": [str(music)]})
        self.assertEqual((status, data), (200, {"ok": True, "message": "Found 1 track"}))
        status, data = self.post("/api/library/test", {"id": "itunes", "path": "/nope/Library.xml"})
        self.assertEqual(status, 200)
        self.assertFalse(data["ok"])
        self.assertTrue(data["error"] and data["fix"])
        self.assertEqual(self.config_path.read_text(), before)

    def test_library_save_keeps_other_config_lines(self):
        status, data = self.post("/api/library", {"id": "folder", "folders": ["/m/a", "/m/b"]})
        self.assertEqual(status, 200)
        self.assertEqual((data["library"]["id"], data["library"]["folders"]), ("folder", ["/m/a", "/m/b"]))
        text = self.config_path.read_text()
        for kept in ("# my settings", "# which library", "playlist_dir =", "[export]", "port = 0"):
            self.assertIn(kept, text)
        self.assertEqual(self.get("/api/status")[1]["library"]["id"], "folder")

    def test_unknown_library(self):
        self.assertEqual(self.post("/api/library", {"id": "winamp"})[0], 404)

    def test_players(self):
        status, data = self.get("/api/players")
        self.assertEqual(data["default"], "strawberry")
        self.assertEqual(len(data["players"]), 10)
        rockbox = next(p for p in data["players"] if p["key"] == "rockbox")
        self.assertEqual(rockbox["path_style"], "relative")
        self.assertIn("m3u8", [f["key"] for f in data["formats"]])
        self.assertEqual([f["key"] for f in data["missing_formats"]], ["json", "csv", "md", "txt"])

    def test_sources_never_leak_secrets(self):
        self.store.save("fake", {"token": SECRET, "user": "me"})
        status, data = self.get("/api/sources")
        fake = next(s for s in data if s["id"] == "fake")
        self.assertEqual(fake["values"], {"token": {"set": True}, "user": {"value": "me"}})
        self.assertEqual(fake["status"]["state"], "ready")
        for path in ("/api/sources", "/api/status"):
            self.assertNotIn(SECRET, json.dumps(self.get(path)[1]))
        self.assertNotIn(SECRET, json.dumps(self.post("/api/sources/fake/credentials", {"values": {"user": "x"}})[1]))

    def test_save_credentials(self):
        self.store.mark_invalid("fake", "old error")
        status, data = self.post("/api/sources/fake/credentials",
                                 {"values": {"token": "good", "user": "me", "sneaky": "x"}})
        self.assertEqual((status, data["status"]["state"]), (200, "ready"))
        self.assertEqual(self.store.get("fake"), {"token": "good", "user": "me"})
        # A blank secret keeps the saved one.
        self.post("/api/sources/fake/credentials", {"values": {"token": "", "user": "you"}})
        self.assertEqual(self.store.get("fake"), {"token": "good", "user": "you"})

    def test_test_does_not_save(self):
        self.store.save("fake", {"token": "good"})
        status, data = self.post("/api/sources/fake/test", {"values": {"token": "bad"}})
        self.assertEqual(status, 200)
        self.assertEqual(data, {"ok": False, "error": "Fake didn't accept the token.", "fix": "Copy the token again."})
        self.assertEqual(self.store.get("fake"), {"token": "good"})
        status, data = self.post("/api/sources/fake/test", {"values": {"token": "new-good"}})
        self.assertEqual(data, {"ok": True, "message": "Fake Music accepted the token."})
        self.assertEqual(self.store.get("fake"), {"token": "good"})

    def test_test_with_saved_values_clears_problem(self):
        self.store.save("fake", {"token": "good", "user": "me"})
        self.store.mark_invalid("fake", "was broken")
        status, data = self.post("/api/sources/fake/test")
        self.assertTrue(data["ok"])
        self.assertEqual(self.store.status(REGISTRY["fake"])["state"], "ready")

    def test_disconnect_clears_tokens_only(self):
        self.store.save("spotify", {"client_id": "cid", "access_token": "a", "refresh_token": "r", "expires_at": 9})
        status, data = self.post("/api/sources/spotify/disconnect")
        self.assertEqual(status, 200)
        self.assertEqual(self.store.get("spotify"), {"client_id": "cid"})

    def test_cross_origin_post_refused(self):
        status, _ = self.post("/api/library", {"id": "folder"}, headers={"Origin": "http://evil.test"})
        self.assertEqual(status, 403)
        status, _ = self.post("/api/library", {"id": "folder"}, headers={"Content-Type": "text/plain"})
        self.assertEqual(status, 403)
        self.assertNotIn('"folder"', self.config_path.read_text())
        status, _ = self.post("/api/status", headers={"Origin": self.base})
        self.assertEqual(status, 404)  # same origin is let through (and this route only exists as GET)

    def test_v1_routes_are_gone(self):
        self.assertEqual(self.get("/login")[0], 404)
        self.assertEqual(self.post("/api/build", {})[0], 404)
        self.assertEqual(self.post("/api/logout", {})[0], 404)
        status = self.get("/api/status")[1]
        self.assertNotIn("logged_in", status)
        self.assertNotIn("spotify", self.analyzed()["tracks"][0])

    def test_unknown_source_404(self):
        self.assertEqual(self.post("/api/sources/nope/test")[0], 404)
        self.assertEqual(self.post("/api/sources/nope/credentials", {"values": {}})[0], 404)
        self.assertEqual(self.post("/api/analyze", {"source": "nope", "url": "x"})[0], 404)
        self.assertEqual(self.get("/login/fake")[0], 404)  # no browser sign-in for this one

    def test_bad_json(self):
        req = urllib.request.Request(self.base + "/api/analyze", data=b"{nope", method="POST",
                                     headers={"Content-Type": "application/json"})
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(req)
        self.assertEqual(cm.exception.code, 400)


class Task17(ApiTest):
    def test_analyze_payload(self):
        data = self.analyzed()
        self.assertEqual(data["playlist"]["source"], "fake")
        self.assertEqual(data["playlist"]["service"], "Fake Music")
        self.assertEqual([t["status"] for t in data["tracks"]], ["exact", "close", "missing"])
        self.assertEqual(data["tracks"][0]["track"]["title"], "Creep")
        self.assertEqual(data["library_count"], 2)
        self.assertEqual(data["library_warning"], "")

    def test_analyze_passes_on_library_warning(self):
        with mock.patch.object(web.App, "library_warning", lambda app: "Strawberry is behind."):
            data = self.analyzed()
        self.assertEqual(data["library_warning"], "Strawberry is behind.")

    def test_library_test_passes_on_warning(self):
        from collector.libraries.folder import FolderLibrary
        music = Path(self.tmp.name) / "Music"
        music.mkdir()
        with mock.patch.object(FolderLibrary, "warning", lambda self, path, folders: "Behind."):
            status, data = self.post("/api/library/test", {"id": "folder", "folders": [str(music)]})
        self.assertEqual((status, data), (200, {"ok": True, "message": "Found 0 tracks", "warning": "Behind."}))

    def test_analyze_detects_source_from_link(self):
        self.ready_fake()
        status, data = self.post("/api/analyze", {"url": LINK})
        self.assertEqual((status, data["playlist"]["source"]), (200, "fake"))

    def test_analyze_credentials_error_shape(self):
        self.store.save("fake", {"token": "bad"})
        status, data = self.post("/api/analyze", {"source": "fake", "url": LINK})
        self.assertEqual(status, 401)
        self.assertEqual(data, {"error": "Fake didn't accept the token.", "fix": "Copy the token again.",
                                "code": "credentials", "source": "fake"})
        sources = {s["id"]: s for s in self.get("/api/sources")[1]}
        self.assertEqual(sources["fake"]["status"]["state"], "invalid")
        self.assertEqual(sources["fake"]["status"]["fix"], "Copy the token again.")

    def test_wrong_source_hint(self):
        self.ready_fake()
        status, data = self.post("/api/analyze", {"source": "fake", "url": "https://other.test/pl"})
        self.assertEqual(status, 400)
        self.assertEqual((data["code"], data["detected"]), ("wrong_source", "other"))
        self.assertIn("Other Music", data["error"])

    def test_library_error_code(self):
        from collector.libraries import LibraryError

        def broken(app):
            raise LibraryError("Strawberry's library file wasn't found.", fix="Open Strawberry once.")
        with mock.patch.object(web.App, "load_library", broken):
            self.ready_fake()
            status, data = self.post("/api/analyze", {"source": "fake", "url": LINK})
        self.assertEqual((status, data["code"], data["fix"]), (400, "library", "Open Strawberry once."))

    def test_resolve_requires_all_decisions(self):
        data = self.analyzed()
        status, err = self.post("/api/resolve", {"analysis_id": data["analysis_id"], "decisions": {}})
        self.assertEqual(status, 400)
        self.assertIn("Smells Like Teen Spirit", err["error"])
        status, totals = self.post("/api/resolve", {"analysis_id": data["analysis_id"], "decisions": {"1": "missing"}})
        self.assertEqual((status, totals), (200, {"matched": 1, "missing": 2}))

    def test_resolve_remembers_choice(self):
        self.resolved()
        data = self.analyzed()
        self.assertEqual(data["tracks"][1]["remembered"], "/music/Nirvana/Teen.flac")

    def test_expired_analysis(self):
        status, data = self.post("/api/resolve", {"analysis_id": "gone", "decisions": {}})
        self.assertEqual(status, 400)
        self.assertIn("expired", data["error"])

    def test_export_before_resolve(self):
        data = self.analyzed()
        status, err = self.post("/api/export/playlist", {"analysis_id": data["analysis_id"], "formats": ["m3u8"]})
        self.assertEqual(status, 400)

    def test_export_writes_selected_formats(self):
        aid = self.resolved()
        status, data = self.post("/api/export/playlist", {"analysis_id": aid, "formats": ["m3u8", "xspf", "csv"],
                                                          "path_style": "absolute"})
        self.assertEqual(status, 200, data)
        files = [Path(f) for f in data["files"]]
        self.assertEqual({f.name for f in files}, {"Road Trip.m3u8", "Road Trip.xspf", "Road Trip.csv"})
        by_ext = {f.suffix: f for f in files}
        self.assertEqual({f.parent for f in files}, {self.playlists})  # every playlist format goes there
        self.assertIn("/music/Nirvana/Teen.flac", by_ext[".m3u8"].read_text())
        # A chosen folder takes every format.
        chosen = Path(self.tmp.name) / "Chosen"
        _, data = self.post("/api/export/playlist", {"analysis_id": aid, "formats": ["m3u8", "wpl"],
                                                     "path_style": "relative", "folder": str(chosen)})
        self.assertEqual({Path(f).parent for f in data["files"]}, {chosen})

    def test_export_rejects_bad_input(self):
        aid = self.resolved()
        for body in ({"formats": []}, {"formats": ["mp3"]}, {"formats": ["m3u8"], "path_style": "weird"}):
            status, _ = self.post("/api/export/playlist", {"analysis_id": aid, **body})
            self.assertEqual(status, 400, body)

    def test_export_missing(self):
        aid = self.resolved()
        status, data = self.post("/api/export/missing", {"analysis_id": aid, "format": "md", "nextup": True})
        self.assertEqual(status, 200, data)
        self.assertEqual(Path(data["file"]), self.exports / "Road Trip missing tracks.md")
        self.assertIn('Get "Karma Police" by Radiohead', Path(data["file"]).read_text())
        self.assertIsNone(data["note_path"])  # NextUp isn't set up in this config
        status, _ = self.post("/api/export/missing", {"analysis_id": aid, "format": "pdf"})
        self.assertEqual(status, 400)

    def test_reveal_refuses_unknown_path(self):
        status, _ = self.post("/api/reveal", {"path": str(self.config_path)})
        self.assertEqual(status, 403)
        status, _ = self.post("/api/reveal", {"path": ""})
        self.assertEqual(status, 403)

    def test_reveal_opens_written_file_folder(self):
        aid = self.resolved()
        _, data = self.post("/api/export/playlist", {"analysis_id": aid, "formats": ["csv"]})
        with mock.patch.object(web.subprocess, "Popen") as popen:
            status, _ = self.post("/api/reveal", {"path": data["files"][0]})
        self.assertEqual(status, 200)
        self.assertEqual(popen.call_args[0][0][-1], str(self.playlists.resolve()))

    def test_status_names_both_default_folders(self):
        _, data = self.get("/api/status")
        self.assertEqual((data["playlist_dir"], data["missing_dir"]), (str(self.playlists), str(self.exports)))

    def test_choose_folder_opens_the_desktop_picker(self):
        with mock.patch.object(web.folder_picker, "choose_folder", return_value="/home/me/Docs") as choose:
            status, data = self.post("/api/choose-folder", {"start": "~/Documents"})
        self.assertEqual((status, data), (200, {"folder": "/home/me/Docs"}))
        self.assertEqual(choose.call_args[0][0], "~/Documents")
        with mock.patch.object(web.folder_picker, "choose_folder", return_value=None):
            self.assertEqual(self.post("/api/choose-folder", {})[1], {"folder": None})  # cancelled

    def test_choose_folder_without_a_picker(self):
        from collector.folder_picker import PickerUnavailable
        with mock.patch.object(web.folder_picker, "choose_folder", side_effect=PickerUnavailable("Type it.")):
            status, data = self.post("/api/choose-folder", {"start": "/x"})
        self.assertEqual((status, data["error"]), (501, "Type it."))



class Icons(unittest.TestCase):
    def test_every_named_icon_exists(self):
        from collector.exporters.players import PLAYERS
        from collector.libraries import LIBRARIES
        from collector.sources.fake import FakeSource
        icons = web.STATIC / "icons"
        named = [("services", s.icon) for s in list(REGISTRY.values()) + [FakeSource()]]
        named += [("apps", lib.icon) for lib in LIBRARIES.values()]
        named += [("apps", p.icon) for p in PLAYERS.values()]
        for folder, name in named:
            self.assertTrue((icons / folder / name).is_file(), f"{folder}/{name}")
        self.assertTrue((icons / "SOURCES.md").is_file())


if __name__ == "__main__":
    unittest.main()
