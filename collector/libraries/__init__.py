"""Local music library readers, in the order the library tiles show them."""
from ..tracks import LocalTrack
from .base import Library, LibraryError
from .strawberry import StrawberryLibrary

LIBRARIES: dict[str, Library] = {}


def register(library: Library) -> None:
    LIBRARIES[library.id] = library


def get_library(library_id: str) -> Library:
    return LIBRARIES[library_id]


for _library in (StrawberryLibrary(),):
    register(_library)

__all__ = ["LIBRARIES", "Library", "LibraryError", "LocalTrack", "get_library", "register"]
