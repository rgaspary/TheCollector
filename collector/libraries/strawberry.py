"""Read the Strawberry music library."""
import shutil
import sqlite3
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlparse

from .. import platform_paths
from ..tracks import LocalTrack
from .base import Library, LibraryError, require_file

NANOSEC_PER_SEC = 1_000_000_000


def url_to_path(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "file":
        return ""
    return unquote(parsed.path)


def copy_sqlite(db_path: Path, tmp: str) -> Path:
    """Copy a database with its -wal/-shm files, since the music app may hold it open."""
    copy = Path(tmp) / db_path.name
    shutil.copy2(db_path, copy)
    for suffix in ("-wal", "-shm"):
        side = db_path.with_name(db_path.name + suffix)
        if side.exists():
            shutil.copy2(side, copy.with_name(copy.name + suffix))
    return copy


class StrawberryLibrary(Library):
    id = "strawberry"
    name = "Strawberry"
    icon = "strawberry.svg"
    help_text = "TheCollector reads Strawberry's library file directly. Strawberry can stay open."
    recommended_player = "strawberry"

    def detect(self) -> Path | None:
        path = platform_paths.default_library_path("strawberry")
        return path if path and path.is_file() else None

    def load(self, path: Path | None, folders: list[Path]) -> list[LocalTrack]:
        db_path = require_file(path or self.detect(), "Strawberry's library file",
                               fix="Open Strawberry once so it creates its library, or pick the file yourself.")
        try:
            with tempfile.TemporaryDirectory() as tmp:
                con = sqlite3.connect(copy_sqlite(db_path, tmp))
                try:
                    rows = con.execute(
                        """SELECT rowid, title, artist, albumartist, album, length, url FROM songs
                           WHERE unavailable = 0 AND title IS NOT NULL AND title != ''"""
                    ).fetchall()
                finally:
                    con.close()
        except sqlite3.DatabaseError as e:
            raise LibraryError(f"Couldn't read Strawberry's library ({e}).",
                               fix="Check that the file is Strawberry's strawberry.db.") from e

        tracks = []
        for rowid, title, artist, albumartist, album, length, url in rows:
            path_str = url_to_path(url or "")
            if not path_str:
                continue
            tracks.append(LocalTrack(
                id=rowid,
                title=title,
                artist=artist or albumartist or "Unknown Artist",
                album=album or "",
                duration=round(length / NANOSEC_PER_SEC) if isinstance(length, (int, float)) else 0,
                path=path_str,
            ))
        return tracks
