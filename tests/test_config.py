import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from collector import config, platform_paths


def write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


class LoadConfig(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_vault_section(self):
        path = write(self.dir / "c.toml", "[library]\ntype = \"strawberry\"\n")
        cfg = config.load(path)
        self.assertFalse(cfg.nextup_enabled)
        self.assertIsNone(cfg.vault_path)

    def test_missing_nextup_file(self):
        path = write(self.dir / "c.toml", f'[vault]\nnextup_config = "{self.dir / "nope.toml"}"\n')
        self.assertFalse(config.load(path).nextup_enabled)

    def test_nextup_vault_read(self):
        nextup = write(self.dir / "nextup.toml", '[vault]\npath = "vault"\nname = "Main"\n')
        path = write(self.dir / "c.toml", f'[vault]\nnextup_config = "{nextup}"\nnotes_folder = "Music"\n')
        cfg = config.load(path)
        self.assertTrue(cfg.nextup_enabled)
        self.assertEqual(cfg.vault_path, self.dir / "vault")
        self.assertEqual((cfg.vault_name, cfg.notes_folder), ("Main", "Music"))

    def test_export_dir_default(self):
        path = write(self.dir / "c.toml", "")
        self.assertEqual(config.load(path).export_dir, Path.home() / "Music/TheCollector Exports")

    def test_v1_library_keys_still_read(self):
        path = write(self.dir / "c.toml", '[library]\nstrawberry_db = "/x/strawberry.db"\n')
        cfg = config.load(path)
        self.assertEqual((cfg.library_type, cfg.library_path), ("strawberry", Path("/x/strawberry.db")))

    def test_new_library_keys(self):
        path = write(self.dir / "c.toml", '[library]\ntype = "folder"\nfolders = ["/m/a", "/m/b"]\n')
        cfg = config.load(path)
        self.assertEqual(cfg.library_type, "folder")
        self.assertEqual(cfg.library_folders, [Path("/m/a"), Path("/m/b")])

    def test_legacy_spotify_client_id(self):
        path = write(self.dir / "c.toml", '[spotify]\nclient_id = "abc"\n')
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SPOTIFY_CLIENT_ID", None)
            self.assertEqual(config.load(path).legacy_spotify_client_id, "abc")
        with mock.patch.dict(os.environ, {"SPOTIFY_CLIENT_ID": "env"}):
            self.assertEqual(config.load(path).legacy_spotify_client_id, "env")

    def test_library_file_uses_default_when_unset(self):
        path = write(self.dir / "c.toml", '[library]\ntype = "strawberry"\n')
        cfg = config.load(path)
        self.assertEqual(cfg.library_file, platform_paths.default_library_path("strawberry"))


class PlatformPaths(unittest.TestCase):
    def test_data_dir_per_platform(self):
        with mock.patch.dict(os.environ, {"APPDATA": "C:/Users/a/AppData/Roaming"}):
            self.assertEqual(platform_paths.data_dir("win32"), Path("C:/Users/a/AppData/Roaming/TheCollector"))
        self.assertEqual(platform_paths.data_dir("darwin"), Path.home() / "Library/Application Support/TheCollector")
        with mock.patch.dict(os.environ, {"XDG_DATA_HOME": "/xdg"}):
            self.assertEqual(platform_paths.data_dir("linux"), Path("/xdg/thecollector"))

    def test_default_library_paths(self):
        with mock.patch.dict(os.environ, {"LOCALAPPDATA": "C:/L", "APPDATA": "C:/R", "USERPROFILE": "C:/U"}):
            self.assertEqual(platform_paths.default_library_path("strawberry", "win32"),
                             Path("C:/L/strawberry/strawberry/strawberry.db"))
            self.assertEqual(platform_paths.default_library_path("itunes", "win32"),
                             Path("C:/U/Music/iTunes/iTunes Library.xml"))
            self.assertEqual(platform_paths.default_library_path("mediamonkey", "win32"),
                             Path("C:/R/MediaMonkey5/MM5.DB"))
        self.assertIsNone(platform_paths.default_library_path("mediamonkey", "linux"))
        self.assertIsNone(platform_paths.default_library_path("itunes", "linux"))
        self.assertEqual(platform_paths.default_library_path("folder", "linux"), Path.home() / "Music")


if __name__ == "__main__":
    unittest.main()
