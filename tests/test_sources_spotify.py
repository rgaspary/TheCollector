import json
import tempfile
import time
import unittest
import urllib.parse
from pathlib import Path
from unittest import mock

from collector import config, http, sources
from collector.choices import MISSING, Choices
from collector.credentials import CredentialStore
from collector.sources.base import CredentialError, SourceError
from collector.sources.spotify import SpotifySource, migrate_v1, parse_playlist_id
from tests.fakes import Router, fixture, http_error

PID = "37i9dQZF1DXcBWIGoYBM5M"
LINK = f"https://open.spotify.com/playlist/{PID}"


def fresh_creds(**extra):
    return {"client_id": "cid", "access_token": "tok", "refresh_token": "ref",
            "expires_at": time.time() + 3600, **extra}


class SpotifyBase(unittest.TestCase):
    def route(self, routes):
        router = Router(routes)
        patcher = mock.patch.object(http, "opener", router)
        patcher.start()
        self.addCleanup(patcher.stop)
        sleep = mock.patch.object(http, "sleep", lambda s: None)
        sleep.start()
        self.addCleanup(sleep.stop)
        return router


class ParseLink(unittest.TestCase):
    def test_parse_playlist_id(self):
        self.assertEqual(parse_playlist_id(f"{LINK}?si=abc"), PID)
        self.assertEqual(parse_playlist_id(f"https://open.spotify.com/intl-es/playlist/{PID}"), PID)
        self.assertEqual(parse_playlist_id(f"spotify:playlist:{PID}"), PID)
        self.assertEqual(parse_playlist_id(PID), PID)
        with self.assertRaises(SourceError):
            parse_playlist_id("https://open.spotify.com/album/xyz")

    def test_registered_and_detected(self):
        self.assertIsInstance(sources.get_source("spotify"), SpotifySource)
        self.assertEqual(sources.detect(f"https://open.spotify.com/intl-es/playlist/{PID}"), "spotify")
        self.assertIsNone(sources.detect("https://tidal.com/browse/playlist/abc"))


class GetPlaylist(SpotifyBase):
    def routes(self, override: dict | None = None):
        routes = {
            ("GET", "fields=name"): fixture("spotify", "meta.json"),
            ("GET", "items?limit=50"): fixture("spotify", "page1.json"),
            ("GET", "offset=50"): fixture("spotify", "page2.json"),
        }
        routes.update(override or {})
        return routes

    def test_get_playlist_pages(self):
        router = self.route(self.routes())
        playlist = SpotifySource().get_playlist(LINK, fresh_creds())
        self.assertEqual((playlist.source, playlist.id, playlist.name), ("spotify", PID, "Road Trip"))
        self.assertEqual([t.title for t in playlist.tracks], ["Black Hole Sun", "Creep"])  # podcast and removed skipped
        self.assertEqual(router.requests[0].get_header("Authorization"), "Bearer tok")

    def test_to_track_reads_isrc(self):
        self.route(self.routes())
        first, second = SpotifySource().get_playlist(LINK, fresh_creds()).tracks
        self.assertEqual((first.id, first.isrc, first.duration, first.album), ("t1", "USAM19400313", 320, "Superunknown"))
        self.assertEqual(first.url, "https://open.spotify.com/track/t1")
        self.assertEqual((second.artists, second.isrc, second.duration), (["Radiohead", "Guest"], "", 239))

    def test_old_tracks_path_is_fallback(self):
        page = {"items": [{"track": fixture("spotify", "page2.json")["items"][0]["item"]}], "next": None}
        self.route(self.routes({("GET", "items?limit=50"): http_error(403), ("GET", "tracks?limit=100"): page}))
        self.assertEqual([t.title for t in SpotifySource().get_playlist(LINK, fresh_creds()).tracks], ["Creep"])

    def test_not_found_is_source_error(self):
        self.route(self.routes({("GET", "fields=name"): http_error(404)}))
        with self.assertRaises(SourceError) as cm:
            SpotifySource().get_playlist(LINK, fresh_creds())
        self.assertNotIsInstance(cm.exception, CredentialError)
        self.assertIn("couldn't find", str(cm.exception))

    def test_refreshes_expired_token(self):
        router = self.route(self.routes({("POST", "api/token"): {"access_token": "new", "expires_in": 3600}}))
        creds = fresh_creds(expires_at=0)
        SpotifySource().get_playlist(LINK, creds)
        self.assertEqual(creds["access_token"], "new")
        self.assertEqual(creds["refresh_token"], "ref")  # kept when Spotify doesn't send a new one
        self.assertEqual(router.calls("POST", "api/token"), 1)

    def test_refresh_failure_raises_credential_error(self):
        self.route(self.routes({("POST", "api/token"): http_error(400, '{"error":"invalid_grant"}')}))
        with self.assertRaises(CredentialError) as cm:
            SpotifySource().get_playlist(LINK, fresh_creds(expires_at=0))
        self.assertIn("Connect", cm.exception.fix)

    def test_401_after_refresh_is_credential_error(self):
        self.route(self.routes({("GET", "fields=name"): http_error(401),
                                  ("POST", "api/token"): {"access_token": "new", "expires_in": 3600}}))
        with self.assertRaises(CredentialError):
            SpotifySource().get_playlist(LINK, fresh_creds())

    def test_not_connected(self):
        with self.assertRaises(CredentialError):
            SpotifySource().get_playlist(LINK, {"client_id": "cid"})

    def test_network_error_is_source_error(self):
        import urllib.error
        self.route(self.routes({("GET", "fields=name"): urllib.error.URLError("down")}))
        with self.assertRaises(SourceError) as cm:
            SpotifySource().get_playlist(LINK, fresh_creds())
        self.assertIn("reach Spotify", str(cm.exception))


