"""Tracks and playlists from a streaming service, and tracks from the local library."""
import re
from dataclasses import dataclass, field

# Every character str.splitlines() treats as a line break.
_BREAKS = re.compile(r"[ \t]*[\n\r\v\f\x1c\x1d\x1e\x85  ]+[ \t]*")


def one_line(text: str) -> str:
    """The text with line breaks turned into spaces. Names are written into line-based files
    (playlists, the NextUp note), where a line break would start a new entry or task."""
    return _BREAKS.sub(" ", text).strip() if _BREAKS.search(text) else text


@dataclass
class SourceTrack:
    id: str
    title: str
    artists: list[str]
    album: str
    duration: int  # seconds
    url: str
    isrc: str = ""

    def __post_init__(self):
        self.title, self.album = one_line(self.title), one_line(self.album)
        self.artists = [one_line(a) for a in self.artists]

    @property
    def artist(self) -> str:
        return ", ".join(self.artists)


@dataclass
class Playlist:
    source: str
    id: str
    name: str
    url: str
    tracks: list[SourceTrack] = field(default_factory=list)

    def __post_init__(self):
        self.name = one_line(self.name)


@dataclass
class LocalTrack:
    """A playable file in the user's own music library."""
    id: int
    title: str
    artist: str
    album: str
    duration: int  # seconds
    path: str

    def __post_init__(self):
        self.title, self.artist, self.album = one_line(self.title), one_line(self.artist), one_line(self.album)
