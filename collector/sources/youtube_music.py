"""YouTube Music: public and unlisted playlists through the YouTube Data API v3 (API key only).

YouTube Music playlists are ordinary YouTube playlists, so the same API reads both. Videos don't
carry artist/title fields, so they're taken from the video title and the channel name.
"""
import json
import re
import urllib.parse

from .. import http
from ..http import HttpError
from ..tracks import Playlist, SourceTrack
from .base import CredentialError, Field, Source, SourceError, parse_iso_duration

API = "https://www.googleapis.com/youtube/v3"
PAGE_SIZE = 50

BAD_KEY = CredentialError(
    "YouTube didn't accept the API key.",
    fix="Copy the key again from console.cloud.google.com → APIs & Services → Credentials.")
NOT_ENABLED = CredentialError(
    "The YouTube Data API isn't turned on for this key's project.",
    fix="In Google Cloud Console open APIs & Services → Library, find YouTube Data API v3 and click Enable.")

# "(Official Video)", "[Official Music Video]", "(Lyrics)", "(Visualizer)", "[HD]" ... but not "(Live)".
_NOISE = re.compile(
    r"\s*[\(\[]\s*(?:official\s+)?(?:hd\s+|4k\s+)?(?:music\s+|lyric\s+)?"
    r"(?:video|audio|visuali[sz]er|lyrics?|hd|hq|4k)(?:\s+video)?\s*[\)\]]",
    re.IGNORECASE)
_DASH = re.compile(r"\s+[-–—]\s+")


def parse_playlist_id(text: str) -> str:
    text = text.strip()
    m = re.search(r"[?&]list=([A-Za-z0-9_-]+)", text) or re.search(r"/browse/VL([A-Za-z0-9_-]+)", text)
    if m:
        pid = m.group(1)
    elif re.fullmatch(r"(?:PL|OLAK5uy_|UU|FL)[A-Za-z0-9_-]+", text):
        pid = text
    else:
        raise SourceError("That doesn't look like a YouTube Music playlist link.")
    if pid.startswith("RD"):
        raise SourceError("YouTube Mix playlists can't be read. Save the songs to a playlist of your own "
                          "and use that link.")
    if pid in ("LM", "LL", "WL"):
        raise SourceError("Liked Music and Watch Later are private and can't be read. Copy the songs to a "
                          "public or unlisted playlist and use that link.")
    return pid


def clean_video_title(title: str) -> str:
    return re.sub(r"\s{2,}", " ", _NOISE.sub("", title)).strip()


def split_youtube_title(video_title: str, channel: str) -> tuple[str, list[str]]:
    """(title, artists) from a video title and its channel name."""
    title = clean_video_title(video_title)
    channel = (channel or "").strip()
    if channel.endswith(" - Topic"):  # YouTube Music's auto-generated artist channels
        return title, [channel[: -len(" - Topic")].strip()]
    parts = _DASH.split(title, maxsplit=1)
    if len(parts) == 2 and parts[0] and parts[1]:
        return parts[1].strip(), [parts[0].strip()]
    artist = re.sub(r"\s*VEVO$", "", channel, flags=re.IGNORECASE).strip()
    return title, [artist or "Unknown Artist"]


