"""Read the MediaMonkey library database (MM5.DB for MediaMonkey 5, MM.DB for MediaMonkey 4).

MediaMonkey declares text columns with its own IUNICODE collation, which sqlite3 doesn't know.
Registering a case-insensitive stand-in lets the queries run.

Column names and the drive-letter rule come from MediaMonkey's documented schema. They haven't been
checked against a real MM5.DB yet (plan Task 1, step 4b).
"""
import re
import sqlite3
import tempfile
from pathlib import Path

from .. import platform_paths
from ..tracks import LocalTrack
from .base import Library, LibraryError, require_file
from .strawberry import copy_sqlite

FIX = "Pick MediaMonkey's library file: MM5.DB (MediaMonkey 5) or MM.DB (MediaMonkey 4) in its AppData folder."


def casefold_compare(a: str, b: str) -> int:
    a, b = (a or "").casefold(), (b or "").casefold()
    return (a > b) - (a < b)


def _drive(letter_number) -> str:
    return chr(ord("A") + letter_number) if isinstance(letter_number, int) and 0 <= letter_number < 26 else ""


def full_path(song_path: str, drive_number) -> str:
    """Songs on fixed drives are stored as ':\\Music\\a.mp3'; the letter comes from Medias.DriveLetter."""
    if song_path.startswith(":\\") or song_path.startswith(":/"):
        letter = _drive(drive_number)
        return f"{letter}{song_path}" if letter else ""
    if re.match(r"^[A-Za-z]:[\\/]", song_path) or song_path.startswith(("\\\\", "/")):
        return song_path
    return ""  # web streams and other non-file entries


class MediaMonkeyLibrary(Library):
    id = "mediamonkey"
    name = "MediaMonkey"
    icon = "mediamonkey.svg"
    help_text = ("TheCollector reads MediaMonkey's library file directly. MediaMonkey can stay open. "
                 "It's MM5.DB in %APPDATA%\\MediaMonkey5 (MediaMonkey 5) or MM.DB in %APPDATA%\\MediaMonkey "
                 "(MediaMonkey 4).")
    recommended_player = "mediamonkey"

    def detect(self) -> Path | None:
        mm5 = platform_paths.default_library_path("mediamonkey")
        if not mm5:
            return None
        return next((p for p in (mm5, mm5.parent.parent / "MediaMonkey/MM.DB") if p.is_file()), None)

    def load(self, path: Path | None, folders: list[Path]) -> list[LocalTrack]:
        db_path = require_file(path or self.detect(), "MediaMonkey library file", fix=FIX)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                con = sqlite3.connect(copy_sqlite(db_path, tmp))
                try:
                    con.create_collation("IUNICODE", casefold_compare)
                    tables = {r[0].lower() for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                    if "songs" not in tables:
                        raise LibraryError("That file isn't a MediaMonkey library.", fix=FIX)
                    columns = {r[1].lower() for r in con.execute("PRAGMA table_info(Songs)")}
                    album_artist = "s.AlbumArtist" if "albumartist" in columns else "''"
                    join = ("LEFT JOIN Medias m ON m.IDMedia = s.IDMedia" if "medias" in tables else "")
                    drive = "m.DriveLetter" if join else "NULL"
                    rows = con.execute(
                        f"""SELECT s.ID, s.SongTitle, s.Artist, {album_artist}, s.Album, s.SongLength,
                                   s.SongPath, {drive}
                            FROM Songs s {join}"""
                    ).fetchall()
                finally:
                    con.close()
        except sqlite3.DatabaseError as e:
            raise LibraryError(f"Couldn't read the MediaMonkey library ({e}).", fix=FIX) from e

        tracks = []
        for song_id, title, artist, album_artist, album, length, song_path, drive_number in rows:
            path_str = full_path(song_path or "", drive_number)
            if not path_str or not title:
                continue
            artist = (artist or album_artist or "Unknown Artist").replace("; ", ", ")
            tracks.append(LocalTrack(
                id=song_id,
                title=title,
                artist=artist,
                album=album or "",
                duration=round(length / 1000) if isinstance(length, (int, float)) else 0,
                path=path_str,
            ))
        return tracks
