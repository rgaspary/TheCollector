"""Read the library XML that iTunes (Windows, older macOS) and the Music app (macOS) can share."""
from pathlib import Path

from .. import platform_paths
from ..itunes_xml import location_to_path, read_plist
from ..sources.base import SourceError
from ..tracks import LocalTrack
from .base import Library, LibraryError, require_file

FIX = ("On a Mac, turn on Music → Settings → Advanced → \"Share Library XML with other applications\". "
       "On Windows, turn on iTunes → Edit → Preferences → Advanced → \"Share iTunes Library XML with other "
       "applications\". Then pick the file.")
SKIP_FLAGS = ("Podcast", "Movie", "TV Show", "Music Video", "Audiobook")


class ItunesLibrary(Library):
    id = "itunes"
    name = "iTunes / Apple Music"
    icon = "itunes.svg"
    help_text = (
        "TheCollector reads the library XML file. "
        "Mac (Music app): open Music → Settings → Advanced, turn on \"Share Library XML with other "
        "applications\", and the file appears as Music/Music/Library.xml in your home folder. "
        "Or use File → Library → Export Library and pick the saved file. "
        "Windows (iTunes): open Edit → Preferences → Advanced, turn on \"Share iTunes Library XML with other "
        "applications\", and use Music\\iTunes\\iTunes Library.xml. "
        "Songs that are only streamed from Apple Music aren't on your computer, so they're left out.")
    recommended_player = "itunes"

    def detect(self) -> Path | None:
        candidates = [platform_paths.default_library_path("itunes"),
                      Path.home() / "Music/iTunes/iTunes Music Library.xml",
                      Path.home() / "Music/iTunes/iTunes Library.xml"]
        return next((p for p in candidates if p and p.is_file()), None)

    def load(self, path: Path | None, folders: list[Path]) -> list[LocalTrack]:
        xml = require_file(path or self.detect(), "iTunes / Apple Music library XML", fix=FIX)
        try:
            plist = read_plist(xml.read_bytes())
        except (SourceError, OSError) as e:
            raise LibraryError("That file isn't an iTunes or Music library XML.", fix=FIX) from e
        entries = plist.get("Tracks")
        if not isinstance(entries, dict):
            raise LibraryError("That XML has no songs in it. It may be a single playlist, not the library.",
                               fix=FIX)

        tracks = []
        for n, (key, t) in enumerate(entries.items()):
            if not isinstance(t, dict) or any(t.get(flag) for flag in SKIP_FLAGS):
                continue
            if t.get("Track Type") in ("URL", "Remote"):
                continue
            path_str = location_to_path(t.get("Location", ""))
            title = t.get("Name") or ""
            if not path_str or not title:
                continue
            total = t.get("Total Time")
            tracks.append(LocalTrack(
                id=t["Track ID"] if isinstance(t.get("Track ID"), int) else -(n + 1),
                title=title,
                artist=t.get("Artist") or t.get("Album Artist") or "Unknown Artist",
                album=t.get("Album") or "",
                duration=round(total / 1000) if isinstance(total, (int, float)) else 0,
                path=path_str,
            ))
        return tracks