class YouTubeMusicSource(Source):
    id = "youtube_music"
    name = "YouTube Music"
    icon = "youtube-music.svg"
    fields = [Field("api_key", "API key", secret=True, placeholder="AIza…",
                    help="A YouTube Data API v3 key from Google Cloud Console.")]
    help_url = "https://console.cloud.google.com/apis/library/youtube.googleapis.com"
    help_text = ("In Google Cloud Console, create a project, enable YouTube Data API v3, then create an API key "
                 "under APIs & Services → Credentials. It's free, and the daily limit covers hundreds of playlists.")
    link_example = "https://music.youtube.com/playlist?list=…"
    limits = "Only public and unlisted playlists can be read. YouTube Mixes and Liked Music can't."
    link_patterns = (r"(?:music\.|www\.|m\.)?youtube\.com/(?:playlist|watch|browse/VL)", r"youtu\.be/.*[?&]list=")

    def parse_link(self, text: str) -> str:
        return parse_playlist_id(text)

    # ---- API ---------------------------------------------------------------------------
    @staticmethod
    def _get(path: str, params: dict, creds: dict) -> dict:
        key = creds.get("api_key")
        if not key:
            raise CredentialError("Add your YouTube API key first.", fix="Enter a YouTube Data API v3 key.")
        try:
            return http.request_json("GET", f"{API}/{path}", params={**params, "key": key})
        except HttpError as e:
            raise _translate(e) from e

    def test(self, creds: dict) -> str:
        self._get("i18nLanguages", {"part": "snippet", "hl": "en"}, creds)
        return "YouTube accepted the API key."

    def get_playlist(self, link: str, creds: dict) -> Playlist:
        pid = parse_playlist_id(link)
        host = "music.youtube.com" if "music.youtube.com" in link or "/" not in link else "www.youtube.com"

        meta = self._get("playlists", {"part": "snippet", "id": pid, "maxResults": 1}, creds)
        if not meta.get("items"):
            raise SourceError("YouTube couldn't find that playlist. Only public and unlisted playlists can be read.")
        name = meta["items"][0].get("snippet", {}).get("title") or "YouTube playlist"

        tracks: list[SourceTrack] = []
        page_token = None
        while True:
            params = {"part": "snippet,contentDetails", "playlistId": pid, "maxResults": PAGE_SIZE}
            if page_token:
                params["pageToken"] = page_token
            page = self._get("playlistItems", params, creds)
            entries = [e for e in page.get("items") or [] if _is_playable(e)]
            durations = self._durations([_video_id(e) for e in entries], creds)
            for e in entries:
                vid = _video_id(e)
                snippet = e.get("snippet") or {}
                title, artists = split_youtube_title(snippet.get("title", ""), snippet.get("videoOwnerChannelTitle", ""))
                tracks.append(SourceTrack(id=vid, title=title, artists=artists, album="",
                                          duration=durations.get(vid, 0), url=f"https://{host}/watch?v={vid}"))
            page_token = page.get("nextPageToken")
            if not page_token:
                break
        return Playlist("youtube_music", pid, name, f"https://{host}/playlist?list={pid}", tracks)

    def _durations(self, video_ids: list[str], creds: dict) -> dict[str, int]:
        if not video_ids:
            return {}
        data = self._get("videos", {"part": "contentDetails", "id": ",".join(video_ids), "maxResults": PAGE_SIZE}, creds)
        return {v["id"]: parse_iso_duration((v.get("contentDetails") or {}).get("duration", ""))
                for v in data.get("items") or [] if v.get("id")}


def _video_id(entry: dict) -> str:
    return (entry.get("contentDetails") or {}).get("videoId") or \
        ((entry.get("snippet") or {}).get("resourceId") or {}).get("videoId", "")


def _is_playable(entry: dict) -> bool:
    """Deleted and private videos stay in playlists without an owner channel."""
    snippet = entry.get("snippet") or {}
    return bool(_video_id(entry)) and bool(snippet.get("videoOwnerChannelTitle"))


def _reasons(body: str) -> tuple[set[str], str]:
    try:
        err = json.loads(body).get("error") or {}
    except (ValueError, AttributeError):
        return set(), body
    reasons = {e.get("reason", "") for e in err.get("errors") or []}
    for detail in err.get("details") or []:
        reasons.add(detail.get("reason", ""))
    return reasons, err.get("message", "")


def _translate(e: HttpError) -> SourceError:
    if e.status == 0:
        return SourceError("Couldn't reach YouTube. Check your internet connection.")
    reasons, message = _reasons(e.body)
    text = f"{message} {' '.join(reasons)}".lower()
    if "api key not valid" in text or "keyinvalid" in text or "api_key_invalid" in text or "keyexpired" in text:
        return BAD_KEY
    if "accessnotconfigured" in text or "has not been used" in text or "service_disabled" in text:
        return NOT_ENABLED
    if "quotaexceeded" in text or "dailylimitexceeded" in text:
        return SourceError("YouTube's daily limit for this API key is used up. Try again tomorrow.")
    if e.status == 404 or "playlistnotfound" in text:
        return SourceError("YouTube couldn't find that playlist. Only public and unlisted playlists can be read.")
    if e.status == 403 and ("forbidden" in text or "playlistitemsnotaccessible" in text):
        return SourceError("That playlist is private. Make it public or unlisted in YouTube Music and try again.")
    if e.status in (400, 401, 403):
        return CredentialError(f"YouTube refused the request ({e.status}).",
                               fix="Check the API key in Google Cloud Console → APIs & Services → Credentials.")
    return SourceError(f"YouTube answered with an error ({e.status}). Try again in a minute.")
