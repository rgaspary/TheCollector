"""The interface every local music library reader implements."""
from pathlib import Path
from typing import ClassVar, Literal

from ..tracks import LocalTrack


class LibraryError(Exception):
    """A problem reading the library, in words the user can act on. `fix` says what to do."""

    def __init__(self, message: str, fix: str = ""):
        super().__init__(message)
        self.fix = fix


class Library:
    id: ClassVar[str]
    name: ClassVar[str]
    subtitle: ClassVar[str] = ""
    icon: ClassVar[str]                      # file in static/icons/apps/
    needs: ClassVar[Literal["file", "folders"]] = "file"
    help_text: ClassVar[str]
    recommended_player: ClassVar[str]        # key in exporters.players.PLAYERS

    def detect(self) -> Path | None:
        """The library's usual location on this computer, if it's there."""
        return None

    def load(self, path: Path | None, folders: list[Path]) -> list[LocalTrack]:
        raise NotImplementedError

    def warning(self, path: Path | None, folders: list[Path]) -> str:
        """Something about this library the user should know before trusting the results, or ""."""
        return ""

    def test(self, path: Path | None, folders: list[Path]) -> str:
        count = len(self.load(path, folders))
        return f"Found {count:,} track{'' if count == 1 else 's'}"


def require_file(path: Path | None, what: str, fix: str) -> Path:
    """The path, or a LibraryError naming it when it's missing."""
    if path is None:
        raise LibraryError(f"Choose your {what} first.", fix=fix)
    if not path.is_file():
        # Capitalise for the start of the sentence, but leave names like "iTunes" alone.
        start = what if what[1:2].isupper() else what[:1].upper() + what[1:]
        raise LibraryError(f"{start} wasn't found at {path}.", fix=fix)
    return path
