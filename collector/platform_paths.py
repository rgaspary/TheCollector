"""Where TheCollector keeps its data, and where music apps keep their libraries, per OS.

This is the only module that branches on sys.platform for paths.
"""
import os
import re
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


def _xdg_user_dir(key: str, fallback: Path) -> Path:
    """A folder from ~/.config/user-dirs.dirs (it follows the system language), or the fallback."""
    home = Path.home()
    conf = _env_path("XDG_CONFIG_HOME", home / ".config") / "user-dirs.dirs"
    try:
        text = conf.read_text(encoding="utf-8")
    except OSError:
        return fallback
    match = re.search(rf'^{key}="([^"]*)"', text, re.M)
    if not match:
        return fallback
    path = Path(match.group(1).replace("$HOME", str(home)))
    return path if path.is_absolute() and path != home else fallback  # $HOME itself means "not used"


def _windows_folder(name: str, fallback: Path) -> Path:
    """A folder from the registry, which knows when Documents or Music moved (OneDrive, another drive)."""
    try:
        import winreg
        key = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
            value, _ = winreg.QueryValueEx(k, name)
        return Path(os.path.expandvars(value))
    except (ImportError, OSError):
        return fallback


def music_dir(platform: str = sys.platform) -> Path:
    if platform == "win32":
        return _windows_folder("My Music", _env_path("USERPROFILE", Path.home()) / "Music")
    if platform == "darwin":
        return Path.home() / "Music"
    return _xdg_user_dir("XDG_MUSIC_DIR", Path.home() / "Music")


def documents_dir(platform: str = sys.platform) -> Path:
    if platform == "win32":
        return _windows_folder("Personal", _env_path("USERPROFILE", Path.home()) / "Documents")
    if platform == "darwin":
        return Path.home() / "Documents"
    return _xdg_user_dir("XDG_DOCUMENTS_DIR", Path.home() / "Documents")


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
        return music_dir(platform)
    return None


def open_folder_command(folder: Path, platform: str = sys.platform) -> list[str]:
    """The command that shows a folder in the system's file manager."""
    if platform == "win32":
        return ["explorer", str(folder)]
    if platform == "darwin":
        return ["open", str(folder)]
    return ["xdg-open", str(folder)]
