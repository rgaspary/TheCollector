"""Spotify: sign-in (Authorization Code with PKCE) and playlist reading."""
import base64
import hashlib
import json
import re
import secrets
import time
import urllib.parse
from pathlib import Path

from .. import http
from ..config import DATA_DIR, Config
from ..http import HttpError
from ..tracks import Playlist, SourceTrack
from .base import CredentialError, Field, Source, SourceError

AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
API = "https://api.spotify.com/v1"
SCOPES = "playlist-read-private playlist-read-collaborative"
V1_TOKEN_FILE = DATA_DIR / "token.json"

EXPIRED = CredentialError("Spotify sign-in expired.", fix="Click Connect to sign in to Spotify again.")


def parse_playlist_id(text: str) -> str:
    text = text.strip()
    m = re.search(r"playlist[/:]([A-Za-z0-9]{22})", text)
    if m:
        return m.group(1)
    if re.fullmatch(r"[A-Za-z0-9]{22}", text):
        return text
    raise SourceError("That doesn't look like a Spotify playlist link.")


class SpotifySource(Source):
    id = "spotify"
    name = "Spotify"
    icon = "spotify.svg"
    fields = [Field("client_id", "Client ID", help="From your app at developer.spotify.com/dashboard.",
                    placeholder="32 letters and numbers")]
    help_url = "https://developer.spotify.com/dashboard"
    help_text = ("Create an app in Spotify's developer dashboard, add TheCollector's Redirect URI to its "
                 "settings, then copy the app's Client ID here.")
    link_example = "https://open.spotify.com/playlist/…"
    limits = ("Apps in Spotify's development mode can usually only read playlists you own or follow. "
              "If a playlist is refused, save a copy to your own account and use that link.")
    setup_steps = [
        "Open https://developer.spotify.com/dashboard and log in with your Spotify account. The first time, "
        "accept the developer terms.",
        "Click Create app. Any name and description work, for example \"TheCollector\".",
        "Under Redirect URIs, add {redirect_uri} exactly as shown, then click Add.",
        "Under \"Which API/SDKs are you planning to use?\", tick Web API. Accept the terms and click Save.",
        "Open the app's Settings and copy its Client ID. TheCollector doesn't need the Client secret.",
        "In TheCollector, open Settings → Spotify → Set up, paste the Client ID and click Save. Then click "
        "Connect and sign in to Spotify in the tab that opens.",
    ]
    setup_notes = [
        "Your app stays in development mode, which is fine for personal use. Only you can sign in, unless you "
        "add other people under the app's User Management.",
        "Spotify doesn't let new apps read its own playlists, like Today's Top Hits or Discover Weekly. Add the "
        "songs to a playlist of your own and use that link.",
        "If you change TheCollector's port in config.toml, change the Redirect URI in the dashboard to match.",
    ]
    uses_oauth = True
    link_patterns = (r"open\.spotify\.com/(?:[\w-]+/)?playlist/", r"spotify:playlist:")

    def __init__(self):
        self._pending: dict[str, str] = {}  # login state -> PKCE code verifier

    def parse_link(self, text: str) -> str:
        return parse_playlist_id(text)

    # ---- sign-in -----------------------------------------------------------------------
    def login_url(self, creds: dict, redirect_uri: str) -> str:
        client_id = creds.get("client_id")
        if not client_id:
            raise CredentialError("Add your Spotify Client ID first.", fix="Enter the Client ID from your Spotify app.")
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        state = secrets.token_urlsafe(16)
        self._pending[state] = verifier
        return AUTH_URL + "?" + urllib.parse.urlencode({
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "code_challenge_method": "S256",
            "code_challenge": challenge,
            "scope": SCOPES,
            "state": state,
        })

    def finish_login(self, creds: dict, code: str, state: str, redirect_uri: str) -> dict:
        verifier = self._pending.pop(state, None)
        if not verifier:
            raise SourceError("Login expired or didn't start here. Try connecting again.")
        data = self._post_token({
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": creds.get("client_id", ""),
            "code_verifier": verifier,
        })
        return self._token_values(data, creds)

    # ---- tokens ------------------------------------------------------------------------
    @staticmethod
    def _token_values(data: dict, creds: dict) -> dict:
        return {
            "access_token": data["access_token"],
            "refresh_token": data.get("refresh_token") or creds.get("refresh_token", ""),
            "expires_at": time.time() + int(data.get("expires_in", 3600)) - 60,
        }

    @staticmethod
    def _post_token(form: dict) -> dict:
        try:
            return http.request_json("POST", TOKEN_URL, form=form)
        except HttpError as e:
            if e.status == 0:
                raise SourceError("Couldn't reach Spotify. Check your internet connection.") from e
            if "invalid_client" in e.body:
                raise CredentialError("Spotify didn't accept the Client ID.",
                                      fix="Copy the Client ID again from your app at developer.spotify.com/dashboard.") from e
            raise CredentialError(f"Spotify sign-in failed ({e.status}).",
                                  fix="Click Connect to sign in to Spotify again.") from e

    def _access_token(self, creds: dict) -> str:
        if not self.has_token(creds):
            raise CredentialError("Spotify isn't connected yet.", fix="Click Connect and sign in to Spotify.")
        if time.time() >= float(creds.get("expires_at") or 0) or not creds.get("access_token"):
            if not creds.get("refresh_token"):
                raise EXPIRED
            try:
                creds.update(self._token_values(self._post_token({
                    "grant_type": "refresh_token",
                    "refresh_token": creds["refresh_token"],
                    "client_id": creds.get("client_id", ""),
                }), creds))
            except CredentialError:
                raise EXPIRED from None
        return creds["access_token"]

    # ---- API ---------------------------------------------------------------------------
    def _get(self, url: str, creds: dict) -> dict:
        if not url.startswith("http"):
            url = API + url
        for attempt in range(2):
            try:
                return http.request_json("GET", url, headers={"Authorization": f"Bearer {self._access_token(creds)}"})
            except HttpError as e:
                if e.status == 401:
                    if attempt == 0:
                        creds["expires_at"] = 0  # refresh and try once more
                        continue
                    raise EXPIRED from e
                if e.status == 0:
                    raise SourceError("Couldn't reach Spotify. Check your internet connection.") from e
                raise
        raise EXPIRED

    def test(self, creds: dict) -> str:
        if not creds.get("client_id"):
            raise CredentialError("Add your Spotify Client ID first.", fix="Enter the Client ID from your Spotify app.")
        try:
            me = self._get("/me", creds)
        except HttpError as e:
            raise CredentialError(f"Spotify answered with an error ({e.status}).",
                                  fix="Click Connect to sign in to Spotify again.") from e
        return f"Connected to Spotify as {me.get('display_name') or me.get('id') or 'you'}."

    def get_playlist(self, link: str, creds: dict) -> Playlist:
        pid = parse_playlist_id(link)
        try:
            meta = self._get(f"/playlists/{pid}?fields=name,external_urls", creds)
        except HttpError as e:
            if e.status == 404:
                raise SourceError("Spotify couldn't find that playlist (it may be private or deleted).") from e
            raise SourceError(f"Spotify wouldn't open that playlist ({e.status}).") from e

        items, last_error = None, None
        # Newer API path first, then the older one.
        for path in (f"/playlists/{pid}/items?limit=50", f"/playlists/{pid}/tracks?limit=100"):
            try:
                items = self._all_items(path, creds)
                break
            except HttpError as e:
                last_error = e
        if items is None:
            raise SourceError(
                f"Spotify wouldn't share this playlist's tracks ({last_error}). Apps in Spotify's "
                "development mode can usually only read playlists you own or collaborate on. "
                "Copy the tracks into a playlist of your own and try that link."
            )

        tracks = [t for entry in items if (t := _to_track(entry))]
        url = meta.get("external_urls", {}).get("spotify") or f"https://open.spotify.com/playlist/{pid}"
        return Playlist("spotify", pid, meta.get("name") or "Spotify playlist", url, tracks)

    def _all_items(self, path: str, creds: dict) -> list[dict]:
        out, url = [], path
        while url:
            page = self._get(url, creds)
            out.extend(page.get("items") or [])
            url = page.get("next")
        return out


