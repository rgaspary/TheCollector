"""Read the Strawberry music library."""
import os
import shutil
import sqlite3
import tempfile
import unicodedata
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .. import platform_paths
from ..itunes_xml import location_to_path
from ..tracks import LocalTrack
from .base import Library, LibraryError, require_file
from .folder import audio_files

NANOSEC_PER_SEC = 1_000_000_000


def url_to_path(url: str) -> str:
    """A song's file:// URL as a path ("" for streams). file:///C:/a.mp3 becomes C:/a.mp3 on Windows."""
    return location_to_path(url)


def _same_path(path: str) -> str:
    """A path in one spelling, so a path from a file:// URL matches the same file found on disk."""
    return unicodedata.normalize("NFC", os.path.normcase(os.path.normpath(path)))


def copy_sqlite(db_path: Path, tmp: str) -> Path:
    """Copy a database with its -wal/-shm files, since the music app may hold it open."""
    copy = Path(tmp) / db_path.name
    shutil.copy2(db_path, copy)
    for suffix in ("-wal", "-shm"):
        side = db_path.with_name(db_path.name + suffix)
        if side.exists():
            shutil.copy2(side, copy.with_name(copy.name + suffix))
    return copy


@contextmanager
def open_copy(db_path: Path) -> Iterator[sqlite3.Connection]:
    """A connection to a temporary copy of the database, removed again afterwards."""
    with tempfile.TemporaryDirectory() as tmp:
        con = sqlite3.connect(copy_sqlite(db_path, tmp))
        try:
            yield con
        finally:
            con.close()


class StrawberryLibrary(Library):
    id = "strawberry"
    name = "Strawberry"
    icon = "strawberry.png"
    help_text = "TheCollector reads Strawberry's library file directly. Strawberry can stay open."
    recommended_player = "strawberry"

    def detect(self) -> Path | None:
        path = platform_paths.default_library_path("strawberry")
        return path if path and path.is_file() else None

    def load(self, path: Path | None, folders: list[Path]) -> list[LocalTrack]:
        db_path = require_file(path or self.detect(), "Strawberry's library file",
                               fix="Open Strawberry once so it creates its library, or pick the file yourself.")
        try:
            with open_copy(db_path) as con:
                rows = con.execute(
                    """SELECT rowid, title, artist, albumartist, album, length, url FROM songs
                       WHERE unavailable = 0 AND title IS NOT NULL AND title != ''"""
                ).fetchall()
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

    def files_not_in_library(self, db_path: Path) -> int:
        """How many music files in Strawberry's folders its library doesn't list (it hasn't rescanned)."""
        try:
            with open_copy(db_path) as con:
                folders = [Path(row[0]) for row in con.execute("SELECT path FROM directories") if row[0]]
                known = {_same_path(url_to_path(row[0] or ""))
                         for row in con.execute("SELECT url FROM songs WHERE unavailable = 0")}
        except (sqlite3.Error, OSError):
            return 0  # an older or unusual library file: nothing to compare against
        on_disk = {_same_path(str(f)) for folder in folders if folder.is_dir() for f in audio_files(folder)}
        return len(on_disk - known)

    def warning(self, path: Path | None, folders: list[Path]) -> str:
        db_path = path or self.detect()
        if not db_path or not db_path.is_file():
            return ""
        count = self.files_not_in_library(db_path)
        if not count:
            return ""
        files = f"{count:,} music file" + ("" if count == 1 else "s")
        return (f"Strawberry hasn't added {files} from its music folders yet, so TheCollector can't see "
                f"{'it' if count == 1 else 'them'}. Open Strawberry and choose Tools → Update collection, "
                f"or pick Music folder as your library instead.")
