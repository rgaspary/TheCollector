"""Remember what you picked for close matches, so re-runs don't ask the same thing twice."""
import json
from pathlib import Path

from .config import DATA_DIR

CHOICES_FILE = DATA_DIR / "choices.json"
MISSING = "missing"


class Choices:
    """Picks are stored as "<source>:<track id>". v1 stored bare Spotify IDs; those still count."""

    def __init__(self, path: Path = CHOICES_FILE):
        self.path = path
        try:
            self.data: dict[str, str] = json.loads(path.read_text())
        except (OSError, ValueError):
            self.data = {}

    def get(self, source: str, track_id: str) -> str | None:
        """A local file path, MISSING, or None if never decided."""
        found = self.data.get(f"{source}:{track_id}")
        if found is None and source == "spotify":
            found = self.data.get(track_id)
        return found

    def update(self, source: str, decisions: dict[str, str]):
        self.data.update({f"{source}:{tid}": pick for tid, pick in decisions.items()})
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=1))