def _to_track(entry: dict) -> SourceTrack | None:
    t = entry.get("item") or entry.get("track")
    if not t or t.get("type", "track") != "track":
        return None  # podcast episode or removed track
    artists = [a.get("name", "") for a in t.get("artists", []) if a.get("name")]
    tid = t.get("id") or ("local:" + (t.get("uri") or t.get("name", "")))
    return SourceTrack(
        id=tid,
        title=t.get("name", ""),
        artists=artists or ["Unknown Artist"],
        album=(t.get("album") or {}).get("name", ""),
        duration=round((t.get("duration_ms") or 0) / 1000),
        url=(t.get("external_urls") or {}).get("spotify", ""),
        isrc=(t.get("external_ids") or {}).get("isrc", ""),
    )


def migrate_v1(store, cfg: Config, token_file: Path = V1_TOKEN_FILE) -> None:
    """Copy v1's Client ID (config.toml) and login (token.json) into the credential store, once."""
    if store.get("spotify"):
        return
    values = {}
    if cfg.legacy_spotify_client_id:
        values["client_id"] = cfg.legacy_spotify_client_id
    try:
        token = json.loads(token_file.read_text())
        values.update({k: token[k] for k in ("access_token", "refresh_token", "expires_at") if token.get(k)})
    except (OSError, ValueError, AttributeError):
        pass
    if values:
        store.save("spotify", values)
