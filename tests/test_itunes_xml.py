import unittest

from collector.itunes_xml import location_to_path, read_plist
from collector.sources.base import SourceError


class Locations(unittest.TestCase):
    def test_location_mac(self):
        self.assertEqual(location_to_path("file:///Users/a/Music/x%20y.m4a"), "/Users/a/Music/x y.m4a")
        self.assertEqual(location_to_path("file://localhost/Users/a/Music/x.m4a"), "/Users/a/Music/x.m4a")

    def test_location_windows_localhost(self):
        self.assertEqual(location_to_path("file://localhost/C:/Users/a/Music/x%20y.m4a"), "C:/Users/a/Music/x y.m4a")
        self.assertEqual(location_to_path("file:///D:/Music/%23hash%20%26%20more.mp3"), "D:/Music/#hash & more.mp3")

    def test_location_network_share(self):
        self.assertEqual(location_to_path("file://nas/music/a.flac"), "//nas/music/a.flac")

    def test_location_not_a_file(self):
        self.assertEqual(location_to_path("https://example.com/a.mp3"), "")
        self.assertEqual(location_to_path(""), "")


class ReadPlist(unittest.TestCase):
    def test_garbage_is_source_error(self):
        with self.assertRaises(SourceError):
            read_plist(b"not a plist")

    def test_not_a_dict_is_source_error(self):
        with self.assertRaises(SourceError):
            read_plist(b'<?xml version="1.0"?><plist version="1.0"><array/></plist>')


if __name__ == "__main__":
    unittest.main()
