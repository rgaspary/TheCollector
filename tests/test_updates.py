import io
import json
import os
import shutil
import sys
import tarfile
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from collector import http, updates
from collector.updates import (
    CHECK_EVERY,
    LATEST_URL,
    TARBALL_URL,
    UpdateError,
    Updater,
    apply_staged,
    cleanup_previous,
    extract_release,
    parse_tag,
    parse_version,
    verify_staged,
)

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


class StreamResponse:
    """A download response: read in chunks, and says where the redirects ended up."""

    def __init__(self, body: bytes, url: str):
        self.stream = io.BytesIO(body)
        self.url = url

    def read(self, n=-1):
        return self.stream.read(n)

    def geturl(self):
        return self.url

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


TOP = "rgaspary-TheCollector-abc123"


def make_release(dir: Path, version: str, *, extra=None, broken=False) -> Path:
    """A release tarball shaped like GitHub's: one top folder holding the app.

    `extra` is a list of TarInfo (with optional bytes) to add as is, for unsafe members.
    """
    path = dir / f"release-{version}.tar.gz"
    init = f'__version__ = "{version}"\n' + ("raise SystemExit(1)\n" if broken else "")
    files = [("collector/__init__.py", init.encode(), 0o644), ("collector/web.py", b"", 0o644),
             ("collector/__main__.py", b"", 0o644), ("collector-launch.sh", b"#!/bin/sh\n", 0o755)]
    with tarfile.open(path, "w:gz") as tar:
        for name in (TOP, f"{TOP}/collector"):
            info = tarfile.TarInfo(name)
            info.type, info.mode = tarfile.DIRTYPE, 0o755
            tar.addfile(info)
        for name, data, mode in files:
            info = tarfile.TarInfo(f"{TOP}/{name}")
            info.size, info.mode = len(data), mode
            tar.addfile(info, io.BytesIO(data))
        for info, data in extra or []:
            tar.addfile(info, io.BytesIO(data) if data is not None else None)
    return path


class Opener:
    """Answers the latest-release URL with `answer` (a dict or an exception) and counts calls.

    The tarball URL is answered with the bytes of `tarball` (or raises it, if it's an exception).
    """

    def __init__(self, tag="v2.1.0"):
        self.answer = {"tag_name": tag, "html_url": HTML_URL}
        self.calls = 0
        self.tarball: Path | Exception | None = None

    def __call__(self, req, timeout=None):
        if req.full_url.startswith(TARBALL_URL.format(version="")):
            if isinstance(self.tarball, Exception):
                raise self.tarball
            return StreamResponse(self.tarball.read_bytes(),
                                  "https://codeload.github.com/rgaspary/TheCollector/legacy.tar.gz/v2.1.0")
        assert req.full_url == LATEST_URL
        self.calls += 1
        if isinstance(self.answer, Exception):
            raise self.answer
        return FakeResponse(json.dumps(self.answer).encode())


class FakeGitHub(unittest.TestCase):
    """An install folder, a state file and a fake GitHub behind http.opener."""

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


class UpdaterTest(FakeGitHub):
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

    def test_info_says_which_version_is_ready(self):
        (self.root / ".update").mkdir()
        (self.root / ".update" / "ready.json").write_text(
            json.dumps({"version": "2.1.0", "folder": "staging-2.1.0"}))
        self.opener.answer = {"tag_name": "v2.2.0", "html_url": "https://github.com/rgaspary/TheCollector/releases/tag/v2.2.0"}
        info = self.make().info()
        self.assertEqual(info["latest"], "2.2.0")
        self.assertEqual(info["ready"], "2.1.0")

    def test_ready_is_none_when_nothing_staged(self):
        self.assertIsNone(self.make().info()["ready"])

    def test_failed_check_keeps_last_good_answer(self):
        up = self.make()
        self.assertEqual(up.info()["latest"], "2.1.0")
        self.opener.answer = urllib.error.HTTPError("https://x", 403, "no", {}, io.BytesIO(b""))
        self.now = CHECK_EVERY + 1
        info = up.info()
        self.assertEqual(self.opener.calls, 2)
        self.assertEqual(info["latest"], "2.1.0")
        self.assertIsNone(info["error"])

    def test_no_ready_file(self):
        self.assertIsNone(self.make().ready_version())

    def test_init_does_no_io(self):
        self.make()
        self.assertEqual(self.opener.calls, 0)
        self.assertFalse(self.state.exists())

    def test_constants(self):
        self.assertEqual(updates.TARBALL_URL.format(version="2.1.0"),
                         "https://api.github.com/repos/rgaspary/TheCollector/tarball/v2.1.0")


