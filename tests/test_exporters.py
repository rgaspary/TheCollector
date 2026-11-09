import csv
import io
import json
import plistlib
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from collector.exporters import PLAYLIST_FORMATS, ExportItem, export_playlist
from collector.exporters.players import PLAYERS, default_player
from collector.playlist import format_path, path_to_uri, safe_filename
from collector.tracks import LocalTrack, Playlist, SourceTrack

XSPF = "{http://xspf.org/ns/0/}"


def item(i: int, title: str, artist: str, album: str, duration: int, path: str, isrc: str = "") -> ExportItem:
    return ExportItem(
        LocalTrack(i, title, artist, album, duration, path),
        SourceTrack(f"s{i}", title, [artist], album, duration, f"https://open.spotify.com/track/s{i}", isrc),
    )


PLAYLIST = Playlist("spotify", "pl1", "Road Trip", "https://open.spotify.com/playlist/pl1")
ITEMS = [
    item(1, "Black Hole Sun", "Soundgarden", "Superunknown", 320, "/music/Soundgarden/Superunknown/Black Hole Sun.m4a",
         "USAM19400001"),
    item(2, 'Tom & "Jerry", <Live>', "Björk", "Homogenic", 0, "/music/a #1/b c.flac"),
]
EXPORT_DIR = Path("/music/Playlists")


def write(key: str, items=ITEMS, style="absolute", folder=EXPORT_DIR) -> str:
    return PLAYLIST_FORMATS[key].write(PLAYLIST, items, folder, style)


class Paths(unittest.TestCase):
    def test_format_path_styles(self):
        p = "/music/a #1/b c.flac"
        self.assertEqual(format_path(p, EXPORT_DIR, "absolute"), p)
        self.assertEqual(format_path(p, EXPORT_DIR, "relative"), "../a #1/b c.flac")
        self.assertEqual(format_path(p, EXPORT_DIR, "name"), "b c.flac")
        self.assertEqual(format_path("C:\\Music\\a b.mp3", EXPORT_DIR, "name"), "a b.mp3")

    def test_path_to_uri(self):
        self.assertEqual(path_to_uri("/music/a #1/b c.flac"), "file:///music/a%20%231/b%20c.flac")
        self.assertEqual(path_to_uri("C:\\Music\\a b.mp3"), "file:///C:/Music/a%20b.mp3")
        self.assertEqual(path_to_uri("C:/Music/a b.mp3"), "file:///C:/Music/a%20b.mp3")
        self.assertEqual(path_to_uri("../a #1/b c.flac"), "../a%20%231/b%20c.flac")

    def test_unsafe_playlist_name(self):
        self.assertEqual(safe_filename("AC/DC: Best?"), "ACDC Best")
        self.assertEqual(safe_filename("..."), "Playlist")
        self.assertEqual(safe_filename(""), "Playlist")