class TestAndLogin(SpotifyBase):
    def test_test_returns_ok_message(self):
        self.route({("GET", "/me"): {"display_name": "Gee", "id": "g"}})
        self.assertIn("Spotify", SpotifySource().test(fresh_creds()))

    def test_test_without_client_id(self):
        with self.assertRaises(CredentialError):
            SpotifySource().test({})

    def test_login_round_trip(self):
        router = self.route({("POST", "api/token"): {"access_token": "a", "refresh_token": "r", "expires_in": 3600}})
        src = SpotifySource()
        url = src.login_url({"client_id": "cid"}, "http://127.0.0.1:8766/callback")
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        self.assertEqual((q["client_id"][0], q["code_challenge_method"][0]), ("cid", "S256"))
        tokens = src.finish_login({"client_id": "cid"}, "code", q["state"][0], "http://127.0.0.1:8766/callback")
        self.assertEqual((tokens["access_token"], tokens["refresh_token"]), ("a", "r"))
        form = urllib.parse.parse_qs(router.requests[0].data.decode())
        self.assertEqual(form["grant_type"], ["authorization_code"])
        self.assertIn("code_verifier", form)

    def test_unknown_state_refused(self):
        with self.assertRaises(SourceError):
            SpotifySource().finish_login({"client_id": "cid"}, "code", "nope", "http://x/callback")

    def test_login_needs_client_id(self):
        with self.assertRaises(CredentialError):
            SpotifySource().login_url({}, "http://x/callback")


class Migration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.store = CredentialStore(self.dir / "credentials.json")
        self.cfg = mock.Mock(spec=config.Config, legacy_spotify_client_id="cid")

    def tearDown(self):
        self.tmp.cleanup()

    def test_migrate_v1_copies_client_id_and_token(self):
        token = self.dir / "token.json"
        token.write_text(json.dumps({"access_token": "a", "refresh_token": "r", "expires_at": 5}))
        migrate_v1(self.store, self.cfg, token)
        self.assertEqual(self.store.get("spotify"),
                         {"client_id": "cid", "access_token": "a", "refresh_token": "r", "expires_at": 5})

    def test_migrate_without_token_file(self):
        migrate_v1(self.store, self.cfg, self.dir / "missing.json")
        self.assertEqual(self.store.get("spotify"), {"client_id": "cid"})

    def test_migrate_keeps_existing_settings(self):
        self.store.save("spotify", {"client_id": "newer"})
        migrate_v1(self.store, self.cfg, self.dir / "missing.json")
        self.assertEqual(self.store.get("spotify"), {"client_id": "newer"})


class ChoiceKeys(unittest.TestCase):
    def test_choices_reads_bare_v1_key_for_spotify_only(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "choices.json"
            path.write_text(json.dumps({"t1": "/music/a.m4a"}))
            choices = Choices(path)
            self.assertEqual(choices.get("spotify", "t1"), "/music/a.m4a")
            self.assertIsNone(choices.get("tidal", "t1"))

    def test_choices_writes_prefixed_keys(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "choices.json"
            choices = Choices(path)
            choices.update("tidal", {"t9": MISSING})
            self.assertEqual(json.loads(path.read_text()), {"tidal:t9": MISSING})
            self.assertEqual(Choices(path).get("tidal", "t9"), MISSING)


if __name__ == "__main__":
    unittest.main()
