import os
import plistlib
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from collector import libraries
from collector.libraries import LibraryError, LocalTrack, get_library
from collector.libraries import folder as folder_mod
from collector.libraries.folder import FolderLibrary, from_path
from collector.libraries.itunes import ItunesLibrary
from collector.libraries.mediamonkey import MediaMonkeyLibrary, casefold_compare
from collector.libraries.strawberry import StrawberryLibrary, url_to_path
from collector.libraries.tags import Tags
from tests.test_tags import flac, id3_text, id3v2

NS = 1_000_000_000


class Registry(unittest.TestCase):
    def test_registry_order(self):
        self.assertEqual(list(libraries.LIBRARIES), ["strawberry", "itunes", "mediamonkey", "folder"])
        self.assertIsInstance(get_library("strawberry"), StrawberryLibrary)
        with self.assertRaises(KeyError):
            get_library("nope")

    def test_every_library_describes_itself(self):
        for lib in libraries.LIBRARIES.values():
            self.assertTrue(lib.name and lib.icon and lib.help_text, lib.id)
            self.assertIn(lib.needs, ("file", "folders"))


class Strawberry(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "strawberry.db"
        con = sqlite3.connect(self.db)
        con.execute("CREATE TABLE songs (title TEXT, artist TEXT, albumartist TEXT, album TEXT, "
                    "length INTEGER, url TEXT, unavailable INTEGER DEFAULT 0)")
        con.executemany("INSERT INTO songs VALUES (?,?,?,?,?,?,?)", [
            ("Creep", "", "Radiohead", "Pablo Honey", 239 * NS, "file:///music/Radiohead/Creep%201.flac", 0),
            ("Gone", "Someone", "", "", 100 * NS, "file:///music/gone.mp3", 1),
        ])
        con.commit()
        con.close()

    def test_url_to_path(self):
        self.assertEqual(url_to_path("file:///home/gc/Music/a%20b/c.m4a"), "/home/gc/Music/a b/c.m4a")
        self.assertEqual(url_to_path("https://example.com/x.mp3"), "")

    def test_strawberry_loads_fixture_db(self):
        tracks = StrawberryLibrary().load(self.db, [])
        self.assertEqual(len(tracks), 1)
        t = tracks[0]
        self.assertIsInstance(t, LocalTrack)
        self.assertEqual((t.title, t.artist, t.album, t.duration, t.path),
                         ("Creep", "Radiohead", "Pablo Honey", 239, "/music/Radiohead/Creep 1.flac"))

    def test_strawberry_missing_file_is_library_error(self):
        with self.assertRaises(LibraryError) as cm:
            StrawberryLibrary().load(Path(self.tmp.name) / "nope.db", [])
        self.assertIn("nope.db", str(cm.exception))
        self.assertTrue(cm.exception.fix)

    def test_not_a_database_is_library_error(self):
        bad = Path(self.tmp.name) / "bad.db"
        bad.write_bytes(b"this is not sqlite" * 100)
        with self.assertRaises(LibraryError):
            StrawberryLibrary().load(bad, [])

    def test_test_counts_tracks(self):
        self.assertEqual(StrawberryLibrary().test(self.db, []), "Found 1 track")


class StrawberryBehind(unittest.TestCase):
    """Music files in Strawberry's folders that its library doesn't have yet."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        self.music = d / "Music"
        for name in ("Known/a b.flac", "Known/Gone.mp3", "New/one.flac", "New/two.MP3", "New/cover.jpg",
                     ".hidden/x.mp3"):
            (self.music / name).parent.mkdir(parents=True, exist_ok=True)
            (self.music / name).write_bytes(b"")
        self.db = d / "strawberry.db"
        con = sqlite3.connect(self.db)
        con.execute("CREATE TABLE directories (path TEXT, subdirs INTEGER)")
        con.execute("INSERT INTO directories VALUES (?, 0)", (str(self.music),))
        con.execute("CREATE TABLE songs (title TEXT, artist TEXT, albumartist TEXT, album TEXT, "
                    "length INTEGER, url TEXT, unavailable INTEGER DEFAULT 0)")
        base = self.music.as_uri()
        con.executemany("INSERT INTO songs VALUES (?,?,?,?,?,?,?)", [
            ("A B", "X", "", "", 0, base + "/Known/a%20b.flac", 0),
            ("Gone", "X", "", "", 0, base + "/Known/Gone.mp3", 1),  # marked unavailable, but it's there
        ])
        con.commit()
        con.close()

    def test_counts_files_strawberry_lacks(self):
        self.assertEqual(StrawberryLibrary().files_not_in_library(self.db), 3)

    def test_warning_names_the_count_and_the_fix(self):
        warning = StrawberryLibrary().warning(self.db, [])
        self.assertIn("3 music files", warning)
        self.assertIn("Update", warning)
        self.assertIn("Music folder", warning)

    def test_no_warning_when_up_to_date(self):
        con = sqlite3.connect(self.db)
        base = self.music.as_uri()
        con.execute("UPDATE songs SET unavailable = 0")
        con.executemany("INSERT INTO songs (title, url) VALUES ('t', ?)",
                        [(base + "/New/one.flac",), (base + "/New/two.MP3",)])
        con.commit()
        con.close()
        self.assertEqual(StrawberryLibrary().files_not_in_library(self.db), 0)
        self.assertEqual(StrawberryLibrary().warning(self.db, []), "")

    def test_missing_folder_or_old_db_gives_no_warning(self):
        con = sqlite3.connect(self.db)
        con.execute("UPDATE directories SET path = ?", (str(self.music / "nope"),))
        con.commit()
        con.close()
        self.assertEqual(StrawberryLibrary().warning(self.db, []), "")
        old = Path(self.tmp.name) / "old.db"
        sqlite3.connect(old).execute("CREATE TABLE songs (url TEXT)").connection.close()
        self.assertEqual(StrawberryLibrary().warning(old, []), "")
        self.assertEqual(StrawberryLibrary().warning(Path(self.tmp.name) / "none.db", []), "")

    def test_other_libraries_have_no_warning(self):
        self.assertEqual(FolderLibrary().warning(None, [self.music]), "")


def itunes_library(tracks: dict) -> bytes:
    return plistlib.dumps({"Major Version": 1, "Tracks": tracks, "Playlists": []})


class Itunes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.xml = Path(self.tmp.name) / "Library.xml"
        self.xml.write_bytes(itunes_library({
            "101": {"Track ID": 101, "Name": "Paranoid Android", "Artist": "Radiohead", "Album": "OK Computer",
                    "Total Time": 383000, "Track Type": "File",
                    "Location": "file://localhost/C:/Users/a/Music/Radiohead/OK%20Computer/02%20Paranoid%20Android.m4a"},
            "102": {"Track ID": 102, "Name": "Streamed", "Artist": "Someone", "Track Type": "Remote",
                    "Apple Music": True, "Total Time": 200000},
            "103": {"Track ID": 103, "Name": "Episode 1", "Artist": "A Show", "Podcast": True, "Track Type": "File",
                    "Location": "file:///Users/a/Podcasts/ep1.mp3"},
            "104": {"Track ID": 104, "Name": "Song", "Album Artist": "Band", "Track Type": "File",
                    "Location": "file:///Users/a/Music/song.mp3"},
        }))

    def test_loads_fixture_plist(self):
        tracks = sorted(ItunesLibrary().load(self.xml, []), key=lambda t: t.id)
        self.assertEqual([t.id for t in tracks], [101, 104])
        t = tracks[0]
        self.assertEqual((t.title, t.artist, t.album, t.duration, t.path),
                         ("Paranoid Android", "Radiohead", "OK Computer", 383,
                          "C:/Users/a/Music/Radiohead/OK Computer/02 Paranoid Android.m4a"))

    def test_artist_falls_back_to_album_artist(self):
        tracks = {t.id: t for t in ItunesLibrary().load(self.xml, [])}
        self.assertEqual((tracks[104].artist, tracks[104].album, tracks[104].duration), ("Band", "", 0))

    def test_bad_xml_is_library_error(self):
        self.xml.write_bytes(b"<html>nope</html>")
        with self.assertRaises(LibraryError) as cm:
            ItunesLibrary().load(self.xml, [])
        self.assertTrue(cm.exception.fix)

    def test_missing_file_is_library_error(self):
        with self.assertRaises(LibraryError) as cm:
            ItunesLibrary().load(Path(self.tmp.name) / "none.xml", [])
        self.assertTrue(str(cm.exception).startswith("iTunes / Apple Music library XML wasn't found"))

    def test_help_text_covers_mac_and_windows(self):
        self.assertIn("Share Library XML", ItunesLibrary.help_text)
        self.assertIn("Share iTunes Library XML", ItunesLibrary.help_text)


class MediaMonkey(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "MM5.DB"
        con = sqlite3.connect(self.db)
        con.create_collation("IUNICODE", casefold_compare)
        con.execute("CREATE TABLE Medias (IDMedia INTEGER PRIMARY KEY, DriveLetter INTEGER, Label TEXT)")
        con.execute("CREATE TABLE Songs (ID INTEGER PRIMARY KEY, SongTitle TEXT COLLATE IUNICODE, "
                    "Artist TEXT COLLATE IUNICODE, AlbumArtist TEXT, Album TEXT, SongLength INTEGER, "
                    "SongPath TEXT COLLATE IUNICODE, IDMedia INTEGER)")
        con.executemany("INSERT INTO Medias VALUES (?,?,?)", [(1, 2, "System"), (2, 3, "Data")])
        con.executemany("INSERT INTO Songs VALUES (?,?,?,?,?,?,?,?)", [
            (1, "Creep", "Radiohead", "", "Pablo Honey", 239000, ":\\Music\\a.mp3", 1),
            (2, "Jóga", "Björk; Someone", "Björk", "Homogenic", 305400, ":\\b.flac", 2),
            (3, "Already Full", "", "Band", "", None, "E:\\c.mp3", 1),
            (4, "Online", "Web", "", "", 1000, "https://example.com/x.mp3", 1),
        ])
        con.commit()
        con.close()

    def test_loads_fixture_db(self):
        tracks = {t.id: t for t in MediaMonkeyLibrary().load(self.db, [])}
        self.assertEqual(sorted(tracks), [1, 2, 3])
        self.assertEqual(tracks[1].path, "C:\\Music\\a.mp3")
        self.assertEqual(tracks[2].path, "D:\\b.flac")
        self.assertEqual(tracks[3].path, "E:\\c.mp3")
        self.assertEqual((tracks[1].title, tracks[1].artist, tracks[1].album, tracks[1].duration),
                         ("Creep", "Radiohead", "Pablo Honey", 239))
        self.assertEqual((tracks[2].artist, tracks[2].duration), ("Björk, Someone", 305))
        self.assertEqual((tracks[3].artist, tracks[3].duration), ("Band", 0))

    def test_query_with_iunicode_column_works(self):
        # Without the collation sqlite refuses: "no such collation sequence: IUNICODE".
        con = sqlite3.connect(self.db)
        with self.assertRaises(sqlite3.OperationalError):
            con.execute("SELECT * FROM Songs ORDER BY SongTitle").fetchall()
        con.close()
        self.assertEqual(len(MediaMonkeyLibrary().load(self.db, [])), 3)

    def test_casefold_compare(self):
        self.assertEqual(casefold_compare("björk", "BJÖRK"), 0)
        self.assertLess(casefold_compare("a", "B"), 0)
        self.assertGreater(casefold_compare("b", "A"), 0)

    def test_missing_db_is_library_error(self):
        with self.assertRaises(LibraryError):
            MediaMonkeyLibrary().load(Path(self.tmp.name) / "none.db", [])

    def test_wrong_database_is_library_error(self):
        other = Path(self.tmp.name) / "other.db"
        sqlite3.connect(other).execute("CREATE TABLE x (a)").connection.close()
        with self.assertRaises(LibraryError) as cm:
            MediaMonkeyLibrary().load(other, [])
        self.assertIn("MediaMonkey", str(cm.exception))


class Folder(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "Music"
        self.cache = Path(self.tmp.name) / "folder-index.json"
        self.put("Radiohead/OK Computer/02 - Paranoid Android.flac", b"no tags here")
        self.put("Björk/Homogenic/01 Hunter.mp3", id3v2(4, [("TIT2", id3_text(3, "Hunter")),
                                                            ("TPE1", id3_text(3, "Björk")),
                                                            ("TALB", id3_text(3, "Homogenic"))]))
        self.put("Loose/Pearl Jam - Even Flow.ogg", b"")
        self.put("Loose/notes.txt", b"not music")
        self.put(".hidden/secret.mp3", b"")
        self.put("Radiohead/tagged.flac", flac(44100, 441000, [("TITLE", "Creep"), ("ARTIST", "Radiohead")]))

    def put(self, rel: str, data: bytes) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def lib(self) -> FolderLibrary:
        return FolderLibrary(cache_path=self.cache)

    def test_scans_audio_files_only(self):
        tracks = self.lib().load(None, [self.root])
        self.assertEqual(sorted(t.title for t in tracks), ["Creep", "Even Flow", "Hunter", "Paranoid Android"])
        self.assertEqual(len({t.id for t in tracks}), 4)

    def test_title_from_path(self):
        self.assertEqual(from_path(Path("Radiohead/OK Computer/02 - Paranoid Android.flac"), Tags()),
                         Tags("Paranoid Android", "Radiohead", "OK Computer", "", 0))
        self.assertEqual(from_path(Path("Pearl Jam - Even Flow.ogg"), Tags()), Tags("Even Flow", "Pearl Jam", "", "", 0))
        self.assertEqual(from_path(Path("Radiohead/OK Computer/Radiohead - Airbag.mp3"), Tags()).title, "Airbag")
        self.assertEqual(from_path(Path("05. Song.mp3"), Tags()), Tags("Song", "", "", "", 0))
        self.assertEqual(from_path(Path("A/B/x.mp3"), Tags("T", "", "", "Band", 5)), Tags("T", "Band", "B", "Band", 5))

    def test_tracks_use_tags_and_path(self):
        tracks = {t.title: t for t in self.lib().load(None, [self.root])}
        self.assertEqual((tracks["Hunter"].artist, tracks["Hunter"].album), ("Björk", "Homogenic"))
        self.assertEqual((tracks["Creep"].duration, tracks["Even Flow"].artist), (10, "Pearl Jam"))
        self.assertEqual(Path(tracks["Hunter"].path), self.root / "Björk/Homogenic/01 Hunter.mp3")

    def test_cache_skips_unchanged_files(self):
        self.lib().load(None, [self.root])
        with mock.patch.object(folder_mod, "read_tags", wraps=folder_mod.read_tags) as spy:
            self.lib().load(None, [self.root])
            self.assertEqual(spy.call_count, 0)
            changed = self.root / "Radiohead/tagged.flac"
            changed.write_bytes(flac(44100, 882000, [("TITLE", "Creep (Acoustic)"), ("ARTIST", "Radiohead")]))
            os.utime(changed, ns=(changed.stat().st_atime_ns, changed.stat().st_mtime_ns + 10**9))
            titles = {t.title for t in self.lib().load(None, [self.root])}
            self.assertEqual(spy.call_count, 1)
        self.assertIn("Creep (Acoustic)", titles)

    def test_removed_files_leave_the_cache(self):
        self.lib().load(None, [self.root])
        (self.root / "Loose/Pearl Jam - Even Flow.ogg").unlink()
        self.lib().load(None, [self.root])
        self.assertNotIn("Even Flow", self.cache.read_text())

    def test_broken_cache_is_rebuilt(self):
        self.cache.write_text("{broken")
        self.assertEqual(len(self.lib().load(None, [self.root])), 4)

    def test_no_folders_is_library_error(self):
        with mock.patch.object(FolderLibrary, "detect", return_value=None):
            with self.assertRaises(LibraryError):
                self.lib().load(None, [])

    def test_missing_folder_is_library_error(self):
        with self.assertRaises(LibraryError) as cm:
            self.lib().load(None, [Path(self.tmp.name) / "gone"])
        self.assertIn("gone", str(cm.exception))

    def test_several_folders_one_missing(self):
        other = Path(self.tmp.name) / "More"
        other.mkdir()
        (other / "Song.mp3").write_bytes(b"")
        tracks = self.lib().load(None, [self.root, other, Path(self.tmp.name) / "gone"])
        self.assertEqual(len(tracks), 5)


if __name__ == "__main__":
    unittest.main()
