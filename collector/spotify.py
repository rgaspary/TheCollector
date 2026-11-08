"""Spotify login (Authorization Code with PKCE) and playlist reading. Standard library only."""
import base64
import hashlib
import json
import re
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from .config import DATA_DIR, Config
from .matching import SpotifyTrack

AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
API = "https://api.spotify.com/v1"
SCOPES = "playlist-read-private playlist-read-collaborative"
TOKEN_FILE = DATA_DIR / "token.json"


class SpotifyError(Exception):
    pass


def parse_playlist_id(text: str) -> str:
    text = text.strip()
    m = re.search(r"playlist[/:]([A-Za-z0-9]{22})", text)
    if m:
        return m.group(1)
    if re.fullmatch(r"[A-Za-z0-9]{22}", text):
        return text
    raise SpotifyError("That doesn't look like a Spotify playlist link.")


@dataclass
class Playlist:
    id: str
    name: str
    url: str
    tracks: list[SpotifyTrack]


class SpotifyClient:
    def __init__(self, config: Config):
        self.config = config
        self._pending: dict[str, str] = {}  # state -> code_verifier
        self._token = self._load_token()

    # ---- login -------------------------------------------------------------------------
    @property
    def logged_in(self) -> bool:
        return bool(self._token.get("refresh_token") or self._token.get("access_token"))

    def login_url(self) -> str:
        if not self.config.legacy_spotify_client_id:
            raise SpotifyError("Add your Spotify Client ID to config.toml first.")
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        state = secrets.token_urlsafe(16)
        self._pending[state] = verifier
        return AUTH_URL + "?" + urllib.parse.urlencode({
            "client_id": self.config.legacy_spotify_client_id,
            "response_type": "code",
            "redirect_uri": self.config.redirect_uri,
            "code_challenge_method": "S256",
            "code_challenge": challenge,
            "scope": SCOPES,
            "state": state,
        })

    def finish_login(self, code: str, state: str):
        verifier = self._pending.pop(state, None)
        if not verifier:
            raise SpotifyError("Login expired or didn't start here. Try connecting again.")
        self._save_token(self._post_token({
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.config.redirect_uri,
            "client_id": self.config.legacy_spotify_client_id,
            "code_verifier": verifier,
        }))

    def logout(self):
        self._token = {}
        TOKEN_FILE.unlink(missing_ok=True)

    # ---- tokens ------------------------------------------------------------------------
    def _load_token(self) -> dict:
        try:
            return json.loads(TOKEN_FILE.read_text())
        except (OSError, ValueError):
            return {}

    def _save_token(self, data: dict):
        token = {
            "access_token": data["access_token"],
            "refresh_token": data.get("refresh_token") or self._token.get("refresh_token"),
            "expires_at": time.time() + int(data.get("expires_in", 3600)) - 60,
        }
        self._token = token
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        TOKEN_FILE.write_text(json.dumps(token))
        TOKEN_FILE.chmod(0o600)

    def _post_token(self, form: dict) -> dict:
        req = urllib.request.Request(
            TOKEN_URL, data=urllib.parse.urlencode(form).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            raise SpotifyError(f"Spotify login failed ({e.code}): {e.read().decode(errors='replace')[:200]}")

    def _access_token(self) -> str:
        if not self.logged_in:
            raise SpotifyError("Connect Spotify first.")
        if time.time() >= self._token.get("expires_at", 0):
            if not self._token.get("refresh_token"):
                raise SpotifyError("Spotify session expired. Connect again.")
            try:
                self._save_token(self._post_token({
                    "grant_type": "refresh_token",
                    "refresh_token": self._token["refresh_token"],
                    "client_id": self.config.legacy_spotify_client_id,
                }))
            except SpotifyError:
                self.logout()
                raise SpotifyError("Spotify session expired. Connect again.")
        return self._token["access_token"]

    # ---- API ---------------------------------------------------------------------------
    def _get(self, url: str) -> dict:
        if not url.startswith("http"):
            url = API + url
        for attempt in range(3):
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {self._access_token()}"})
            try:
                with urllib.request.urlopen(req, timeout=20) as resp:
                    return json.load(resp)
            except urllib.error.HTTPError as e:
                if e.code == 429 and attempt < 2:
                    time.sleep(min(int(e.headers.get("Retry-After", "2")), 10))
                    continue
                if e.code == 401:
                    self._token["expires_at"] = 0
                    if attempt < 2:
                        continue
                raise SpotifyError(f"HTTP {e.code}") from e
        raise SpotifyError("Spotify is rate limiting requests. Try again in a minute.")

    def get_playlist(self, link: str) -> Playlist:
        pid = parse_playlist_id(link)
        try:
            meta = self._get(f"/playlists/{pid}?fields=name,external_urls")
        except SpotifyError as e:
            if "404" in str(e):
                raise SpotifyError("Spotify couldn't find that playlist (it may be private or deleted).")
            raise

        items = None
        last_error = None
        # Newer API path first, then the older one.
        for path in (f"/playlists/{pid}/items?limit=50", f"/playlists/{pid}/tracks?limit=100"):
            try:
                items = self._all_items(path)
                break
            except SpotifyError as e:
                last_error = e
        if items is None:
            raise SpotifyError(
                f"Spotify wouldn't share this playlist's tracks ({last_error}). Apps in Spotify's "
                "development mode can usually only read playlists you own or collaborate on. "
                "Copy the tracks into a playlist of your own and try that link."
            )

        tracks = [t for entry in items if (t := _to_track(entry))]
        url = meta.get("external_urls", {}).get("spotify") or f"https://open.spotify.com/playlist/{pid}"
        return Playlist(pid, meta.get("name") or "Spotify playlist", url, tracks)

    def _all_items(self, path: str) -> list[dict]:
        out, url = [], path
        while url:
            page = self._get(url)
            out.extend(page.get("items", []))
            url = page.get("next")
        return out


def _to_track(entry: dict) -> SpotifyTrack | None:
    t = entry.get("item") or entry.get("track")
    if not t or t.get("type", "track") != "track":
        return None  # podcast episode or removed track
    artists = [a.get("name", "") for a in t.get("artists", []) if a.get("name")]
    tid = t.get("id") or ("local:" + (t.get("uri") or t.get("name", "")))
    return SpotifyTrack(
        id=tid,
        title=t.get("name", ""),
        artists=artists or ["Unknown Artist"],
        album=(t.get("album") or {}).get("name", ""),
        duration=round((t.get("duration_ms") or 0) / 1000),
        url=(t.get("external_urls") or {}).get("spotify", ""),
    )
