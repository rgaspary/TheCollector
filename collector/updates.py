"""Checking for a newer TheCollector release, and the update state the app shows."""
import gzip
import json
import os
import posixpath
import re
import shutil
import subprocess
import sys
import tarfile
import threading
import time
import zlib
from collections.abc import Callable
from pathlib import Path
from typing import NoReturn

from . import __version__, config, http
from .files import atomic_write

REPO = "rgaspary/TheCollector"
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
TARBALL_URL = "https://api.github.com/repos/" + REPO + "/tarball/v{version}"
CHECK_EVERY = 24 * 3600
# Folders and files the download leaves in .update/ on its way to being ready.
LEFTOVERS = ("staging-", "unpack-", "download-")
# Never moved out of the way when a new version is put in place: the person's own data and our workspace.
KEEP = frozenset({"config.toml", "collector.log", ".update", ".git", ".venv"})
GITHUB_HOSTS = ("api.github.com", "github.com", "codeload.github.com")

# A release is a few MB; anything that unpacks to more than this is not one of ours (or is a zip bomb).
MAX_UNPACKED = 500_000_000
# filter="data" arrived in 3.11.4; before that we rely on our own checks alone.
HAS_DATA_FILTER = hasattr(tarfile, "data_filter")

_TAG = re.compile(r"v(\d+)\.(\d+)\.(\d+)")

DAMAGED = "The download looks damaged. Try again later."
NO_GITHUB = "Couldn't reach GitHub. Check your internet connection and try again."
NO_SPACE = "Couldn't save the update. Check that there's free space on your disk and try again."
GIT_CHECKOUT = "This copy is a git checkout. Update it with git."


class UpdateError(Exception):
    """A problem with updating. The message is shown to the person as is, so keep it plain."""


def parse_tag(tag: str) -> tuple[int, int, int] | None:
    """Read a release tag like "v2.1.0". Anything else (no "v", a suffix, two numbers) is None."""
    m = _TAG.fullmatch(tag) if isinstance(tag, str) else None
    return tuple(int(g) for g in m.groups()) if m else None


def parse_version(v: str) -> tuple[int, int, int]:
    """Read the installed version, ignoring a suffix: "2.0.0-dev" is (2, 0, 0)."""
    nums = re.match(r"(\d+)\.(\d+)\.(\d+)", v)
    return tuple(int(g) for g in nums.groups()) if nums else (0, 0, 0)


def _check_members(members: list[tarfile.TarInfo]) -> str:
    """Refuse anything that could write outside the folder, and return the one top-level folder's name.

    Links are refused outright: our releases never contain any, and a chain of links that each look
    harmless (l -> .., l/m -> ..) can still lead out of the folder.
    """
    tops, total = set(), 0
    for m in members:
        if posixpath.isabs(m.name) or ".." in m.name.split("/") or not (m.isfile() or m.isdir()):
            raise UpdateError(DAMAGED)
        name = posixpath.normpath(m.name)
        total += m.size
        if name != ".":
            tops.add(name.split("/")[0])
        if name in tops and not m.isdir():
            raise UpdateError(DAMAGED)  # the top level must be a folder, not a file
    if len(tops) != 1 or total > MAX_UNPACKED:
        raise UpdateError(DAMAGED)
    return tops.pop()


