import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from collector import sources
from collector.credentials import CredentialStore
from collector.sources.base import CredentialError, Field, Source, SourceError


class FakeTidal(Source):
    id = "tidal"
    name = "TIDAL"
    fields = [Field("client_id", "Client ID"), Field("client_secret", "Client secret", secret=True),
              Field("country", "Country", required=False)]
    link_patterns = (r"tidal\.com/(browse/)?playlist/",)


class FakeOAuth(Source):
    id = "oauth"
    name = "OAuth"
    fields = [Field("client_id", "Client ID")]
    uses_oauth = True


class NoFields(Source):
    id = "file"
    name = "File"
    input = "file"


TIDAL = FakeTidal()


class Store(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "sub" / "credentials.json"
        self.store = CredentialStore(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    @unittest.skipIf(os.name == "nt", "POSIX file modes")
    def test_file_mode_is_600(self):
        self.store.save("tidal", {"client_id": "a", "client_secret": "b"})
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_saved_values_survive_reload(self):
        self.store.save("tidal", {"client_id": "a", "client_secret": "b"})
        self.assertEqual(CredentialStore(self.path).get("tidal"), {"client_id": "a", "client_secret": "b"})

    def test_blank_secret_keeps_old(self):
        self.store.save("tidal", {"client_id": "a", "client_secret": "b"})
        self.store.save("tidal", {"client_id": "a2", "client_secret": ""})
        self.assertEqual(self.store.get("tidal"), {"client_id": "a2", "client_secret": "b"})

    def test_get_returns_a_copy(self):
        self.store.save("tidal", {"client_id": "a"})
        self.store.get("tidal")["client_id"] = "changed"
        self.assertEqual(self.store.get("tidal")["client_id"], "a")

    def test_remove_keys(self):
        self.store.save("tidal", {"client_id": "a", "access_token": "t"})
        self.store.remove("tidal", ["access_token", "missing_key"])
        self.assertEqual(self.store.get("tidal"), {"client_id": "a"})

    def test_public_view_hides_secrets(self):
        self.store.save("tidal", {"client_id": "a", "client_secret": "b"})
        view = self.store.public_view(TIDAL)
        self.assertEqual(view["client_secret"], {"set": True})
        self.assertEqual(view["client_id"], {"value": "a"})
        self.assertEqual(view["country"], {"value": ""})
        self.assertNotIn("b", json.dumps(view))

    def test_status_cycle(self):
        self.assertEqual(self.store.status(TIDAL)["state"], "needs_setup")
        self.store.save("tidal", {"client_id": "a", "client_secret": "b"})
        self.assertEqual(self.store.status(TIDAL)["state"], "ready")  # country is optional
        self.store.mark_invalid("tidal", "HTTP 401", "Copy it again")
        self.assertEqual(self.store.status(TIDAL), {"state": "invalid", "error": "HTTP 401", "fix": "Copy it again"})
        self.store.mark_ok("tidal")
        self.assertEqual(self.store.status(TIDAL)["state"], "ready")

    def test_oauth_needs_token(self):
        src = FakeOAuth()
        self.store.save("oauth", {"client_id": "a"})
        self.assertEqual(self.store.status(src)["state"], "needs_setup")
        self.store.save("oauth", {"refresh_token": "r"})
        self.assertEqual(self.store.status(src)["state"], "ready")

    def test_source_without_fields_is_ready(self):
        self.assertEqual(self.store.status(NoFields())["state"], "ready")

    def test_clear(self):
        self.store.save("tidal", {"client_id": "a", "client_secret": "b"})
        self.store.mark_invalid("tidal", "x", "y")
        self.store.clear("tidal")
        self.assertEqual(self.store.get("tidal"), {})
        self.assertEqual(self.store.status(TIDAL)["state"], "needs_setup")

    def test_corrupt_file_is_empty_store(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("{")
        self.assertEqual(CredentialStore(self.path).get("tidal"), {})


class Registry(unittest.TestCase):
    def test_get_source_unknown(self):
        with self.assertRaises(KeyError):
            sources.get_source("nope")

    def test_detect(self):
        with mock.patch.dict(sources.REGISTRY, {"tidal": TIDAL}, clear=True):
            self.assertEqual(sources.detect("https://tidal.com/browse/playlist/abc"), "tidal")
            self.assertIsNone(sources.detect("https://example.com/x"))
            self.assertIs(sources.get_source("tidal"), TIDAL)

    def test_matches_link(self):
        self.assertTrue(TIDAL.matches_link("https://tidal.com/browse/playlist/abc"))
        self.assertFalse(TIDAL.matches_link("https://open.spotify.com/playlist/abc"))

    def test_credential_error_carries_fix(self):
        e = CredentialError("Bad key", fix="Copy it again")
        self.assertIsInstance(e, SourceError)
        self.assertEqual((str(e), e.fix), ("Bad key", "Copy it again"))

    def test_file_source_refuses_links_by_default(self):
        with self.assertRaises(SourceError):
            NoFields().parse_link("x")
        with self.assertRaises(SourceError):
            TIDAL.parse_file("a.xml", b"")


if __name__ == "__main__":
    unittest.main()
