"""All streaming sources, in the order their tiles are shown."""
import os

from .base import CredentialError, Field, Source, SourceError

REGISTRY: dict[str, Source] = {}


def register(source: Source) -> Source:
    REGISTRY[source.id] = source
    return source


def get_source(source_id: str) -> Source:
    return REGISTRY[source_id]


def detect(link: str) -> str | None:
    """The id of the source whose links look like this one, if any."""
    for source in REGISTRY.values():
        if source.matches_link(link):
            return source.id
    return None


from .spotify import SpotifySource  # noqa: E402  (after the helpers above)
from .youtube_music import YouTubeMusicSource  # noqa: E402

# Tile order. Apple Music, TIDAL and Qobuz are added here as they're built.
for _source in (SpotifySource(), YouTubeMusicSource()):
    register(_source)

if os.environ.get("COLLECTOR_FAKE_SOURCES") == "1":  # for trying the screens without real accounts
    from .fake import FakeSource
    register(FakeSource())

__all__ = ["REGISTRY", "CredentialError", "Field", "Source", "SourceError", "detect", "get_source", "register"]
