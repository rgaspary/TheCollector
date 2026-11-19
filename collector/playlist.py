"""File names and track paths for exported playlists."""
import os
import re
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Literal
from urllib.parse import quote

PathStyle = Literal["absolute", "relative", "name"]

_WINDOWS = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\)")


def safe_filename(name: str) -> str:
    name = re.sub(r'[/\\:*?"<>|\x00-\x1f]', "", name).strip(" .")
    return name or "Playlist"


def _pure(path: str) -> PurePosixPath | PureWindowsPath:
    """The path as written, Windows or POSIX, whatever OS this runs on."""
    return PureWindowsPath(path) if _WINDOWS.match(path) else PurePosixPath(path)


def format_path(track_path: str, export_dir: Path, style: PathStyle) -> str:
    """The track's path as a playlist should list it.

    absolute: unchanged (works on this computer).
    relative: from the export folder, with forward slashes (works when music and playlist move together).
    name:     the file name only.
    """
    if style == "name":
        return _pure(track_path).name
    if style == "relative":
        try:
            return os.path.relpath(track_path, export_dir).replace("\\", "/")
        except ValueError:  # another drive on Windows: no relative path exists
            return track_path
    return track_path


def path_to_uri(path: str) -> str:
    """A file:// URI for an absolute path (Windows or POSIX form), or a percent-encoded relative path."""
    pure = _pure(path)
    if pure.is_absolute():
        return pure.as_uri()
    return quote(path.replace("\\", "/"), safe="/")
