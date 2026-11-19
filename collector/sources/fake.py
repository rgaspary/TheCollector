"""A pretend music service for trying the screens without real accounts.

Registered only when the COLLECTOR_FAKE_SOURCES=1 environment variable is set. The token "ok" is
accepted; anything else is refused, so the set-up and fix screens can be tried too.
"""
from ..tracks import Playlist, SourceTrack
from .base import CredentialError, Field, Source

TRACKS = [
    ("Creep", "Radiohead", "Pablo Honey", 239),
    ("Black Hole Sun", "Soundgarden", "Superunknown", 320),
    ("Smells Like Teen Spirit", "Nirvana", "Nevermind", 301),
    ("Everlong", "Foo Fighters", "The Colour and the Shape", 250),
    ("Karma Police", "Radiohead", "OK Computer", 264),
    ("A Song Nobody Has", "Nobody", "Nothing", 200),
]


class FakeSource(Source):
    id = "fake"
    name = "Test Service"
    icon = "fake.svg"
    fields = [Field("token", "Token", secret=True, placeholder="ok", help='Type "ok" to pass the test.')]
    help_url = "https://example.com/"
    help_text = 'A pretend service for trying TheCollector. The token "ok" works; anything else is refused.'
    link_example = "https://fake.example/playlist/demo"
    limits = "Always returns the same six songs."
    link_patterns = (r"fake\.example/playlist/",)

    def parse_link(self, text: str) -> str:
        return text.strip().rstrip("/").rsplit("/", 1)[-1] or "demo"

    def test(self, creds: dict) -> str:
        if creds.get("token") != "ok":
            raise CredentialError("The test service refused the token.", fix='Type "ok" as the token.')
        return "Test Service accepted the token."

    def get_playlist(self, link: str, creds: dict) -> Playlist:
        self.test(creds)
        pid = self.parse_link(link)
        tracks = [SourceTrack(f"f{i}", title, [artist], album, duration, f"https://fake.example/track/f{i}")
                  for i, (title, artist, album, duration) in enumerate(TRACKS, start=1)]
        return Playlist(self.id, pid, "Test Playlist", f"https://fake.example/playlist/{pid}", tracks)
