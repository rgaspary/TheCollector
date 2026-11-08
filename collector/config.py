import os
import shutil
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from . import platform_paths

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.toml"
EXAMPLE_PATH = ROOT / "config.example.toml"
DATA_DIR = platform_paths.data_dir()


def _path(value: str) -> Path:
    return Path(os.path.expanduser(value))


@dataclass
class Config:
    legacy_spotify_client_id: str
    library_type: str
    library_path: Path | None
    library_folders: list[Path]
    playlist_dir: Path
    export_dir: Path
    vault_path: Path | None
    vault_name: str | None
    notes_folder: str | None
    area: str
    host: str
    port: int
    library_configured: bool = field(default=False)

    @property
    def redirect_uri(self) -> str:
        return f"http://{self.host}:{self.port}/callback"

    @property
    def nextup_enabled(self) -> bool:
        return self.vault_path is not None and bool(self.notes_folder)

    @property
    def library_file(self) -> Path | None:
        """The configured library file, or the usual location for this library type."""
        return self.library_path or platform_paths.default_library_path(self.library_type)


def _load_vault(raw: dict) -> tuple[Path | None, str | None, str | None]:
    """Read the vault from NextUp's config. Missing section or file means NextUp isn't used."""
    section = raw.get("vault") or {}
    if not section.get("nextup_config"):
        return None, None, None
    nextup_path = _path(section["nextup_config"])
    try:
        with open(nextup_path, "rb") as f:
            nextup = tomllib.load(f)
        vault_path = Path(nextup["vault"]["path"]).expanduser()
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        return None, None, None
    if not vault_path.is_absolute():
        vault_path = nextup_path.parent / vault_path
    name = nextup["vault"].get("name", vault_path.name)
    return vault_path, name, section.get("notes_folder", "Entertainment/Missing Tracks")


def load(path: Path = CONFIG_PATH) -> Config:
    if path == CONFIG_PATH and not path.exists() and EXAMPLE_PATH.exists():
        shutil.copyfile(EXAMPLE_PATH, path)  # first run from a fresh clone
    with open(path, "rb") as f:
        raw = tomllib.load(f)

    library = raw.get("library") or {}
    lib_type = library.get("type") or "strawberry"
    # v1 used [library] strawberry_db; v2 uses type + path.
    lib_path = library.get("path") or (library.get("strawberry_db") if lib_type == "strawberry" else "")
    folders = library.get("folders") or []
    vault_path, vault_name, notes_folder = _load_vault(raw)
    server = raw.get("server") or {}

    return Config(
        legacy_spotify_client_id=os.environ.get("SPOTIFY_CLIENT_ID") or (raw.get("spotify") or {}).get("client_id", ""),
        library_type=lib_type,
        library_path=_path(lib_path) if lib_path else None,
        library_folders=[_path(f) for f in folders],
        library_configured="type" in library or "strawberry_db" in library,
        playlist_dir=_path(library.get("playlist_dir") or "~/Music/Playlists"),
        export_dir=_path((raw.get("export") or {}).get("dir") or "~/Music/TheCollector Exports"),
        vault_path=vault_path,
        vault_name=vault_name,
        notes_folder=notes_folder,
        area=(raw.get("vault") or {}).get("area", "music"),
        host=server.get("host", "127.0.0.1"),
        port=int(server.get("port", 8766)),
    )
