"""Match Spotify tracks to local tracks.

Ported from spotify-itunes-gap-analyzer/src/utils/matching.ts, with one change: version words
like "live" or "acoustic" are pulled out of the title as tags instead of being thrown away, so
a live recording is offered as a close match rather than counted as the same song.
"""
import re
import unicodedata
from dataclasses import dataclass, field

from .library import LocalTrack
from .tracks import SourceTrack

SpotifyTrack = SourceTrack  # v1 name, kept for one release

MATCH_THRESHOLD = 0.92
PARTIAL_THRESHOLD = 0.6
CROSS_ARTIST_PENALTY = 0.85
MAX_CANDIDATES = 3

# Words that mark a different recording. Order matters: first match wins per phrase.
TAG_PATTERNS = [
    ("live", r"\blive\b|\bin concert\b|\bconcert\b"),
    ("acoustic", r"\bacoustic\b|\bunplugged\b"),
    ("remix", r"\bremix\b|\bmix\b|\brework\b|\bdub\b"),
    ("demo", r"\bdemo\b"),
    ("edit", r"\bedit\b"),
    ("instrumental", r"\binstrumental\b|\bkaraoke\b"),
    ("extended", r"\bextended\b"),
    ("re-recorded", r"\bre ?recorded\b|\btaylor s version\b"),
    ("orchestral", r"\borchestral\b|\bsymphonic\b"),
    ("mono", r"\bmono\b"),
    ("remaster", r"\bremaster(ed)?\b"),
    ("stereo", r"\bstereo\b"),
]
# Tags that don't change the song enough to ask about.
MINOR_TAGS = {"remaster", "stereo", "mono"}
# Suffixes that carry no meaning and are just dropped.
NEUTRAL = r"\b(single|album|lp|original|radio)? ?version\b|\bexplicit\b|\bclean\b|\bbonus track\b|\bfrom .*\b(soundtrack|motion picture|series)\b"

TAG_LABELS = {
    "live": "live version",
    "acoustic": "acoustic version",
    "remix": "remix",
    "demo": "demo",
    "edit": "edit",
    "instrumental": "instrumental",
    "extended": "extended version",
    "re-recorded": "re-recorded version",
    "orchestral": "orchestral version",
}

ALBUM_EDITION = re.compile(
    r"[\(\[][^\)\]]*\b(deluxe|edition|remaster(ed)?|expanded|anniversary|special|bonus|version|reissue)\b[^\)\]]*[\)\]]"
)