def member(name, type=tarfile.REGTYPE, data=b"x", linkname=""):
    info = tarfile.TarInfo(name)
    info.type, info.linkname = type, linkname
    if type == tarfile.REGTYPE:
        info.size = len(data)
        return info, data
    return info, None


class StageTest(FakeGitHub):
    """Downloading, unpacking and checking a release."""

    def setUp(self):
        super().setUp()
        self.work = self.root.parent / "work"
        self.work.mkdir()

    def staged(self):
        return sorted(p.name for p in (self.root / ".update").glob("*")) if (self.root / ".update").exists() else []

    def ready_updater(self, **release):
        self.opener.tarball = make_release(self.work, release.pop("version", "2.1.0"), **release)
        up = self.make()
        up.info()  # sees 2.1.0 as the latest
        return up

    def test_stage_success(self):
        up = self.ready_updater()
        up.stage()
        self.assertEqual(up.state, "ready")
        self.assertIsNone(up.error)
        self.assertEqual(up.ready_version(), "2.1.0")
        self.assertEqual(json.loads((self.root / ".update" / "ready.json").read_text()),
                         {"version": "2.1.0", "folder": "staging-2.1.0"})
        launcher = self.root / ".update" / "staging-2.1.0" / "collector-launch.sh"
        self.assertTrue(launcher.stat().st_mode & 0o111)
        self.assertEqual(self.staged(), ["ready.json", "staging-2.1.0"])
        self.assertEqual(up.info()["state"], "ready")

    def assert_rejected(self, label, extra):
        """extract_release refuses the release with `extra` members added and writes nothing anywhere."""
        case = self.work / label.replace(" ", "-")
        case.mkdir()
        tar = make_release(case, "2.1.0", extra=extra)
        dest = case / "out" / "dest"
        dest.mkdir(parents=True)
        with self.assertRaises(UpdateError) as cm:
            extract_release(tar, dest)
        self.assertEqual(str(cm.exception), "The download looks damaged. Try again later.")
        self.assertEqual(sorted(p.name for p in case.iterdir()), ["out", tar.name])
        self.assertEqual([p.name for p in (case / "out").iterdir()], ["dest"])
        self.assertEqual(list(dest.iterdir()), [])

    def test_unsafe_members_rejected(self):
        bad = {
            "dotdot": member("../evil"),
            "absolute": member("/abs"),
            "symlink out": member(f"{TOP}/link", tarfile.SYMTYPE, linkname="/etc/passwd"),
            "relative symlink out": member(f"{TOP}/link", tarfile.SYMTYPE, linkname="../../evil"),
            "symlink inside": member(f"{TOP}/link", tarfile.SYMTYPE, linkname="collector/web.py"),
            "hardlink out": member(f"{TOP}/hard", tarfile.LNKTYPE, linkname="../evil"),
            "hardlink inside": member(f"{TOP}/hard", tarfile.LNKTYPE, linkname=f"{TOP}/collector/web.py"),
            "device": member(f"{TOP}/dev", tarfile.CHRTYPE),
            "fifo": member(f"{TOP}/fifo", tarfile.FIFOTYPE),
            "second top folder": member("other/file.txt"),
        }
        # Without the data filter (Python before 3.11.4) the hand checks are the only guard.
        for has_filter in (True, False):
            for label, (info, data) in bad.items():
                with self.subTest(label, data_filter=has_filter), \
                        mock.patch.object(updates, "HAS_DATA_FILTER", has_filter):
                    self.assert_rejected(f"{label} {has_filter}", [(info, data)])
        self.assertFalse(Path("/abs").exists())

    def test_symlink_chain_rejected(self):
        # Each link looks harmless on its own, but together they lead out of the folder.
        chain = [member(f"{TOP}/l", tarfile.SYMTYPE, linkname=".."),
                 member(f"{TOP}/l/m", tarfile.SYMTYPE, linkname=".."),
                 member(f"{TOP}/l/m/evil")]
        for has_filter in (True, False):
            with self.subTest(data_filter=has_filter), mock.patch.object(updates, "HAS_DATA_FILTER", has_filter):
                self.assert_rejected(f"chain {has_filter}", chain)

    def test_safe_release_extracts(self):
        for has_filter in (True, False):
            with self.subTest(data_filter=has_filter), mock.patch.object(updates, "HAS_DATA_FILTER", has_filter):
                dest = self.work / f"dest-{has_filter}"
                dest.mkdir()
                top = extract_release(make_release(self.work, "2.1.0"), dest)
                self.assertEqual(top, dest / TOP)
                self.assertTrue((top / "collector-launch.sh").stat().st_mode & 0o111)
                self.assertEqual((top / "collector" / "__init__.py").read_text(), '__version__ = "2.1.0"\n')

    def test_fallback_skips_python_filter(self):
        # So the fallback tests above prove the hand checks alone, not Python 3.14's default filter.
        with mock.patch.object(updates, "HAS_DATA_FILTER", False), \
                mock.patch.object(tarfile.TarFile, "extractall", autospec=True) as extractall:
            dest = self.work / "dest"
            dest.mkdir()
            with self.assertRaises(UpdateError):  # nothing was really extracted
                extract_release(make_release(self.work, "2.1.0"), dest)
        self.assertEqual(extractall.call_args.kwargs.get("filter"), "fully_trusted")

    def test_not_a_tarball(self):
        junk = self.work / "junk.tar.gz"
        junk.write_bytes(b"not a tarball at all")
        dest = self.work / "dest"
        dest.mkdir()
        with self.assertRaises(UpdateError):
            extract_release(junk, dest)

    def test_broken_release_not_staged(self):
        # The version line is right, so only importing the staged copy (not this one) can fail it.
        up = self.ready_updater(broken=True)
        # Even with this running copy on PYTHONPATH, the check must import the staged one.
        with mock.patch.dict(os.environ, {"PYTHONPATH": str(Path(updates.__file__).parents[1])}):
            up.stage()
        self.assertEqual(up.state, "failed")
        self.assertEqual(up.error, "The new version didn't pass its start-up check. Try again later.")
        self.assertIsNone(up.ready_version())
        self.assertEqual(self.staged(), [])

    def test_verify_imports_the_staged_copy(self):
        dest = self.work / "dest"
        dest.mkdir()
        good = extract_release(make_release(self.work, "2.1.0"), dest)
        verify_staged(good, "2.1.0")
        (good / "collector" / "web.py").write_text("raise SystemExit(3)\n")
        with self.assertRaises(UpdateError):
            verify_staged(good, "2.1.0")

    def test_wrong_version_not_staged(self):
        up = self.ready_updater(version="2.0.9")
        up.stage()
        self.assertEqual(up.state, "failed")
        self.assertEqual(up.error, "The download isn't the version it should be. Try again later.")
        self.assertIsNone(up.ready_version())
        self.assertEqual(self.staged(), [])

    def test_network_error_message(self):
        up = self.make()
        up.info()
        self.opener.tarball = urllib.error.URLError("no route")
        up.stage()
        self.assertEqual(up.state, "failed")
        self.assertEqual(up.error, "Couldn't reach GitHub. Check your internet connection and try again.")
        self.assertEqual(up.info()["error"], up.error)
        self.assertEqual(self.staged(), [])

    def test_unwritable_folder_fails_cleanly(self):
        up = self.ready_updater()
        with mock.patch.object(updates, "extract_release", side_effect=OSError(28, "No space left on device")):
            up.stage()
        self.assertEqual(up.state, "failed")
        self.assertEqual(up.error, "Couldn't save the update. Check that there's free space on your disk and try again.")
        self.assertEqual(self.staged(), [])

    def test_git_checkout_refuses_download(self):
        (self.root / ".git").mkdir()
        up = self.ready_updater()
        with self.assertRaises(UpdateError) as cm:
            up.start_download()
        self.assertEqual(str(cm.exception), "This copy is a git checkout. Update it with git.")
        self.assertEqual(up.state, "idle")

    def test_start_download_runs_in_background(self):
        up = self.ready_updater()
        info = up.start_download()
        self.assertIn(info["state"], ("downloading", "ready"))
        up.thread.join(30)
        self.assertEqual(up.info()["state"], "ready")
        self.assertEqual(up.ready_version(), "2.1.0")

    def test_start_download_once_at_a_time(self):
        up = self.ready_updater()
        up.state = "downloading"
        with mock.patch.object(updates.threading, "Thread") as thread:
            self.assertEqual(up.start_download()["state"], "downloading")
            thread.assert_not_called()
        up.state = "idle"
        up.stage()
        with mock.patch.object(updates.threading, "Thread") as thread:
            self.assertEqual(up.start_download()["state"], "ready")
            thread.assert_not_called()

    def test_retry_after_failure(self):
        up = self.ready_updater()
        self.opener.tarball, release = urllib.error.URLError("no route"), self.opener.tarball
        up.stage()
        self.assertEqual(up.state, "failed")
        self.opener.tarball = release
        up.stage()
        self.assertEqual(up.state, "ready")
        self.assertIsNone(up.error)

    def test_nothing_newer_to_download(self):
        self.opener.answer["tag_name"] = "v2.0.0"
        up = self.ready_updater()
        up.stage()
        self.assertEqual(up.state, "failed")
        self.assertIsNone(up.ready_version())