def extract_release(tar_path: Path, dest: Path) -> Path:
    """Unpack a release tarball into `dest` and return the single folder GitHub wraps it in.

    Every member is checked before anything is written, so an unsafe archive leaves `dest` empty. (A
    tarball cut short part-way can still leave some files behind: the caller deletes the folder.)
    Disk errors are let through as OSError, since they mean something different to the person.
    """
    try:
        with tarfile.open(tar_path, "r:gz") as tar:
            members = tar.getmembers()
            top = _check_members(members)
            if HAS_DATA_FILTER:
                tar.extractall(dest, filter="data")
            else:
                # Older 3.11 has no filter, so do its other job by hand: no setuid, no group/other write.
                for m in members:
                    m.mode &= 0o755
                if hasattr(tarfile, "fully_trusted_filter"):
                    # Only reached when tests switch the data filter off; ask for no filter, so they show
                    # the checks above are enough by themselves.
                    tar.extractall(dest, filter="fully_trusted")
                else:
                    tar.extractall(dest)
    except (tarfile.TarError, EOFError, zlib.error, gzip.BadGzipFile) as e:
        raise UpdateError(DAMAGED) from e
    folder = dest / top
    if folder.is_symlink() or not folder.is_dir():
        raise UpdateError(DAMAGED)
    return folder


def verify_staged(folder: Path, version: str) -> None:
    """Make sure the unpacked copy is the version we asked for and that it actually imports."""
    try:
        init = (folder / "collector" / "__init__.py").read_text(encoding="utf-8")
    except (OSError, UnicodeError) as e:
        raise UpdateError(DAMAGED) from e
    if not re.search(rf'^__version__ = "{re.escape(version)}"$', init, re.MULTILINE):
        raise UpdateError("The download isn't the version it should be. Try again later.")
    # -I leaves this running copy's folder (and PYTHONPATH) off the path, and cwd + "." puts the staged
    # copy on it, so it's the new code that has to import cleanly.
    try:
        done = subprocess.run(
            [sys.executable, "-I", "-c", "import sys; sys.path.insert(0, '.'); import collector.web, collector.__main__"],
            cwd=folder, timeout=60, capture_output=True, check=False)
    except (OSError, subprocess.SubprocessError) as e:
        raise UpdateError("The new version didn't pass its start-up check. Try again later.") from e
    if done.returncode != 0:
        raise UpdateError("The new version didn't pass its start-up check. Try again later.")


def _remove(path: Path) -> None:
    """Delete a file or folder if it's there. Used for tidying up, so it never raises."""
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path, ignore_errors=True)
    else:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def _message(e: Exception) -> str:
    """The plain sentence to show for a failed update."""
    if isinstance(e, UpdateError):
        return str(e)
    if isinstance(e, http.HttpError):
        return NO_GITHUB if e.status == 0 else "GitHub didn't send the update. Try again later."
    if isinstance(e, OSError):
        return NO_SPACE
    return "Something went wrong while getting the update. Try again later."


