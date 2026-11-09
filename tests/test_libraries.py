import sqlite3
import tempfile
import unittest
from pathlib import Path

from collector import libraries
from collector.libraries import LibraryError, LocalTrack, get_library
from collector.libraries.strawberry import StrawberryLibrary, url_to_path

NS = 1_000_000_000


class Registry(unittest.TestCase):
    def test_registry_order(self):
        self.assertEqual(list(libraries.LIBRARIES)[:1], ["strawberry"])
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


if __name__ == "__main__":
    unittest.main()
