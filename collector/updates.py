"""Checking for a newer TheCollector release, and the update state the app shows."""
import json
import re
import threading
import time
from collections.abc import Callable
from pathlib import Path

from . import __version__, config, http
from .files import atomic_write

REPO = "rgaspary/TheCollector"
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
TARBALL_URL = "https://api.github.com/repos/" + REPO + "/tarball/v{version}"
CHECK_EVERY = 24 * 3600
# Never moved out of the way when a new version is put in place: the person's own data and our workspace.
KEEP = frozenset({"config.toml", "collector.log", ".update", ".git", ".venv"})
GITHUB_HOSTS = ("api.github.com", "github.com", "codeload.github.com")

_TAG = re.compile(r"v(\d+)\.(\d+)\.(\d+)")


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
            ready = self.ready_version() is not None
            newer = (isinstance(latest, str) and parse_tag("v" + latest) is not None
                     and parse_tag("v" + latest) > parse_version(self.current))
            return {
                "current": self.current,
                "latest": latest if isinstance(latest, str) else None,
                "url": url if isinstance(url, str) else None,
                "skipped": skipped if isinstance(skipped, str) else None,
                "state": "ready" if ready else self.state,
                "error": self.error,
                "git": (self.root / ".git").exists(),
                "show": bool(newer and latest != skipped and not ready),
            }

    def skip(self, version: str) -> None:
        """Stop offering this version. An empty string clears the skip."""
        with self.lock:
            data = self._load()
            data["skipped"] = version
            self._save(data)
