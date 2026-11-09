"""Write .m3u8 playlists Strawberry (and most players) can open."""
import re
from pathlib import Path

from .tracks import LocalTrack


def safe_filename(name: str) -> str:
    name = re.sub(r'[/\\:*?"<>|\x00-\x1f]', "", name).strip(" .")
    return name or "Playlist"


def write_m3u8(name: str, tracks: list[LocalTrack], folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{safe_filename(name)}.m3u8"
    lines = ["#EXTM3U", f"#PLAYLIST:{name}"]
    for t in tracks:
        lines.append(f"#EXTINF:{t.duration or -1},{t.artist} - {t.title}")
        lines.append(t.path)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
