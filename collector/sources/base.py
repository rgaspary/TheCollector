"""What every streaming source looks like to the rest of the app."""
import re
from dataclasses import dataclass
from typing import ClassVar, Literal

from ..tracks import Playlist


@dataclass
class Field:
    """One value the user enters to set a source up."""
    key: str
    label: str
    secret: bool = False
    help: str = ""
    placeholder: str = ""
    multiline: bool = False
    required: bool = True


class SourceError(Exception):
    """A problem to show the user as-is."""


class CredentialError(SourceError):
    """The saved credentials were refused. `fix` says what to do about it."""

    def __init__(self, message: str, fix: str = ""):
        super().__init__(message)
        self.fix = fix


class Source:
    """A streaming service. One instance per service lives in sources.REGISTRY.

    Methods get the saved credentials as a dict and may change it in place (for example a
    refreshed token); the caller saves it afterwards.
    """
    id: ClassVar[str] = ""
    name: ClassVar[str] = ""
    icon: ClassVar[str] = ""  # file name in static/icons/services/
    fields: ClassVar[list[Field]] = []
    help_url: ClassVar[str] = ""
    help_text: ClassVar[str] = ""
    link_example: ClassVar[str] = ""
    # For the Help screen: numbered set-up steps, then notes. "{redirect_uri}" becomes the real one.
    setup_steps: ClassVar[list[str]] = []
    setup_notes: ClassVar[list[str]] = []
    limits: ClassVar[str] = ""
    uses_oauth: ClassVar[bool] = False
    token_keys: ClassVar[tuple[str, ...]] = ("access_token", "refresh_token", "expires_at")
    link_patterns: ClassVar[tuple[str, ...]] = ()  # regexes that recognise this service's links
    # File-import sources
    input: ClassVar[Literal["link", "file"]] = "link"
    file_types: ClassVar[list[str]] = []
    intro: ClassVar[str] = ""
    export_steps: ClassVar[dict[str, list[str]]] = {}

    def matches_link(self, text: str) -> bool:
        return any(re.search(p, text, re.IGNORECASE) for p in self.link_patterns)

    def has_token(self, creds: dict) -> bool:
        return bool(creds.get("access_token") or creds.get("refresh_token"))

    def parse_link(self, text: str) -> str:
        raise SourceError(f"{self.name} playlists are imported from a file.")

    def test(self, creds: dict) -> str:
        """Check the credentials. Returns an OK message or raises CredentialError."""
        raise NotImplementedError

    def get_playlist(self, link: str, creds: dict) -> Playlist:
        raise NotImplementedError

    def parse_file(self, filename: str, data: bytes) -> list[Playlist]:
        raise SourceError(f"{self.name} playlists are opened from a link, not a file.")

    # OAuth sources only
    def login_url(self, creds: dict, redirect_uri: str) -> str:
        raise NotImplementedError

    def finish_login(self, creds: dict, code: str, state: str, redirect_uri: str) -> dict:
        """Returns the values to save (tokens)."""
        raise NotImplementedError


_ISO_DURATION = re.compile(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?)?")


def parse_iso_duration(value: str) -> int:
    """ISO 8601 duration like "PT3M59S" to whole seconds. 0 if it can't be read."""
    m = _ISO_DURATION.fullmatch(value or "")
    if not m or not any(m.groups()):
        return 0
    days, hours, minutes, seconds = (float(g) if g else 0 for g in m.groups())
    return round(days * 86400 + hours * 3600 + minutes * 60 + seconds)