def make_install(root: Path, version: str = "2.1.0") -> Path:
    """An installed copy with the person's own files, and `version` staged and marked ready."""
    (root / "collector").mkdir(parents=True)
    (root / "collector" / "old.py").write_text("old")
    (root / "config.toml").write_text("mine")
    (root / "collector.log").write_text("log")
    (root / ".git").mkdir()
    (root / ".git" / "HEAD").write_text("ref")
    (root / "static").mkdir()
    (root / "static" / "old.css").write_text("old")
    staging = root / ".update" / f"staging-{version}"
    (staging / "collector").mkdir(parents=True)
    (staging / "collector" / "__init__.py").write_text(f'__version__ = "{version}"\n')
    (staging / "collector" / "new.py").write_text("new")
    (staging / "static").mkdir()
    (staging / "static" / "new.css").write_text("new")
    (root / ".update" / "ready.json").write_text(json.dumps({"version": version, "folder": staging.name}))
    return staging


def tree(root: Path) -> dict[str, str]:
    """Every file under root (outside .update) and what it holds."""
    return {str(p.relative_to(root)): p.read_text() for p in root.rglob("*")
            if p.is_file() and p.relative_to(root).parts[0] != ".update"}


class ApplyTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        self.out = io.StringIO()
        patcher = mock.patch("sys.stdout", self.out)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_apply_swaps_and_keeps_settings(self):
        make_install(self.root)

        self.assertIs(apply_staged(self.root), True)

        self.assertTrue((self.root / "collector" / "new.py").exists())
        self.assertFalse((self.root / "collector" / "old.py").exists())
        self.assertTrue((self.root / "static" / "new.css").exists())
        self.assertEqual((self.root / "config.toml").read_text(), "mine")
        self.assertEqual((self.root / "collector.log").read_text(), "log")
        self.assertEqual((self.root / ".git" / "HEAD").read_text(), "ref")
        self.assertFalse((self.root / ".update" / "ready.json").exists())
        self.assertFalse((self.root / ".update" / "staging-2.1.0").exists())
        previous = self.root / ".update" / f"previous-{updates.__version__}"
        self.assertTrue((previous / "collector" / "old.py").exists())
        self.assertFalse((previous / "config.toml").exists())

    def test_apply_rolls_back_on_failure(self):
        make_install(self.root)
        before = tree(self.root)
        real, calls = os.replace, []

        def flaky(src, dst):
            calls.append(src)
            if len(calls) == 2:
                raise OSError("permission denied")
            return real(src, dst)

        with mock.patch("os.replace", side_effect=flaky):
            self.assertIs(apply_staged(self.root), False)

        self.assertEqual(tree(self.root), before)
        self.assertFalse((self.root / ".update" / "ready.json").exists())
        self.assertFalse((self.root / ".update" / "staging-2.1.0").exists())
        self.assertFalse((self.root / ".update" / f"previous-{updates.__version__}").exists())
        self.assertIn("Couldn't switch to TheCollector 2.1.0", self.out.getvalue())

    def test_rollback_when_moving_new_files_in_fails(self):
        make_install(self.root)
        before = tree(self.root)
        real = os.replace

        def flaky(src, dst):
            if Path(src).parent.name == "staging-2.1.0" and Path(src).name == "static":
                raise OSError("disk full")
            return real(src, dst)

        with mock.patch("os.replace", side_effect=flaky):
            self.assertIs(apply_staged(self.root), False)

        self.assertEqual(tree(self.root), before)
        self.assertFalse((self.root / ".update" / "staging-2.1.0").exists())

    def test_failed_rollback_keeps_old_files_out_of_cleanup(self):
        make_install(self.root)
        real, calls = os.replace, []

        def flaky(src, dst):
            calls.append(src)
            if len(calls) == 2 or Path(src).parent.name.startswith("previous-"):
                raise OSError("permission denied")
            return real(src, dst)

        with mock.patch("os.replace", side_effect=flaky):
            self.assertIs(apply_staged(self.root), False)
        cleanup_previous(self.root)

        kept = self.root / ".update" / f"kept-{updates.__version__}"
        self.assertTrue((kept / "collector" / "old.py").exists())
        self.assertIn(str(kept), self.out.getvalue())

    def test_staged_copy_never_overwrites_kept_files(self):
        staging = make_install(self.root)
        (staging / "config.toml").write_text("theirs")
        (staging / ".git").mkdir()

        self.assertIs(apply_staged(self.root), True)

        self.assertEqual((self.root / "config.toml").read_text(), "mine")
        self.assertEqual((self.root / ".git" / "HEAD").read_text(), "ref")
        self.assertFalse((self.root / ".update" / "staging-2.1.0").exists())

    def test_leftover_staging_without_ready_is_removed(self):
        make_install(self.root)
        (self.root / ".update" / "ready.json").unlink()
        (self.root / ".update" / "staging-1.9.0").mkdir()
        (self.root / ".update" / "unpack-2.1.0").mkdir()
        (self.root / ".update" / "download-2.1.0.tar.gz").write_bytes(b"x")
        before = tree(self.root)

        self.assertIs(apply_staged(self.root), False)

        self.assertEqual(list((self.root / ".update").iterdir()), [])
        self.assertEqual(tree(self.root), before)

    def test_bad_ready_is_deleted_and_nothing_moves(self):
        bad = [
            "not json",
            json.dumps(["2.1.0"]),
            json.dumps({"version": "2.1", "folder": "staging-2.1"}),
            json.dumps({"version": "2.1.0", "folder": "../.."}),
            json.dumps({"version": "2.1.0", "folder": "staging-2.0.0"}),
            json.dumps({"version": "2.1.0"}),
            json.dumps({"version": 2, "folder": "staging-2"}),
        ]
        for body in bad:
            with self.subTest(body=body):
                root = Path(tempfile.mkdtemp())
                self.addCleanup(shutil.rmtree, root, True)
                make_install(root)
                (root / ".update" / "staging-2.0.0").mkdir()
                (root / ".update" / "ready.json").write_text(body)
                before = tree(root)

                self.assertIs(apply_staged(root), False)

                self.assertEqual(tree(root), before)
                self.assertEqual(list((root / ".update").iterdir()), [])

    def test_older_or_same_version_is_never_applied(self):
        for version in ("2.0.0", "1.9.9"):
            with self.subTest(version=version):
                root = Path(tempfile.mkdtemp())
                self.addCleanup(shutil.rmtree, root, True)
                make_install(root, version)
                before = tree(root)

                self.assertIs(apply_staged(root, current="2.0.0"), False)

                self.assertEqual(tree(root), before)
                self.assertEqual(list((root / ".update").iterdir()), [])

    def test_newer_than_a_dev_build_is_applied(self):
        make_install(self.root)

        self.assertIs(apply_staged(self.root, current="2.0.0-dev"), True)

    def test_ready_pointing_at_missing_or_broken_copy_is_refused(self):
        staging = make_install(self.root)
        (staging / "collector" / "__init__.py").unlink()
        before = tree(self.root)

        self.assertIs(apply_staged(self.root), False)

        self.assertEqual(tree(self.root), before)
        self.assertEqual(list((self.root / ".update").iterdir()), [])

    def test_previous_left_from_before_is_replaced(self):
        make_install(self.root)
        stale = self.root / ".update" / f"previous-{updates.__version__}" / "collector"
        stale.mkdir(parents=True)
        (stale / "stale.py").write_text("stale")

        self.assertIs(apply_staged(self.root), True)

        previous = self.root / ".update" / f"previous-{updates.__version__}"
        self.assertTrue((previous / "collector" / "old.py").exists())
        self.assertFalse((previous / "collector" / "stale.py").exists())
        self.assertTrue((self.root / "collector" / "new.py").exists())

    def test_nothing_staged(self):
        (self.root / "collector").mkdir()

        self.assertIs(apply_staged(self.root), False)

        self.assertFalse((self.root / ".update").exists())
        self.assertEqual([p.name for p in self.root.iterdir()], ["collector"])

    def test_cleanup_previous(self):
        (self.root / ".update" / "previous-2.0.0" / "collector").mkdir(parents=True)
        (self.root / ".update" / "previous-2.0.0" / "collector" / "old.py").write_text("old")
        (self.root / ".update" / "ready.json").write_text("{}")

        cleanup_previous(self.root)

        self.assertFalse((self.root / ".update" / "previous-2.0.0").exists())
        self.assertTrue((self.root / ".update" / "ready.json").exists())
        cleanup_previous(self.root / "missing")  # no .update at all is fine


class StartupLockTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)

    def test_only_one_process_gets_the_lock(self):
        first = updates.startup_lock(self.root)
        self.addCleanup(first.close)

        self.assertIsNotNone(first)
        self.assertTrue((self.root / ".update" / "lock").exists())
        self.assertIsNone(updates.startup_lock(self.root))

    def test_lock_is_free_again_once_the_holder_closes(self):
        first = updates.startup_lock(self.root)
        first.close()

        second = updates.startup_lock(self.root)
        self.addCleanup(second.close)
        self.assertIsNotNone(second)

    def test_lock_file_survives_leftover_clean_up(self):
        handle = updates.startup_lock(self.root)
        self.addCleanup(handle.close)

        self.assertIs(apply_staged(self.root), False)
        cleanup_previous(self.root)

        self.assertTrue((self.root / ".update" / "lock").exists())

    def test_unwritable_install_folder_gives_no_lock(self):
        self.assertIsNone(updates.startup_lock(self.root / "missing" / "deeper"))


class RestartTest(unittest.TestCase):
    def test_restart_adds_no_browser(self):
        with mock.patch("os.execv") as execv:
            updates.restart([])
            execv.assert_called_once_with(sys.executable, [sys.executable, "-m", "collector", "--no-browser"])

    def test_restart_keeps_no_browser_once(self):
        with mock.patch("os.execv") as execv:
            updates.restart(["--no-browser"])
            execv.assert_called_once_with(sys.executable, [sys.executable, "-m", "collector", "--no-browser"])


if __name__ == "__main__":
    unittest.main()
