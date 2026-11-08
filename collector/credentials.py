"""Saved keys, IDs and tokens for each source, plus whether they last worked.

Kept in DATA_DIR/credentials.json, readable only by the user (mode 0600 where the OS has it).
The browser never gets secret values back: see public_view().
"""
import json
import os
import tempfile
from pathlib import Path
from typing import Iterable

from .config import DATA_DIR
from .sources.base import Source

CREDENTIALS_FILE = DATA_DIR / "credentials.json"


class CredentialStore:
    def __init__(self, path: Path = CREDENTIALS_FILE):
        self.path = path
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        self._values: dict[str, dict] = data.get("sources") or {}
        self._invalid: dict[str, dict] = data.get("invalid") or {}

    # ---- values ------------------------------------------------------------------------
    def get(self, source_id: str) -> dict:
        return dict(self._values.get(source_id) or {})

    def save(self, source_id: str, values: dict) -> None:
        """Merge values in. An empty string never replaces a saved value (blank secret fields
        in the form mean "keep what's saved")."""
        current = self._values.setdefault(source_id, {})
        for key, value in values.items():
            if value == "" and current.get(key):
                continue
            current[key] = value
        self._write()

    def remove(self, source_id: str, keys: Iterable[str]) -> None:
        current = self._values.get(source_id) or {}
        for key in keys:
            current.pop(key, None)
        self._write()

    def clear(self, source_id: str) -> None:
        self._values.pop(source_id, None)
        self._invalid.pop(source_id, None)
        self._write()

    # ---- status ------------------------------------------------------------------------
    def status(self, source: Source) -> dict:
        if source.id in self._invalid:
            bad = self._invalid[source.id]
            return {"state": "invalid", "error": bad.get("error", ""), "fix": bad.get("fix", "")}
        values = self._values.get(source.id) or {}
        missing = any(f.required and not values.get(f.key) for f in source.fields)
        if missing or (source.uses_oauth and not source.has_token(values)):
            return {"state": "needs_setup", "error": "", "fix": ""}
        return {"state": "ready", "error": "", "fix": ""}

    def mark_invalid(self, source_id: str, error: str, fix: str = "") -> None:
        self._invalid[source_id] = {"error": error, "fix": fix}
        self._write()

    def mark_ok(self, source_id: str) -> None:
        if self._invalid.pop(source_id, None) is not None:
            self._write()

    def public_view(self, source: Source) -> dict:
        """Field values safe to send to the browser: secrets only say whether they're set."""
        values = self._values.get(source.id) or {}
        return {f.key: ({"set": bool(values.get(f.key))} if f.secret else {"value": values.get(f.key, "")})
                for f in source.fields}

    # ---- file --------------------------------------------------------------------------
    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps({"sources": self._values, "invalid": self._invalid}, indent=1)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".credentials-", suffix=".tmp")
        try:
            if hasattr(os, "fchmod"):
                os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
            os.replace(tmp, self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
