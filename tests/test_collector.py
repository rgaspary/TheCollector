import datetime as dt
import tempfile
import unittest
from pathlib import Path

from collector.library import LocalTrack, url_to_path
from collector.matching import SpotifyTrack, match_playlist, split_title
from collector.playlist import write_m3u8
from collector.spotify import SpotifyError, parse_playlist_id
from collector.vault import write_missing_note


def local(i, title, artist, album, duration=200):
    return LocalTrack(i, title, artist, album, duration, f"/music/{artist}/{album}/{title}.m4a")


def sp(i, title, artist, album, duration=200):
    return SpotifyTrack(str(i), title, [artist], album, duration, f"https://open.spotify.com/track/{i}")


LIBRARY = [
    local(1, "Black Hole Sun", "Soundgarden", "Superunknown", 320),
    local(2, "Creep", "Radiohead", "Pablo Honey", 239),
    local(3, "Paranoid Android", "Radiohead", "OK Computer", 383),
    local(4, "Smells Like Teen Spirit (Live)", "Nirvana", "From the Muddy Banks", 300),
    local(5, "Café del Mar", "Energy 52", "Café del Mar"),
    local(6, "Even Flow", "Pearl Jam", "Ten"),
]


class SplitTitle(unittest.TestCase):
    def test_tags(self):
        self.assertEqual(split_title("Black Hole Sun - Live"), ("black hole sun", {"live"}))
        self.assertEqual(split_title("Creep (Acoustic)"), ("creep", {"acoustic"}))
        self.assertEqual(split_title("Hey Jude - 2015 Remaster"), ("hey jude", {"remaster"}))
        self.assertEqual(split_title("Hey Jude - Remastered 2009"), ("hey jude", {"remaster"}))

    def test_neutral_and_feat(self):
        self.assertEqual(split_title("Song (feat. Someone)")[0], "song")
        self.assertEqual(split_title("Song - Single Version"), ("song", set()))
        self.assertEqual(split_title("(Don't Fear) The Reaper")[0], "don t fear the reaper")
        self.assertEqual(split_title("Song - Part Two")[0], "song part two")


class Matching(unittest.TestCase):
    def match(self, track):
        return match_playlist([track], LIBRARY)[0]

    def test_exact(self):
        r = self.match(sp(1, "Black Hole Sun", "Soundgarden", "Superunknown"))
        self.assertEqual(r.status, "exact")
        self.assertEqual(r.best.id, 1)

    def test_remaster_and_album_edition_still_exact(self):
        r = self.match(sp(1, "Creep - 2008 Remaster", "Radiohead", "Pablo Honey (Deluxe Edition)"))
        self.assertEqual(r.status, "exact")

    def test_accents(self):
        self.assertEqual(self.match(sp(1, "Cafe Del Mar", "Energy 52", "Cafe del Mar")).status, "exact")

    def test_live_is_close(self):
        r = self.match(sp(1, "Black Hole Sun - Live", "Soundgarden", "Superunknown"))
        self.assertEqual(r.status, "close")
        self.assertIn("live", r.candidates[0].reason)

    def test_local_live_is_close(self):
        r = self.match(sp(1, "Smells Like Teen Spirit", "Nirvana", "From the Muddy Banks"))
        self.assertEqual(r.status, "close")
        self.assertIn("Yours is the live version", r.candidates[0].reason)

    def test_different_album_is_close(self):
        r = self.match(sp(1, "Even Flow", "Pearl Jam", "rearviewmirror (Greatest Hits 1991-2003)"))
        self.assertEqual(r.status, "close")
        self.assertIn("Different album: Ten", r.candidates[0].reason)

    def test_missing(self):
        self.assertEqual(self.match(sp(1, "Karma Police", "Radiohead", "OK Computer")).status, "missing")
        self.assertEqual(self.match(sp(1, "Totally Unknown", "Nobody", "Nothing")).status, "missing")


