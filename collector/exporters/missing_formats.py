"""Missing-track lists for people who don't use NextUp: JSON, CSV, Markdown checklist, plain text.

The Markdown lines are the NextUp note's task lines (vault.task_line), so both read the same.
"""
import csv
import io
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable

from ..playlist import safe_filename
from ..tracks import Playlist, SourceTrack
from ..vault import intro_line, note_title, task_line

Writer = Callable[[Playlist, list[SourceTrack], str, date], str]


@dataclass
class MissingFormat:
    key: str
    label: str
    ext: str
    write: Writer


def _mmss(seconds: int) -> str:
    return f"{seconds // 60}:{seconds % 60:02d}" if seconds else ""


def write_md(playlist: Playlist, tracks: list[SourceTrack], service: str, today: date) -> str:
    lines = [f"# {note_title(playlist.name)}", "", intro_line(playlist, service), ""]
    lines += [task_line(t, service) for t in tracks]
    return "\n".join(lines) + "\n"


def write_txt(playlist: Playlist, tracks: list[SourceTrack], service: str, today: date) -> str:
    return "".join(f"{t.artist} - {t.title}\n" for t in tracks)


def write_csv(playlist: Playlist, tracks: list[SourceTrack], service: str, today: date) -> str:
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\r\n")
    w.writerow(["Title", "Artist", "Album", "Duration", "ISRC", "URL"])
    for t in tracks:
        w.writerow([t.title, t.artist, t.album, _mmss(t.duration), t.isrc, t.url])
    return out.getvalue()


def write_json(playlist: Playlist, tracks: list[SourceTrack], service: str, today: date) -> str:
    data = {
        "playlist": playlist.name, "source": playlist.source, "source_url": playlist.url,
        "exported_at": today.isoformat(),
        "tracks": [{"title": t.title, "artist": t.artist, "album": t.album, "duration": t.duration,
                    "isrc": t.isrc, "url": t.url} for t in tracks],
    }
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


MISSING_FORMATS: dict[str, MissingFormat] = {f.key: f for f in (
    MissingFormat("json", "JSON", ".json", write_json),
    MissingFormat("csv", "CSV (spreadsheet)", ".csv", write_csv),
    MissingFormat("md", "Markdown checklist", ".md", write_md),
    MissingFormat("txt", "Plain text, one per line", ".txt", write_txt),
)}


def export_missing(playlist: Playlist, missing: list[SourceTrack], fmt: str, folder: Path, service: str,
                   today: date | None = None) -> Path:
    """Write `<playlist> missing tracks.<ext>` into `folder`, replacing an earlier export."""
    chosen = MISSING_FORMATS[fmt]
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{safe_filename(note_title(playlist.name))}{chosen.ext}"
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(chosen.write(playlist, missing, service, today or date.today()))
    return path