class Updater:
    """Knows the installed version, the newest release, and where an update stands."""

    def __init__(self, root: Path = config.ROOT, state_path: Path = config.DATA_DIR / "update.json",
                 current: str = __version__, clock: Callable[[], float] = time.time):
        self.root = root
        self.state_path = state_path
        self.current = current
        self.clock = clock
        # "downloading" and "failed" are set while an update is being fetched.
        self.state = "idle"
        self.error: str | None = None
        self.lock = threading.Lock()
        self.thread: threading.Thread | None = None

    def _load(self) -> dict:
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save(self, data: dict) -> None:
        try:
            atomic_write(self.state_path, json.dumps(data))
        except OSError:
            pass  # not worth bothering the person: we just ask GitHub again next time

    def _check(self, data: dict) -> None:
        """Ask GitHub for the latest release and record the answer. A failed check keeps the old one."""
        data["checked_at"] = self.clock()
        try:
            body = http.request_json("GET", LATEST_URL)
            tag = parse_tag(body.get("tag_name"))
            url = body.get("html_url")
        except (http.HttpError, AttributeError):
            return
        if tag is None or not isinstance(url, str):
            return
        data["latest"] = "{}.{}.{}".format(*tag)
        data["url"] = url

    def ready_version(self) -> str | None:
        """The version waiting to be switched on at the next start, if one is staged."""
        try:
            version = json.loads((self.root / ".update" / "ready.json").read_text(encoding="utf-8"))["version"]
        except (OSError, ValueError, KeyError, TypeError):
            return None
        return version if isinstance(version, str) else None

    def info(self) -> dict:
        with self.lock:
            data = self._load()
            checked = data.get("checked_at")
            if not isinstance(checked, (int, float)) or self.clock() - checked >= CHECK_EVERY:
                self._check(data)
                self._save(data)
            latest, url, skipped = data.get("latest"), data.get("url"), data.get("skipped")
            ready = self.ready_version()
            newer = (isinstance(latest, str) and parse_tag("v" + latest) is not None
                     and parse_tag("v" + latest) > parse_version(self.current))
            return {
                "current": self.current,
                "latest": latest if isinstance(latest, str) else None,
                "url": url if isinstance(url, str) else None,
                "skipped": skipped if isinstance(skipped, str) else None,
                "ready": ready,
                "state": "ready" if ready else self.state,
                "error": self.error,
                "git": (self.root / ".git").exists(),
                "show": bool(newer and latest != skipped and ready is None),
            }

    def skip(self, version: str) -> None:
        """Stop offering this version. An empty string clears the skip."""
        with self.lock:
            data = self._load()
            data["skipped"] = version
            self._save(data)

    def start_download(self) -> dict:
        """Start fetching the latest release in the background, unless one is already on its way or ready."""
        if (self.root / ".git").exists():
            raise UpdateError(GIT_CHECKOUT)
        with self.lock:
            if self.state != "downloading" and self.ready_version() is None:
                # Set here, not in the thread, so a second click straight after sees "downloading".
                self.state, self.error = "downloading", None
                self.thread = threading.Thread(target=self.stage, daemon=True)
                self.thread.start()
        return self.info()

    def stage(self) -> None:
        """Download, unpack and check the latest release, then mark it ready. Sets `state` and `error`.

        The lock is only held to read and set state, so info() keeps answering during the download.
        """
        with self.lock:
            latest = self._load().get("latest")
            self.state, self.error = "downloading", None
        work = self.root / ".update"
        version = latest if isinstance(latest, str) and parse_tag("v" + latest) else None
        tarball = work / f"download-{version}.tar.gz"
        unpack = work / f"unpack-{version}"
        staging = work / f"staging-{version}"
        error = None
        try:
            if version is None or parse_tag("v" + version) <= parse_version(self.current):
                raise UpdateError("There's no newer version to download.")
            work.mkdir(exist_ok=True)
            for leftover in (tarball, unpack, staging):  # from a run that was cut short
                _remove(leftover)
            http.download(TARBALL_URL.format(version=version), tarball, allowed_hosts=GITHUB_HOSTS)
            unpack.mkdir()
            extract_release(tarball, unpack).rename(staging)
            verify_staged(staging, version)
            atomic_write(work / "ready.json", json.dumps({"version": version, "folder": staging.name}))
        except Exception as e:  # noqa: BLE001 - this runs in a thread, so every failure must land in `error`
            if version is not None:
                _remove(staging)
            error = _message(e)
        finally:
            if version is not None:
                _remove(tarball)
                _remove(unpack)
        with self.lock:
            self.state, self.error = ("failed", error) if error else ("ready", None)


def startup_lock(root: Path) -> object | None:
    """Claim the install folder for this process, so two start-ups never swap files at once.

    Returns something to hold on to for as long as the process lives, or None when another copy of
    the app has it (or it can't be taken): then leave the files alone. The lock goes with the open
    file, and Python doesn't pass open files on through execv, so a restart lets go of it and the new
    process takes it again.
    """
    try:
        import fcntl
    except ImportError:  # Windows: no flock, so no lock (Windows isn't supported yet)
        return True
    try:
        (root / ".update").mkdir(exist_ok=True)
        handle = open(root / ".update" / "lock", "a")  # noqa: SIM115 - kept open on purpose
    except OSError:
        return None
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


