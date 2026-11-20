import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from collector import http, updates
from collector.updates import CHECK_EVERY, LATEST_URL, Updater, parse_tag, parse_version

HTML_URL = "https://github.com/rgaspary/TheCollector/releases/tag/v2.1.0"


class FakeResponse:
    def __init__(self, body: bytes):
        self.body = body

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class Opener:
    """Answers the latest-release URL with `answer` (a dict or an exception) and counts calls."""

    def __init__(self, tag="v2.1.0"):
        self.answer = {"tag_name": tag, "html_url": HTML_URL}
        self.calls = 0

    def __call__(self, req, timeout=None):
        assert req.full_url == LATEST_URL
        self.calls += 1
        if isinstance(self.answer, Exception):
            raise self.answer
        return FakeResponse(json.dumps(self.answer).encode())


class UpdaterTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "app"
        self.root.mkdir()
        self.state = Path(tmp.name) / "data" / "update.json"
        self.now = 0.0
        self.opener = Opener()
        patcher = mock.patch.object(http, "opener", self.opener)
        patcher.start()
        self.addCleanup(patcher.stop)
        sleeper = mock.patch.object(http, "sleep", lambda s: None)
        sleeper.start()
        self.addCleanup(sleeper.stop)

    def make(self, current="2.0.0"):
        return Updater(self.root, self.state, current, lambda: self.now)

    def test_parse(self):
        self.assertEqual(parse_tag("v2.1.0"), (2, 1, 0))
        self.assertIsNone(parse_tag("2.1.0"))
        self.assertIsNone(parse_tag("v2.1"))
        self.assertIsNone(parse_tag("v2.1.0-rc1"))
        self.assertEqual(parse_version("2.0.0-dev"), (2, 0, 0))

    def test_newer_release_shows(self):
        info = self.make().info()
        self.assertEqual(info["latest"], "2.1.0")
        self.assertIs(info["show"], True)
        self.assertEqual(info["state"], "idle")
        self.assertIs(info["git"], False)
        self.assertEqual(info["url"], HTML_URL)
        self.assertEqual(info["current"], "2.0.0")

    def test_same_or_older_release_hidden(self):
        self.opener.answer["tag_name"] = "v2.0.0"
        self.assertIs(self.make().info()["show"], False)
        self.state.unlink()
        self.opener.answer["tag_name"] = "v1.9.0"
        self.assertIs(self.make().info()["show"], False)

    def test_checks_once_a_day(self):
        up = self.make()
        up.info()
        self.now = 3600
        up.info()
        self.assertEqual(self.opener.calls, 1)
        self.now = CHECK_EVERY + 1
        up.info()
        self.assertEqual(self.opener.calls, 2)

    def test_failed_check_waits_a_day(self):
        self.opener.answer = urllib.error.HTTPError("https://x", 403, "no", {}, io.BytesIO(b""))
        up = self.make()
        info = up.info()
        self.assertIs(info["show"], False)
        self.assertIsNone(info["error"])
        self.now = 3600
        up.info()
        self.assertEqual(self.opener.calls, 1)

    def test_odd_answer_counts_as_no_update(self):
        self.opener.answer = {"message": "hello"}
        up = self.make()
        info = up.info()
        self.assertIs(info["show"], False)
        self.assertIsNone(info["error"])
        self.now = 3600
        up.info()
        self.assertEqual(self.opener.calls, 1)

    def test_skip_hides_until_newer(self):
        up = self.make()
        up.info()
        up.skip("2.1.0")
        self.assertIs(up.info()["show"], False)
        fresh = self.make()
        self.assertIs(fresh.info()["show"], False)
        self.opener.answer["tag_name"] = "v2.2.0"
        self.now = CHECK_EVERY + 1
        self.assertIs(fresh.info()["show"], True)

    def test_skip_empty_clears(self):
        up = self.make()
        up.skip("2.1.0")
        up.skip("")
        self.assertIs(up.info()["show"], True)

    def test_corrupt_state_file_is_ignored(self):
        self.state.parent.mkdir(parents=True)
        self.state.write_text("{nope")
        self.assertIs(self.make().info()["show"], True)

    def test_git_checkout_flagged(self):
        (self.root / ".git").mkdir()
        self.assertIs(self.make().info()["git"], True)

    def test_ready_update_hides_popup(self):
        (self.root / ".update").mkdir()
        (self.root / ".update" / "ready.json").write_text(
            json.dumps({"version": "2.1.0", "folder": "staging-2.1.0"}))
        up = self.make()
        self.assertEqual(up.ready_version(), "2.1.0")
        info = up.info()
        self.assertEqual(info["state"], "ready")
        self.assertIs(info["show"], False)

    def test_no_ready_file(self):
        self.assertIsNone(self.make().ready_version())

    def test_init_does_no_io(self):
        self.make()
        self.assertEqual(self.opener.calls, 0)
        self.assertFalse(self.state.exists())

    def test_constants(self):
        self.assertEqual(updates.TARBALL_URL.format(version="2.1.0"),
                         "https://api.github.com/repos/rgaspary/TheCollector/tarball/v2.1.0")


if __name__ == "__main__":
    unittest.main()
