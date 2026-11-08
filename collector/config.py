import os
import shutil
import tomllib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.toml"
EXAMPLE_PATH = ROOT / "config.example.toml"
DATA_DIR = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "thecollector"


def _path(value: str) -> Path:
    return Path(os.path.expanduser(value))


@dataclass
class Config:
    client_id: str
    strawberry_db: Path
    playlist_dir: Path
    vault_path: Path
    vault_name: str
    notes_folder: str
    area: str
    host: str
    port: int

    @property
    def redirect_uri(self) -> str:
        return f"http://{self.host}:{self.port}/callback"


def load(path: Path = CONFIG_PATH) -> Config:
    if path == CONFIG_PATH and not path.exists() and EXAMPLE_PATH.exists():
        shutil.copyfile(EXAMPLE_PATH, path)  # first run from a fresh clone
    with open(path, "rb") as f:
        raw = tomllib.load(f)

    nextup_path = _path(raw["vault"]["nextup_config"])
    with open(nextup_path, "rb") as f:
        nextup = tomllib.load(f)
    vault_path = Path(nextup["vault"]["path"]).expanduser()
    if not vault_path.is_absolute():
        vault_path = nextup_path.parent / vault_path

    return Config(
        client_id=os.environ.get("SPOTIFY_CLIENT_ID") or raw["spotify"].get("client_id", ""),
        strawberry_db=_path(raw["library"]["strawberry_db"]),
        playlist_dir=_path(raw["library"]["playlist_dir"]),
        vault_path=vault_path,
        vault_name=nextup["vault"].get("name", vault_path.name),
        notes_folder=raw["vault"]["notes_folder"],
        area=raw["vault"].get("area", "music"),
        host=raw["server"].get("host", "127.0.0.1"),
        port=int(raw["server"].get("port", 8766)),
    )
