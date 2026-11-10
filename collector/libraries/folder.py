"""Scan music folders and read each file's tags. Covers Winamp, VLC, Windows Media Player and any other
player, since they all play files from folders.

Tags are cached in DATA_DIR/folder-index.json by path, size and modification time, so a second scan
only reads files that changed.
"""
import json
import os
import re
import tempfile
from dataclasses import asdict
from pathlib import Path

from .. import platform_paths
from ..tracks import LocalTrack
from .base import Library, LibraryError
from .tags import Tags, read_tags

AUDIO_EXTENSIONS = {".mp3", ".m4a", ".m4b", ".aac", ".alac", ".flac", ".ogg", ".oga", ".opus", ".wma",
                    ".wav", ".aif", ".aiff"}
CACHE_VERSION = 1
_TRACK_NUMBER = re.compile(r"^(?:\d{1,3}\s*[-.]\s*|\d{2,3}\s+)(?=\S)")
FIX = "Add the folder your music is in. You can add more than one."


def from_path(rel: Path, tags: Tags) -> Tags:
    """Fill gaps in the tags from the file's place in the folder tree: Artist/Album/NN - Title.ext,
    or Artist - Title.ext."""
    name = _TRACK_NUMBER.sub("", rel.stem).strip() or rel.stem
    folders = rel.parts[:-1]
    folder_artist, folder_album = (folders[-2], folders[-1]) if len(folders) >= 2 else ("", "")
    file_artist = ""
    if " - " in name:
        left, right = (part.strip() for part in name.split(" - ", 1))
        if left and right and (not folder_artist or left.casefold() == folder_artist.casefold()):
            file_artist, name = left, right
    return Tags(
        title=tags.title or name,
        artist=tags.artist or tags.album_artist or file_artist or folder_artist,
        album=tags.album or folder_album,
        album_artist=tags.album_artist,
        duration=tags.duration,
    )


class FolderLibrary(Library):
    id = "folder"
    name = "Music folder"
    subtitle = "Winamp, VLC, Windows Media Player, others"
    icon = "folder.svg"
    needs = "folders"
    help_text = ("TheCollector reads the song details saved in your music files. Add the folders your music "
                 "is in. The first scan of a big collection can take a minute; later scans only read new or "
                 "changed files.")
    recommended_player = "other"

    def __init__(self, cache_path: Path | None = None):
        self._cache_path = cache_path

    @property
    def cache_path(self) -> Path:
        if self._cache_path is None:
            from ..config import DATA_DIR
            self._cache_path = DATA_DIR / "folder-index.json"
        return self._cache_path

    def detect(self) -> Path | None:
        path = platform_paths.default_library_path("folder")
        return path if path and path.is_dir() else None

    def load(self, path: Path | None, folders: list[Path]) -> list[LocalTrack]:
        roots = list(folders) or ([path] if path else []) or [p for p in (self.detect(),) if p]
        if not roots:
            raise LibraryError("Add a music folder first.", fix=FIX)
        existing = [r for r in roots if r.is_dir()]
        if not existing:
            names = ", ".join(str(r) for r in roots)
            raise LibraryError(f"The music folder wasn't found: {names}.", fix=FIX)

        cache = self._read_cache()
        fresh: dict[str, list] = {}
        found: list[tuple[str, Tags]] = []
        for root in existing:
            for file in audio_files(root):
                key = str(file)
                if key in fresh:
                    continue  # the same file reached through two folders
                try:
                    st = file.stat()
                except OSError:
                    continue
                hit = cache.get(key)
                if hit and hit[0] == st.st_size and hit[1] == st.st_mtime_ns:
                    tags = Tags(**hit[2])
                else:
                    tags = from_path(file.relative_to(root), read_tags(file))
                fresh[key] = [st.st_size, st.st_mtime_ns, asdict(tags)]
                found.append((key, tags))
        if fresh != cache:
            self._write_cache(fresh)

        found.sort(key=lambda item: item[0])
        return [LocalTrack(id=i, title=t.title, artist=t.artist or "Unknown Artist", album=t.album,
                           duration=t.duration, path=key)
                for i, (key, t) in enumerate(found, start=1)]

    def _read_cache(self) -> dict[str, list]:
        try:
            data = json.loads(self.cache_path.read_text(encoding="utf-8"))
            if data.get("version") == CACHE_VERSION and isinstance(data.get("files"), dict):
                return data["files"]
        except (OSError, ValueError, AttributeError):
            pass
        return {}

    def _write_cache(self, files: dict[str, list]) -> None:
        path = self.cache_path
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".folder-index-", suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"version": CACHE_VERSION, "files": files}, f, ensure_ascii=False)
            os.replace(tmp, path)
        except OSError:
            pass  # no cache just means a slower next scan


def audio_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root, onerror=lambda e: None):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for name in sorted(filenames):
            if not name.startswith(".") and os.path.splitext(name)[1].lower() in AUDIO_EXTENSIONS:
                yield Path(dirpath) / name