class Formats(unittest.TestCase):
    def test_m3u8_matches_v1_output(self):
        self.assertEqual(write("m3u8"), (
            "#EXTM3U\n#PLAYLIST:Road Trip\n"
            "#EXTINF:320,Soundgarden - Black Hole Sun\n/music/Soundgarden/Superunknown/Black Hole Sun.m4a\n"
            '#EXTINF:-1,Björk - Tom & "Jerry", <Live>\n/music/a #1/b c.flac\n'))

    def test_m3u_parses_back(self):
        lines = write("m3u").splitlines()
        self.assertEqual(lines[0], "#EXTM3U")
        self.assertEqual([l for l in lines if not l.startswith("#")], [i.local.path for i in ITEMS])

    def test_pls_parses_back(self):
        text = write("pls")
        self.assertTrue(text.startswith("[playlist]\n"))
        self.assertIn("NumberOfEntries=2\n", text)
        self.assertIn("Version=2\n", text)
        self.assertIn("File1=/music/Soundgarden/Superunknown/Black Hole Sun.m4a\n", text)
        self.assertIn('Title2=Björk - Tom & "Jerry", <Live>\n', text)
        self.assertIn("Length1=320\n", text)
        self.assertIn("Length2=-1\n", text)

    def test_xspf_parses_back(self):
        root = ET.fromstring(write("xspf").encode("utf-8"))
        self.assertEqual(root.tag, f"{XSPF}playlist")
        self.assertEqual(root.findtext(f"{XSPF}title"), "Road Trip")
        tracks = root.findall(f"{XSPF}trackList/{XSPF}track")
        self.assertEqual([t.findtext(f"{XSPF}location") for t in tracks],
                         ["file:///music/Soundgarden/Superunknown/Black%20Hole%20Sun.m4a",
                          "file:///music/a%20%231/b%20c.flac"])
        self.assertEqual(tracks[1].findtext(f"{XSPF}title"), 'Tom & "Jerry", <Live>')
        self.assertEqual(tracks[1].findtext(f"{XSPF}creator"), "Björk")
        self.assertEqual(tracks[0].findtext(f"{XSPF}duration"), "320000")
        self.assertIsNone(tracks[1].find(f"{XSPF}duration"))

    def test_itunes_xml_parses_back(self):
        plist = plistlib.loads(write("itunes_xml").encode("utf-8"))
        self.assertEqual(sorted(plist["Tracks"]), ["1", "2"])
        t2 = plist["Tracks"]["2"]
        self.assertEqual((t2["Track ID"], t2["Name"], t2["Artist"], t2["Album"]),
                         (2, 'Tom & "Jerry", <Live>', "Björk", "Homogenic"))
        self.assertEqual(t2["Location"], "file:///music/a%20%231/b%20c.flac")
        self.assertEqual(plist["Tracks"]["1"]["Total Time"], 320000)
        pl = plist["Playlists"][0]
        self.assertEqual(pl["Name"], "Road Trip")
        self.assertEqual([x["Track ID"] for x in pl["Playlist Items"]], [1, 2])

    def test_wpl_parses_back(self):
        text = write("wpl")
        self.assertTrue(text.startswith('<?wpl version="1.0"?>'))
        root = ET.fromstring(text.split("?>", 1)[1])
        self.assertEqual(root.tag, "smil")
        self.assertEqual(root.findtext("head/title"), "Road Trip")
        self.assertEqual([m.get("src") for m in root.findall("body/seq/media")], [i.local.path for i in ITEMS])

    def test_csv_parses_back(self):
        rows = list(csv.DictReader(io.StringIO(write("csv"), newline="")))
        self.assertEqual(list(rows[0]), ["Title", "Artist", "Album", "Duration", "ISRC", "Path", "Source URL"])
        self.assertEqual(rows[0]["ISRC"], "USAM19400001")
        self.assertEqual((rows[1]["Title"], rows[1]["Artist"], rows[1]["Path"]),
                         ('Tom & "Jerry", <Live>', "Björk", "/music/a #1/b c.flac"))
        self.assertEqual(rows[0]["Duration"], "5:20")
        self.assertEqual(rows[1]["Duration"], "")
        self.assertEqual(rows[1]["Source URL"], "https://open.spotify.com/track/s2")

    def test_json_parses_back(self):
        data = json.loads(write("json"))
        self.assertEqual((data["format"], data["version"], data["name"], data["source"], data["source_url"]),
                         ("thecollector-playlist", 1, "Road Trip", "spotify", "https://open.spotify.com/playlist/pl1"))
        self.assertEqual(data["tracks"][1], {
            "title": 'Tom & "Jerry", <Live>', "artist": "Björk", "album": "Homogenic", "duration": 0,
            "path": "/music/a #1/b c.flac", "isrc": "",
            "source_id": "s2", "source_url": "https://open.spotify.com/track/s2"})

    def test_special_characters(self):
        # Every format keeps the tricky title, the non-Latin artist and the path with # and spaces.
        # WPL lists only file paths, so it's checked for the path alone.
        for key in PLAYLIST_FORMATS:
            text = write(key)
            if key == "wpl":
                self.assertIn('src="/music/a #1/b c.flac"', text)
                continue
            self.assertIn("Björk", text, key)
            if key in ("xspf", "itunes_xml"):
                self.assertIn("Tom &amp;", text, key)  # XML-escaped, and parsed back above
                self.assertIn("a%20%231/b%20c.flac", text, key)
            elif key == "json":
                self.assertIn('Tom & \\"Jerry\\", <Live>', text, key)  # JSON-escaped, parsed back above
            else:
                self.assertIn('Tom & "Jerry", <Live>', text.replace('""', '"'), key)
                self.assertIn("/music/a #1/b c.flac", text, key)

    def test_relative_paths(self):
        self.assertIn("\n../a #1/b c.flac\n", write("m3u8", style="relative"))
        self.assertIn("File2=../a #1/b c.flac\n", write("pls", style="relative"))
        self.assertIn("<location>../a%20%231/b%20c.flac</location>", write("xspf", style="relative"))
        self.assertIn('src="../a #1/b c.flac"', write("wpl", style="relative"))
        self.assertIn("\nb c.flac\n", write("m3u8", style="name"))

    def test_itunes_xml_always_absolute(self):
        # The Music app and iTunes can only import absolute file locations.
        plist = plistlib.loads(write("itunes_xml", style="relative").encode("utf-8"))
        self.assertEqual(plist["Tracks"]["2"]["Location"], "file:///music/a%20%231/b%20c.flac")

    def test_windows_paths_kept(self):
        items = [item(1, "Song", "A", "B", 10, "C:\\Music\\a b.mp3")]
        for key in ("m3u8", "pls", "wpl"):
            self.assertIn("C:\\Music\\a b.mp3", write(key, items), key)
        self.assertIn("file:///C:/Music/a%20b.mp3", write("xspf", items))
        self.assertEqual(plistlib.loads(write("itunes_xml", items).encode())["Tracks"]["1"]["Location"],
                         "file:///C:/Music/a%20b.mp3")

    def test_empty_playlist(self):
        for key in PLAYLIST_FORMATS:
            self.assertTrue(write(key, items=[]), key)


