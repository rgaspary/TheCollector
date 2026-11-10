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

    def test_folder_defaults_music_and_documents(self):
        path = write(self.dir / "c.toml", "")
        with mock.patch.object(platform_paths, "music_dir", return_value=Path("/u/Muziek")), \
                mock.patch.object(platform_paths, "documents_dir", return_value=Path("/u/Documenten")):
            cfg = config.load(path)
        self.assertEqual((cfg.playlist_dir, cfg.missing_dir), (Path("/u/Muziek/Playlists"), Path("/u/Documenten")))

    def test_folders_can_be_set(self):
        path = write(self.dir / "c.toml", '[export]\nplaylist_dir = "/p"\nmissing_dir = "/m"\n')
        cfg = config.load(path)
        self.assertEqual((cfg.playlist_dir, cfg.missing_dir), (Path("/p"), Path("/m")))

    def test_v1_playlist_dir_still_read(self):
        path = write(self.dir / "c.toml", '[library]\nplaylist_dir = "/v1/Playlists"\n')
        self.assertEqual(config.load(path).playlist_dir, Path("/v1/Playlists"))

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


V1_CONFIG = """# My settings
[spotify]
client_id = "abc"

[library]
# Strawberry's database
strawberry_db = "/home/a/.local/share/strawberry/strawberry/strawberry.db"
folders = [
  "/old/a",
  "/old/b",
]
# Where built playlists go.
playlist_dir = "~/Music/Playlists"

[server]
port = 8766  # keep me
"""


class SaveLibrary(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = write(Path(self.tmp.name) / "config.toml", V1_CONFIG)

    def test_library_save_keeps_other_config_lines(self):
        config.save_library("folder", None, [Path("/m/a"), Path("/m/b c")], self.path)
        text = self.path.read_text()
        for kept in ("# My settings", 'client_id = "abc"', "# Strawberry's database", "# Where built playlists go.",
                     'playlist_dir = "~/Music/Playlists"', "port = 8766  # keep me"):
            self.assertIn(kept, text)
        self.assertNotIn("strawberry_db", text)
        self.assertNotIn("/old/a", text)
        cfg = config.load(self.path)
        self.assertEqual((cfg.library_type, cfg.library_path), ("folder", None))
        self.assertEqual(cfg.library_folders, [Path("/m/a"), Path("/m/b c")])
        self.assertEqual(cfg.playlist_dir, Path.home() / "Music/Playlists")
        self.assertTrue(cfg.library_configured)

    def test_windows_path_round_trips(self):
        config.save_library("itunes", Path("C:\\Users\\a\\Music\\iTunes\\iTunes Library.xml"), [], self.path)
        self.assertEqual(str(config.load(self.path).library_path), "C:\\Users\\a\\Music\\iTunes\\iTunes Library.xml")

    def test_saving_twice_keeps_one_of_each_key(self):
        config.save_library("strawberry", Path("/x.db"), [], self.path)
        config.save_library("mediamonkey", Path("/y.db"), [], self.path)
        text = self.path.read_text()
        self.assertEqual((text.count("type ="), text.count("path ="), text.count("folders =")), (1, 1, 1))
        self.assertEqual(config.load(self.path).library_path, Path("/y.db"))

    def test_file_permissions_kept(self):
        self.path.chmod(0o640)
        config.save_library("folder", None, [], self.path)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o640)

    def test_no_library_section_appends_one(self):
        write(self.path, "[server]\nport = 1\n")
        config.save_library("folder", None, [Path("/m")], self.path)
        cfg = config.load(self.path)
        self.assertEqual((cfg.library_type, cfg.library_folders, cfg.port), ("folder", [Path("/m")], 1))


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

    def test_music_and_documents_from_xdg_user_dirs(self):
        with tempfile.TemporaryDirectory() as d:
            home, conf = Path(d) / "home", Path(d) / "conf"
            conf.mkdir()
            (conf / "user-dirs.dirs").write_text('XDG_MUSIC_DIR="$HOME/Muziek"\nXDG_DOCUMENTS_DIR="$HOME"\n')
            with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(conf)}), \
                    mock.patch.object(Path, "home", return_value=home):
                self.assertEqual(platform_paths.music_dir("linux"), home / "Muziek")
                # A folder set to $HOME itself means "not used": fall back to the usual name.
                self.assertEqual(platform_paths.documents_dir("linux"), home / "Documents")
            with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(Path(d) / "none")}), \
                    mock.patch.object(Path, "home", return_value=home):
                self.assertEqual(platform_paths.music_dir("linux"), home / "Music")

    def test_music_and_documents_elsewhere(self):
        self.assertEqual(platform_paths.music_dir("darwin"), Path.home() / "Music")
        self.assertEqual(platform_paths.documents_dir("darwin"), Path.home() / "Documents")
        with mock.patch.dict(os.environ, {"USERPROFILE": "C:/Users/a"}):  # no registry off Windows
            self.assertEqual(platform_paths.music_dir("win32"), Path("C:/Users/a/Music"))
            self.assertEqual(platform_paths.documents_dir("win32"), Path("C:/Users/a/Documents"))

    def test_open_folder_command(self):
        self.assertEqual(platform_paths.open_folder_command(Path("/a"), "linux"), ["xdg-open", "/a"])
        self.assertEqual(platform_paths.open_folder_command(Path("/a"), "darwin"), ["open", "/a"])
        self.assertEqual(platform_paths.open_folder_command(Path("C:/a"), "win32")[0], "explorer")


if __name__ == "__main__":
    unittest.main()
