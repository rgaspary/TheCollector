"""Write a matched playlist in the formats music apps import."""
from pathlib import Path

from ..playlist import PathStyle, safe_filename
from ..tracks import Playlist
from .playlist_formats import PLAYLIST_FORMATS, ExportItem, PlaylistFormat


def export_playlist(playlist: Playlist, items: list[ExportItem], formats: list[str], folder: Path,
                    style: PathStyle) -> list[Path]:
    """Write one file per format into `folder` and return their paths. Unknown formats raise KeyError
    before anything is written."""
    chosen = [PLAYLIST_FORMATS[key] for key in formats]
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for fmt in chosen:
        path = folder / f"{safe_filename(playlist.name)}{fmt.ext}"
        # newline="" keeps each writer's own line ends (CSV uses \r\n, the rest \n).
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(fmt.write(playlist, items, folder, style))
        paths.append(path)
    return paths


__all__ = ["PLAYLIST_FORMATS", "ExportItem", "PlaylistFormat", "export_playlist"]