def _fold(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(c for c in value if not unicodedata.combining(c))
    return value.lower().replace("’", "'").replace("‘", "'").replace("&", " and ")


def _clean(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def _strip_feat(value: str) -> str:
    value = re.sub(r"[\(\[]\s*(feat|ft|featuring|with)\b[^\)\]]*[\)\]]", " ", value)
    return re.sub(r"\s(feat|ft|featuring)\b\.?.*$", " ", value)


def _tags_in(text: str) -> set[str]:
    text = _clean(text)
    return {tag for tag, pattern in TAG_PATTERNS if re.search(pattern, text)}


def split_title(title: str) -> tuple[str, set[str]]:
    """Return (normalized base title, version tags)."""
    t = _strip_feat(_fold(title))
    tags: set[str] = set()

    def bracket(match: re.Match) -> str:
        inner = match.group(1)
        found = _tags_in(inner)
        if found or re.search(NEUTRAL, _clean(inner)):
            tags.update(found)
            return " "
        return " " + inner + " "

    t = re.sub(r"[\(\[]([^\)\]]*)[\)\]]", bracket, t)

    # "Song - Live at Wembley", "Song - 2011 Remaster"
    parts = re.split(r"\s[-–—]\s", t)
    base = parts[0]
    for suffix in parts[1:]:
        found = _tags_in(suffix)
        if found or re.search(NEUTRAL, _clean(suffix)) or re.fullmatch(r"\s*\d{4}\s*", suffix):
            tags.update(found)
        else:
            base += " " + suffix
    return _clean(base), tags


def normalize_artist(artist: str) -> str:
    a = _clean(_strip_feat(_fold(artist)))
    return re.sub(r"^the ", "", a)


def normalize_album(album: str) -> str:
    a = ALBUM_EDITION.sub(" ", _fold(album))
    a = re.split(r"\s[-–—]\s", a)[0]
    return _clean(a)


def levenshtein(a: str, b: str) -> int:
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(prev[j - 1] if ca == cb else 1 + min(prev[j], cur[j - 1], prev[j - 1]))
        prev = cur
    return prev[-1]


def similarity(a: str, b: str) -> float:
    if a == b:
        return 1.0
    longest = max(len(a), len(b))
    if longest == 0:
        return 1.0
    if abs(len(a) - len(b)) / longest > 1 - PARTIAL_THRESHOLD:
        return 0.0  # can't reach the threshold; skip the expensive part
    return 1 - levenshtein(a, b) / longest


@dataclass
class _Indexed:
    track: LocalTrack
    base: str
    tags: set[str]
    album: str


class LibraryIndex:
    def __init__(self, tracks: list[LocalTrack]):
        self.by_artist: dict[str, list[_Indexed]] = {}
        self.by_id: dict[int, LocalTrack] = {}
        for t in tracks:
            base, tags = split_title(t.title)
            item = _Indexed(t, base, tags, normalize_album(t.album))
            self.by_artist.setdefault(normalize_artist(t.artist), []).append(item)
            self.by_id[t.id] = t

    def artist_items(self, artists: list[str]) -> list[_Indexed]:
        keys = {normalize_artist(a) for a in artists}
        items: list[_Indexed] = []
        for key in keys:
            items.extend(self.by_artist.get(key, []))
        if items:
            return items
        # Fall back to near-identical artist names ("Alice In Chains" vs "Alice in Chains & X").
        for local_key, group in self.by_artist.items():
            if any(similarity(k, local_key) >= MATCH_THRESHOLD for k in keys):
                items.extend(group)
        return items


@dataclass
class Candidate:
    track: LocalTrack
    score: float
    exact: bool
    reason: str


@dataclass
class MatchResult:
    spotify: SpotifyTrack
    status: str  # "exact", "close" or "missing"
    candidates: list[Candidate] = field(default_factory=list)

    @property
    def best(self) -> LocalTrack | None:
        return self.candidates[0].track if self.candidates else None


def _describe_tags(wanted: set[str], have: set[str]) -> str:
    wanted, have = wanted - MINOR_TAGS, have - MINOR_TAGS
    if have - wanted:
        return "Yours is the " + ", ".join(TAG_LABELS[t] for t in sorted(have - wanted))
    if wanted - have:
        labels = ", ".join(TAG_LABELS[t] for t in sorted(wanted - have))
        return f"Spotify's is the {labels}; yours isn't"
    return ""


def _grade(item: _Indexed, base: str, tags: set[str], album: str, cross_artist: bool) -> Candidate | None:
    score = similarity(base, item.base)
    if cross_artist:
        score *= CROSS_ARTIST_PENALTY
    if score < PARTIAL_THRESHOLD:
        return None
    reasons = []
    if cross_artist:
        reasons.append(f"Different artist: {item.track.artist}")
    if score < MATCH_THRESHOLD:
        reasons.append("Similar title")
    tag_reason = _describe_tags(tags, item.tags)
    if tag_reason:
        reasons.append(tag_reason)
    if album != item.album:
        reasons.append(f"Different album: {item.track.album or 'unknown'}")
    return Candidate(item.track, round(score, 2), exact=not reasons, reason="; ".join(reasons))


def match_track(sp: SpotifyTrack, index: LibraryIndex) -> MatchResult:
    base, tags = split_title(sp.title)
    album = normalize_album(sp.album)

    graded = [c for item in index.artist_items(sp.artists) if (c := _grade(item, base, tags, album, False))]
    if not graded:
        for group in index.by_artist.values():
            for item in group:
                if c := _grade(item, base, tags, album, True):
                    graded.append(c)

    if not graded:
        return MatchResult(sp, "missing")

    graded.sort(key=lambda c: (not c.exact, -c.score, abs(c.track.duration - sp.duration)))
    # Duplicate files of the same song on the same album only need to be offered once.
    seen, unique = set(), []
    for c in graded:
        key = (c.track.title.lower(), c.track.album.lower(), c.track.artist.lower())
        if key not in seen:
            seen.add(key)
            unique.append(c)
    status = "exact" if unique[0].exact else "close"
    return MatchResult(sp, status, unique[:MAX_CANDIDATES])


def match_playlist(tracks: list[SpotifyTrack], library: list[LocalTrack]) -> list[MatchResult]:
    index = LibraryIndex(library)
    return [match_track(t, index) for t in tracks]
