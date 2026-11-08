"""Tracks and playlists as read from a streaming service."""
from dataclasses import dataclass, field


@dataclass
class SourceTrack:
    id: str
    title: str
    artists: list[str]
    album: str
    duration: int  # seconds
    url: str
    isrc: str = ""

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
