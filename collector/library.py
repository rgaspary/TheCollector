"""Read the Strawberry music library."""
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

NANOSEC_PER_SEC = 1_000_000_000


@dataclass
class LocalTrack:
    id: int
    title: str
    artist: str
    album: str
    duration: int  # seconds
    path: str


def url_to_path(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "file":
        return ""
    return unquote(parsed.path)


def load_library(db_path: Path) -> list[LocalTrack]:
    """Load playable tracks. Works on a copy, since Strawberry may hold the database open."""
    if not db_path.exists():
        raise FileNotFoundError(f"Strawberry database not found: {db_path}")
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "strawberry.db"
        shutil.copy2(db_path, copy)
        for suffix in ("-wal", "-shm"):
            side = db_path.with_name(db_path.name + suffix)
            if side.exists():
                shutil.copy2(side, copy.with_name(copy.name + suffix))
        con = sqlite3.connect(copy)
        try:
            rows = con.execute(
                """SELECT rowid, title, artist, albumartist, album, length, url FROM songs
                   WHERE unavailable = 0 AND title IS NOT NULL AND title != ''"""
            ).fetchall()
        finally:
            con.close()

    tracks = []
    for rowid, title, artist, albumartist, album, length, url in rows:
        path = url_to_path(url or "")
        if not path:
            continue
        tracks.append(LocalTrack(
            id=rowid,
            title=title,
            artist=artist or albumartist or "Unknown Artist",
            album=album or "",
            duration=round(length / NANOSEC_PER_SEC) if isinstance(length, (int, float)) else 0,
            path=path,
        ))
    return tracks