class ExportPlaylist(unittest.TestCase):
    def test_writes_selected_formats(self):
        with tempfile.TemporaryDirectory() as d:
            unsafe = Playlist("spotify", "x", "AC/DC: Best?", "")
            paths = export_playlist(unsafe, ITEMS, ["m3u8", "itunes_xml", "csv"], Path(d) / "new", "absolute")
            self.assertEqual([p.name for p in paths], ["ACDC Best.m3u8", "ACDC Best.xml", "ACDC Best.csv"])
            self.assertTrue(all(p.is_file() for p in paths))
            self.assertIn(b"\r\n", paths[2].read_bytes())        # CSV keeps RFC 4180 line ends
            self.assertNotIn(b"\r\n", paths[0].read_bytes())     # M3U8 keeps plain line ends
            self.assertEqual(paths[0].read_text(encoding="utf-8").splitlines()[0], "#EXTM3U")

    def test_unknown_format(self):
        with tempfile.TemporaryDirectory() as d, self.assertRaises(KeyError):
            export_playlist(PLAYLIST, ITEMS, ["mp3"], Path(d), "absolute")


class Players(unittest.TestCase):
    def test_every_player_format_exists(self):
        self.assertEqual(list(PLAYERS), ["itunes", "apple_music", "strawberry", "vlc", "mediamonkey", "winamp",
                                         "wmp", "media_player", "other"])
        for player in PLAYERS.values():
            self.assertIn(player.recommended, PLAYLIST_FORMATS, player.key)
            for key in player.also:
                self.assertIn(key, PLAYLIST_FORMATS, player.key)
            self.assertNotIn(player.recommended, player.also, player.key)
            self.assertTrue(player.platforms <= {"linux", "win32", "darwin"}, player.key)

    def test_recommendations_match_spec(self):
        self.assertEqual({k: p.recommended for k, p in PLAYERS.items()}, {
            "itunes": "itunes_xml", "apple_music": "itunes_xml", "strawberry": "m3u8", "vlc": "xspf",
            "mediamonkey": "m3u8", "winamp": "m3u8", "wmp": "wpl", "media_player": "m3u", "other": "m3u8"})
        self.assertEqual(set(PLAYERS["other"].also), set(PLAYLIST_FORMATS) - {"m3u8"})

    def test_default_player(self):
        self.assertEqual(default_player("strawberry", "linux"), "strawberry")
        self.assertEqual(default_player("itunes", "darwin"), "apple_music")
        self.assertEqual(default_player("itunes", "win32"), "itunes")
        self.assertEqual(default_player("mediamonkey", "win32"), "mediamonkey")
        self.assertEqual(default_player("folder", "linux"), "other")
        self.assertEqual(default_player("unknown", "linux"), "other")


if __name__ == "__main__":
    unittest.main()
