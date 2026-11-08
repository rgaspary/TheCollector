"""Remember what you picked for close matches, so re-runs don't ask the same thing twice."""
import json
from pathlib import Path

from .config import DATA_DIR

CHOICES_FILE = DATA_DIR / "choices.json"
MISSING = "missing"


class Choices:
    def __init__(self, path: Path = CHOICES_FILE):
        self.path = path
        try:
            self.data: dict[str, str] = json.loads(path.read_text())
        except (OSError, ValueError):
            self.data = {}

    def get(self, spotify_id: str) -> str | None:
        """A local file path, MISSING, or None if never decided."""
        return self.data.get(spotify_id)

    def update(self, decisions: dict[str, str]):
        self.data.update(decisions)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=1))
