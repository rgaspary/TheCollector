import json
import os
import re
import shutil
import tempfile
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from . import platform_paths

ROOT = Path(__file__).resolve().parent.parent
# COLLECTOR_CONFIG points at another file, e.g. to try the app without touching your settings.
CONFIG_PATH = Path(os.environ.get("COLLECTOR_CONFIG") or ROOT / "config.toml").expanduser()
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
    playlist_dir: Path   # where playlists are saved unless the user picks another folder
    missing_dir: Path    # where missing-song lists are saved unless the user picks another folder
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
    export = raw.get("export") or {}

    return Config(
        legacy_spotify_client_id=os.environ.get("SPOTIFY_CLIENT_ID") or (raw.get("spotify") or {}).get("client_id", ""),
        library_type=lib_type,
        library_path=_path(lib_path) if lib_path else None,
        library_folders=[_path(f) for f in folders],
        library_configured="type" in library or "strawberry_db" in library,
        # [library] playlist_dir is v1's name for the same setting.
        playlist_dir=_path(export.get("playlist_dir") or library.get("playlist_dir")
                           or str(platform_paths.music_dir() / "Playlists")),
        missing_dir=_path(export.get("missing_dir") or str(platform_paths.documents_dir())),
        vault_path=vault_path,
        vault_name=vault_name,
        notes_folder=notes_folder,
        area=(raw.get("vault") or {}).get("area", "music"),
        host=server.get("host", "127.0.0.1"),
        port=int(server.get("port", 8766)),
    )


_TABLE = re.compile(r"^\s*\[\s*[A-Za-z0-9_.\-]+\s*\]\s*(#.*)?$")
_LIBRARY_KEYS = ("type", "path", "folders", "strawberry_db")


def _toml_str(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)  # a JSON string is a valid TOML basic string


def save_library(lib_type: str, path: Path | None, folders: list[Path], config_path: Path = CONFIG_PATH) -> None:
    """Write the library choice into config.toml's [library] table.

    Only the type/path/folders lines (and v1's strawberry_db) are replaced; comments, other keys and
    other tables stay as they were.
    """
    new = [f"type = {_toml_str(lib_type)}",
           f"path = {_toml_str(str(path) if path else '')}",
           "folders = [" + ", ".join(_toml_str(str(f)) for f in folders) + "]"]
    try:
        lines = config_path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        lines = []

    start = next((i for i, l in enumerate(lines) if re.match(r"^\s*\[\s*library\s*\]", l)), None)
    if start is None:
        while lines and not lines[-1].strip():
            lines.pop()
        lines += ([""] if lines else []) + ["[library]"] + new
    else:
        end = next((i for i in range(start + 1, len(lines)) if _TABLE.match(lines[i])), len(lines))
        kept, insert_at, i = [], None, start + 1
        while i < end:
            line = lines[i]
            m = re.match(r"^\s*([A-Za-z0-9_]+)\s*=\s*(.*)$", line)
            if m and m.group(1) in _LIBRARY_KEYS:
                if insert_at is None:
                    insert_at = len(kept)
                value = m.group(2).split("#")[0].strip()
                if value.startswith("[") and "]" not in value:  # multi-line array: skip to its end
                    while i < end and "]" not in lines[i].split("#")[0]:
                        i += 1
                i += 1
                continue
            kept.append(line)
            i += 1
        if insert_at is None:
            insert_at = 0
        kept[insert_at:insert_at] = new
        lines = lines[:start + 1] + kept + lines[end:]

    config_path.parent.mkdir(parents=True, exist_ok=True)
    mode = config_path.stat().st_mode & 0o777 if config_path.exists() else 0o644
    fd, tmp = tempfile.mkstemp(dir=config_path.parent, prefix=".config-", suffix=".tmp")
    if hasattr(os, "fchmod"):
        os.fchmod(fd, mode)  # keep the file's permissions (mkstemp makes it owner-only)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp, config_path)