class Files(unittest.TestCase):
    def test_url_to_path(self):
        self.assertEqual(url_to_path("file:///home/gc/Music/a%20b/c.m4a"), "/home/gc/Music/a b/c.m4a")

    def test_parse_playlist_id(self):
        pid = "37i9dQZF1DXcBWIGoYBM5M"
        self.assertEqual(parse_playlist_id(f"https://open.spotify.com/playlist/{pid}?si=abc"), pid)
        self.assertEqual(parse_playlist_id(f"https://open.spotify.com/intl-es/playlist/{pid}"), pid)
        self.assertEqual(parse_playlist_id(f"spotify:playlist:{pid}"), pid)
        with self.assertRaises(SpotifyError):
            parse_playlist_id("https://open.spotify.com/album/xyz")

    def test_m3u8(self):
        with tempfile.TemporaryDirectory() as d:
            path = write_m3u8("Road: Trip?", LIBRARY[:2], Path(d))
            self.assertEqual(path.name, "Road Trip.m3u8")
            lines = path.read_text().splitlines()
            self.assertEqual(lines[0], "#EXTM3U")
            self.assertEqual(lines[2], "#EXTINF:320,Soundgarden - Black Hole Sun")
            self.assertEqual(lines[3], LIBRARY[0].path)


class Note(unittest.TestCase):
    def test_create_merge_and_tick(self):
        a = sp("a", "Karma Police", "Radiohead", "OK Computer")
        b = sp("b", "Song [Live] #1", "Band | X", "")
        c = sp("c", "Third", "Band", "Album")
        today = dt.date(2026, 10, 28)
        with tempfile.TemporaryDirectory() as d:
            vault = Path(d)
            r1 = write_missing_note(vault, "Music", "music", "Mix", "https://p", [a, b], [], today)
            text = r1.path.read_text()
            self.assertEqual(r1.path.name, "Mix missing tracks.md")
            self.assertIn('project: "Mix missing tracks"', text)
            self.assertIn("area: music", text)
            self.assertIn("checklist: false", text)
            self.assertIn('- [ ] Get "Karma Police" by Radiohead (OK Computer) [Spotify](https://open.spotify.com/track/a)', text)
            self.assertIn(r'Song \[Live\] \#1', text)
            self.assertEqual(r1.added, 2)

            # Re-run: a is now owned, b still missing, c newly missing.
            r2 = write_missing_note(vault, "Music", "music", "Mix", "https://p", [b, c], [a], today)
            self.assertEqual((r2.added, r2.ticked), (1, 1))
            text = r2.path.read_text()
            self.assertIn("- [x] Get \"Karma Police\"", text)
            self.assertIn("✅ 2026-10-28", text)
            self.assertEqual(text.count("open.spotify.com/track/b"), 1)

            # Third run with nothing new changes nothing.
            r3 = write_missing_note(vault, "Music", "music", "Mix", "https://p", [b, c], [a], today)
            self.assertEqual((r3.added, r3.ticked), (0, 0))

    def test_older_note_gets_checklist_setting(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d) / "Music"
            folder.mkdir()
            note = folder / "Mix missing tracks.md"
            note.write_text('---\nproject: "Mix missing tracks"\narea: music\n---\n# Mix\n\n- [ ] Get "A" by B\n')
            write_missing_note(Path(d), "Music", "music", "Mix", "https://p", [], [], dt.date.today())
            text = note.read_text()
            self.assertIn("area: music\nchecklist: false\n---", text)
            write_missing_note(Path(d), "Music", "music", "Mix", "https://p", [], [], dt.date.today())
            self.assertEqual(note.read_text().count("checklist:"), 1)

    def test_no_note_when_nothing_missing(self):
        with tempfile.TemporaryDirectory() as d:
            r = write_missing_note(Path(d), "Music", "music", "Mix", "https://p", [], [], dt.date.today())
            self.assertIsNone(r.path)


if __name__ == "__main__":
    unittest.main()
