"""Write "<Playlist> missing tracks" notes into the Obsidian vault, in NextUp's task format."""
import datetime as dt
import re
from dataclasses import dataclass
from pathlib import Path

from .matching import SpotifyTrack
from .playlist import safe_filename


@dataclass
class NoteResult:
    path: Path | None
    added: int
    ticked: int


def note_title(playlist_name: str) -> str:
    return f"{playlist_name} missing tracks"


def track_key(t: SpotifyTrack) -> str:
    return t.url or f'"{t.title}" by {t.artist}'


def task_line(t: SpotifyTrack) -> str:
    text = f'- [ ] Get "{_md(t.title)}" by {_md(t.artist)}'
    if t.album:
        text += f" ({_md(t.album)})"
    if t.url:
        text += f" [Spotify]({t.url})"
    return text


def _md(value: str) -> str:
    # Keep task lines from turning into links, tags or extra checkboxes.
    return re.sub(r"([\[\]#|])", r"\\\1", value)


def _line_key(line: str) -> str | None:
    m = re.search(r"\[Spotify\]\((https?://[^)]+)\)", line)
    if m:
        return m.group(1)
    m = re.match(r'\s*- \[.\] Get (".*") by (.*?)(?: \(.*\))?$', line)
    if m:
        return f"{m.group(1)} by {m.group(2)}".replace("\\", "")
    return None


def _ensure_frontmatter(lines: list[str], key: str, value: str) -> bool:
    """Add "key: value" to the note's frontmatter if the key isn't there. Returns True if added."""
    if not lines or lines[0].strip() != "---":
        return False
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            if any(re.match(rf"{key}\s*:", l) for l in lines[1:i]):
                return False
            lines.insert(i, f"{key}: {value}")
            return True
    return False


def write_missing_note(vault: Path, folder: str, area: str, playlist_name: str, playlist_url: str,
                       missing: list[SpotifyTrack], found: list[SpotifyTrack],
                       today: dt.date | None = None) -> NoteResult:
    """Create or update the note.

    New missing tracks are appended; tracks already listed are left alone; open tasks for tracks
    that are now in the library are ticked off.
    """
    today = today or dt.date.today()
    title = note_title(playlist_name)
    path = vault / folder / f"{safe_filename(title)}.md"

    if not path.exists():
        if not missing:
            return NoteResult(None, 0, 0)
        path.parent.mkdir(parents=True, exist_ok=True)
        header = [
            "---",
            f'project: "{title.replace(chr(34), "")}"',
            f"area: {area}",
            f"source: {playlist_url}",
            "tags: [music]",
            "checklist: false",
            "---",
            f"# {title}",
            "",
            f"Tracks from [the Spotify playlist]({playlist_url}) that aren't in your library yet.",
            "",
        ]
        lines = [task_line(t) for t in missing]
        path.write_text("\n".join(header + lines) + "\n", encoding="utf-8")
        return NoteResult(path, len(lines), 0)

    lines = path.read_text(encoding="utf-8").splitlines()
    added_setting = _ensure_frontmatter(lines, "checklist", "false")
    found_keys = {track_key(t) for t in found}
    existing = set()
    ticked = 0
    for i, line in enumerate(lines):
        key = _line_key(line)
        if key is None:
            continue
        existing.add(key)
        if key in found_keys and line.lstrip().startswith("- [ ]"):
            lines[i] = line.replace("- [ ]", "- [x]", 1) + f" ✅ {today.isoformat()}"
            ticked += 1

    new = [task_line(t) for t in missing if track_key(t) not in existing]
    if new:
        while lines and not lines[-1].strip():
            lines.pop()
        lines.extend(new)
    if new or ticked or added_setting:
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return NoteResult(path, len(new), ticked)
