"""Helpers for the XML files iTunes and the Music app write (library and playlist exports)."""
import plistlib
import re
from urllib.parse import unquote, urlparse

from .sources.base import SourceError

NOT_ITUNES = "This doesn't look like a playlist exported from Apple Music or iTunes."


def location_to_path(url: str) -> str:
    """A `Location` file URL as a plain path, the same on any OS.

    file:///Users/a/x%20y.m4a           → /Users/a/x y.m4a
    file://localhost/C:/Users/a/x.m4a   → C:/Users/a/x.m4a
    file://nas/music/a.flac             → //nas/music/a.flac
    """
    parsed = urlparse(url or "")
    if parsed.scheme != "file":
        return ""
    path = unquote(parsed.path)
    if re.match(r"^/[A-Za-z]:", path):
        return path[1:]
    if parsed.netloc and parsed.netloc.lower() != "localhost":
        return f"//{parsed.netloc}{path}"
    return path


def read_plist(data: bytes) -> dict:
    try:
        plist = plistlib.loads(data)
    except Exception as e:  # plistlib raises several kinds of errors for bad input
        raise SourceError(NOT_ITUNES) from e
    if not isinstance(plist, dict):
        raise SourceError(NOT_ITUNES)
    return plist
