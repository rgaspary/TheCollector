"""Where TheCollector keeps its data, and where music apps keep their libraries, per OS.

This is the only module that branches on sys.platform for paths.
"""
import os
import sys
from pathlib import Path


def _env_path(name: str, fallback: Path) -> Path:
    value = os.environ.get(name)
    return Path(value) if value else fallback


def data_dir(platform: str = sys.platform) -> Path:
    home = Path.home()
    if platform == "win32":
        return _env_path("APPDATA", home / "AppData/Roaming") / "TheCollector"
    if platform == "darwin":
        return home / "Library/Application Support/TheCollector"
    return _env_path("XDG_DATA_HOME", home / ".local/share") / "thecollector"


def default_library_path(kind: str, platform: str = sys.platform) -> Path | None:
    """The usual location of a library of this kind, or None if it doesn't exist on this OS."""
    home = Path.home()
    if kind == "strawberry":
        if platform == "win32":
            return _env_path("LOCALAPPDATA", home / "AppData/Local") / "strawberry/strawberry/strawberry.db"
        if platform == "darwin":
            return home / "Library/Application Support/Strawberry/Strawberry/strawberry.db"
        return _env_path("XDG_DATA_HOME", home / ".local/share") / "strawberry/strawberry/strawberry.db"
    if kind == "itunes":
        if platform == "win32":
            return _env_path("USERPROFILE", home) / "Music/iTunes/iTunes Library.xml"
        if platform == "darwin":
            return home / "Music/Music/Library.xml"
        return None
    if kind == "mediamonkey":
        if platform == "win32":
            return _env_path("APPDATA", home / "AppData/Roaming") / "MediaMonkey5/MM5.DB"
        return None
    if kind == "folder":
        if platform == "win32":
            return _env_path("USERPROFILE", home) / "Music"
        return home / "Music"
    return None


def open_folder_command(folder: Path, platform: str = sys.platform) -> list[str]:
    """The command that shows a folder in the system's file manager."""
    if platform == "win32":
        return ["explorer", str(folder)]
    if platform == "darwin":
        return ["open", str(folder)]
    return ["xdg-open", str(folder)]