def _staged_folder(work: Path, current: str) -> tuple[str, Path] | None:
    """The version and folder ready.json points at, or None if it isn't there or can't be trusted."""
    try:
        data = json.loads((work / "ready.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    version, folder = data.get("version"), data.get("folder")
    if not isinstance(version, str) or parse_tag("v" + version) is None or folder != f"staging-{version}":
        return None
    if parse_tag("v" + version) <= parse_version(current):
        return None  # never put an older version (or the same one) over the one that's installed
    staging = work / folder
    # A copy without its code would leave an app that won't open, so don't swap it in.
    if staging.is_symlink() or not staging.is_dir() or not (staging / "collector" / "__init__.py").is_file():
        return None
    return version, staging


def _clear_leftovers(work: Path) -> None:
    """Delete ready.json and every half-finished or abandoned download, whatever its version."""
    _remove(work / "ready.json")
    try:
        entries = list(work.iterdir())
    except OSError:
        return
    for entry in entries:
        if entry.name.startswith(LEFTOVERS):
            _remove(entry)


def _move(src: Path, dst: Path, moves: list[tuple[Path, Path]]) -> None:
    """Rename src to dst and note it, so it can be undone. Never lands on top of something already there."""
    if dst.exists() or dst.is_symlink():
        raise OSError(f"{dst.name} is in the way")
    os.replace(src, dst)
    moves.append((src, dst))


def apply_staged(root: Path, current: str = __version__) -> bool:
    """Put a staged update in place of the running copy's files. True means restart to use it.

    Only renames, inside one folder, so nothing is rewritten in place. If any of them fails, every
    rename done so far is undone in reverse order and the old version starts as before.
    """
    work = root / ".update"
    if not work.is_dir():
        return False
    staged = _staged_folder(work, current)
    if staged is None:
        _clear_leftovers(work)
        return False
    version, staging = staged
    previous = work / f"previous-{current}"
    moves: list[tuple[Path, Path]] = []
    try:
        _remove(previous)  # from an earlier swap whose clean-up didn't get to run
        previous.mkdir()
        for entry in sorted(root.iterdir()):
            if entry.name not in KEEP:
                _move(entry, previous / entry.name, moves)
        for entry in sorted(staging.iterdir()):
            # The person's settings and our own folders are never replaced by whatever the release holds.
            if entry.name not in KEEP:
                _move(entry, root / entry.name, moves)
    except OSError as e:
        undone = True
        for src, dst in reversed(moves):
            try:
                os.replace(dst, src)
            except OSError:
                undone = False
        _clear_leftovers(work)
        if undone:
            try:
                previous.rmdir()
            except OSError:
                pass
            print(f"Couldn't switch to TheCollector {version}, so the current version is starting instead. "
                  f"The update will be offered again. ({e.strerror or e})", flush=True)
        else:
            # Out of cleanup_previous's reach, since these may be the only copy of the old files.
            kept = work / f"kept-{current}"
            try:
                os.replace(previous, kept)
            except OSError:
                kept = previous
            print(f"Couldn't switch to TheCollector {version}, and couldn't put every file back. "
                  f"The old files are in {kept}. ({e.strerror or e})", flush=True)
        return False
    _remove(work / "ready.json")
    _remove(staging)  # only anything left behind on purpose is still in it
    return True


def cleanup_previous(root: Path) -> None:
    """Delete the old version's files, set aside by the last swap. Called once the new version is up."""
    try:
        entries = list((root / ".update").iterdir())
    except OSError:
        return
    for entry in entries:
        if entry.name.startswith("previous-"):
            shutil.rmtree(entry, ignore_errors=True)


def restart(argv: list[str]) -> NoReturn:
    """Replace this process with a fresh copy of the app, without opening another browser tab.

    The launcher's working folder and PYTHONPATH carry over, so "-m collector" finds the new code.
    """
    args = argv if "--no-browser" in argv else [*argv, "--no-browser"]
    sys.stdout.flush()
    sys.stderr.flush()
    os.execv(sys.executable, [sys.executable, "-m", "collector", *args])
