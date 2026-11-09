"""Which playlist format each music app imports best, and how to import it.

Matches the spec's "Which format for which app" table. Rows are checked by hand before release (plan Task 23).
"""
from dataclasses import dataclass, field

ALL = {"linux", "win32", "darwin"}


@dataclass
class Player:
    key: str
    name: str
    icon: str                    # file in static/icons/apps/
    platforms: set[str]
    recommended: str             # key in PLAYLIST_FORMATS
    also: list[str] = field(default_factory=list)
    steps: str = ""


PLAYERS: dict[str, Player] = {p.key: p for p in (
    Player("itunes", "iTunes", "itunes.svg", {"win32"}, "itunes_xml", ["m3u"],
           "In iTunes, choose File → Library → Import Playlist, then pick the file."),
    Player("apple_music", "Apple Music", "apple-music.svg", {"darwin"}, "itunes_xml", ["m3u8", "m3u"],
           "In Music, choose File → Library → Import Playlist, then pick the file."),
    Player("strawberry", "Strawberry", "strawberry.svg", ALL, "m3u8", ["xspf", "pls"],
           "In Strawberry, choose Playlist → Load playlist, or drag the file into the playlist area."),
    Player("vlc", "VLC", "vlc.svg", ALL, "xspf", ["m3u8", "pls"],
           "In VLC, choose Media → Open File, or drag the file onto VLC."),
    Player("mediamonkey", "MediaMonkey", "mediamonkey.svg", {"win32"}, "m3u8", ["m3u", "pls"],
           "In MediaMonkey, choose File → Import → Playlists, or drag the file onto Playlists."),
    Player("winamp", "Winamp", "winamp.svg", {"win32"}, "m3u8", ["pls", "m3u"],
           "Drag the file into Winamp's playlist editor, or use Library → Playlists → Import."),
    Player("wmp", "Windows Media Player (Legacy)", "wmp.svg", {"win32"}, "wpl", ["m3u"],
           "Drag the file into the Library, or double-click it to open it in Windows Media Player."),
    Player("media_player", "Media Player (Windows 11)", "media-player.svg", {"win32"}, "m3u", ["wpl"],
           "Right-click the file, choose Open with → Media Player."),
    Player("other", "Other / not sure", "folder.svg", ALL, "m3u8",
           ["m3u", "pls", "xspf", "itunes_xml", "wpl", "csv", "json"],
           "Most music players open M3U8 files. Look for Open, Import or Load playlist, or drag the file in."),
)}

_BY_LIBRARY = {"strawberry": "strawberry", "mediamonkey": "mediamonkey", "folder": "other"}


def default_player(library_id: str, platform: str) -> str:
    """The app the Export screen pre-selects for this library."""
    if library_id == "itunes":
        return "apple_music" if platform == "darwin" else "itunes"
    return _BY_LIBRARY.get(library_id, "other")
