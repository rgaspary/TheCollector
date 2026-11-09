# TheCollector v2.0 Implementation Plan

Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn TheCollector into a multi-source, step-by-step app (v2.0.0) that runs on Linux, Windows and macOS, imports playlists from Spotify and YouTube Music, and matches them against the user's own library (Strawberry, iTunes/Apple Music, MediaMonkey, or a music folder). It exports the matched playlist in the right format for the user's player, and exports missing tracks in four formats.

**Architecture:** A `collector/sources/` package puts every service behind one `Source` interface, and `collector/libraries/` does the same for local libraries (all produce `LocalTrack` lists). A `CredentialStore` keeps per-source secrets and their status, and `collector/exporters/` holds one small writer per format. `web.py` gets source/credential/export routes, and the frontend becomes ES modules with a tiny screen router that runs the slide-and-fade transitions.

**Tech Stack:** Python 3.11+ standard library only (`urllib`, `json`, `xml.etree`, `plistlib`, `csv`, `hashlib`, `secrets`), `unittest`. Vanilla JS (ES modules) + CSS, no build step.

**Spec:** `docs/specs/2026-11-08-thecollector-v2-design.md`

## Global Constraints

- No third-party Python packages. If a task seems to need one, stop and ask.
- Version string `2.0.0` in `collector/__init__.py` as `__version__`.
- Credentials file: `DATA_DIR / "credentials.json"`, mode `0o600`, atomic write (temp file + `os.replace`).
- The API never returns a stored secret value. Secret fields come back as `{"set": true}`.
- Every network call goes through `collector/http.py` (one place to fake in tests). Timeout 20 s, retry 429 up to 2 times honouring `Retry-After` (max 10 s).
- Transition: 320 ms, `cubic-bezier(.2,.7,.2,1)`, `translateX(48px)` + opacity. Reduced motion: opacity only, 150 ms.
- Keep `/callback` as the Spotify redirect path (already registered by the user).
- Tests: `python3 -m unittest discover tests`. No test makes a real network call.
- Runs on Linux, Windows and macOS with Python 3.11+. Use `pathlib`, never hard-coded `/`, and branch on `sys.platform` only inside `collector/platform_paths.py`. Linux-only pieces (`window.py`, `collector-launch.sh`) stay optional.
- Personal settings live in `config.toml` (git-ignored). Default changes go in `config.example.toml`.
- User-facing text: plain, short, no jargon (matches the v1 UI voice).

## Review Focus

1. **Existing v1 notes and choices:** notes with `[Spotify](url)` links and `choices.json` keyed by bare Spotify IDs must keep working (no duplicate tasks, remembered picks still applied). Tests in Tasks 5 and 14.
2. **Credentials that go bad mid-flow** (token revoked between source pick and Analyze): `/api/analyze` must answer `{"code": "credentials"}` and the UI must land on the Fix screen, not a generic error. Tests in Tasks 4 and 17.
3. **Track names with commas, quotes, `&`, `<`, non-Latin script, and file paths with spaces/`#`** in every export format. Tests in Tasks 13 and 15.
4. **Playlist names that aren't safe file names** (`AC/DC: Best?`, empty, only dots): every writer uses `safe_filename`. Test in Task 13.
5. **No NextUp installed** (missing `[vault]` or the NextUp config file): app starts, missing-tracks export works, NextUp toggle hidden. Tests in Tasks 2 and 17.
6. **Library files in odd shapes:** iTunes XML with Windows `file://localhost/C:/…` locations, MediaMonkey paths without drive letters, music files with no tags or broken tags. Tests in Tasks 10, 11 and 12.

---

## Branches

Each feature has its own branch cut from `v2.0`. When a branch's tasks are done and its tests pass, open a pull request into `v2.0` and merge it. Merge in the order below: each branch builds on the ones above it. Before starting a branch, update it from `v2.0` (`git merge v2.0`) so it has everything merged so far. `v2.0` merges into `main` at release.

| # | Branch | Tasks | Delivers |
|---|---|---|---|
| 1 | `feature/foundation` | 1–5 | Config (optional NextUp, per-OS paths), track model, HTTP helper, source interface, credential store, Spotify as a source |
| 2 | `feature/streaming-sources` | 6 | YouTube Music (TIDAL, Qobuz and Apple Music file import postponed) |
| 3 | `feature/local-libraries` | 9–12 | Strawberry, iTunes / Apple Music, MediaMonkey, music folder readers |
| 4 | `feature/playlist-export` | 13 | Playlist formats and the per-player format table |
| 5 | `feature/missing-tracks-export` | 14–15 | Service-neutral NextUp note, JSON / CSV / Markdown / TXT export |
| 6 | `feature/server-api` | 16–17 | Library, source, credential, import, analyze and export routes |
| 7 | `feature/step-screens` | 18 | Screen router with slide and fade transitions |
| 8 | `feature/source-picker` | 19–20 | Library and source tiles with icons, credential set-up / fix / test |
| 9 | `feature/import-review-screens` | 21 | Link and review screens |
| 10 | `feature/export-screens` | 22 | Export, missing tracks and done screens |
| 11 | `release/v2.0-checks` | 23–24 | Player import check, docs, version 2.0.0 |

---

## File structure

```
collector/
  __init__.py            + __version__
  config.py              [vault] optional, [export] dir, [library] type/path/folders, Config.vault_* may be None
  platform_paths.py      NEW  per-OS data folder and default library paths
  http.py                NEW  request_json(), HttpError
  credentials.py         NEW  CredentialStore
  itunes_xml.py          NEW  Music/iTunes XML helpers (Task 10)
  tracks.py              NEW  SourceTrack (moved from matching.py), Playlist
  sources/
    __init__.py          NEW  REGISTRY, get_source()
    base.py              NEW  Field, Source, SourceError, CredentialError
    spotify.py           MOVED from collector/spotify.py, now a Source
    youtube_music.py     NEW
    (tidal.py, qobuz.py, apple_music.py postponed: Tasks 7–8)
  libraries/
    __init__.py          NEW  LIBRARIES, get_library()
    base.py              NEW  Library, LibraryError
    strawberry.py        MOVED from collector/library.py
    itunes.py            NEW  iTunes / Apple Music Library XML
    mediamonkey.py       NEW  MM.DB / MM5.DB
    folder.py            NEW  folder scan + cache
    tags.py              NEW  ID3, FLAC, MP4, Ogg, ASF tag readers
  exporters/
    __init__.py          NEW  PLAYLIST_FORMATS, MISSING_FORMATS
    players.py           NEW  PLAYERS: app → recommended format + import steps
    playlist_formats.py  NEW  m3u8/m3u/pls/xspf/itunes_xml/wpl/csv/json
    missing_formats.py   NEW  json/csv/md/txt
  matching.py            imports SourceTrack from tracks.py
  playlist.py            safe_filename + PathStyle helpers (write_m3u8 moves to exporters)
  vault.py               service label in links, accepts old [Spotify] lines
  choices.py             keys "<source>:<id>", reads bare Spotify IDs
  web.py                 new routes
static/
  index.html             screen containers, step bar, type="module"
  style.css              screens, tiles, transitions
  js/main.js api.js router.js state.js
  js/screens/library.js source.js credentials.js link.js import.js review.js export.js missing.js done.js
  icons/services/*.svg   official service icons + SOURCES.md
  icons/apps/*.svg       official player/library app icons (same SOURCES.md rules)
tests/
  test_collector.py      existing (updated imports)
  test_credentials.py test_http.py test_sources_*.py test_exporters.py test_web.py
  fixtures/<source>/*.json
  fixtures/libraries/    small iTunes XML, MediaMonkey DB, tagged audio files (a few KB each)
```

---

## Phase 0 — Preparation

### Task 1: Repo, version, API spike

**Files:**
- Create: `.gitignore` (`collector.log`, `__pycache__/`), `CHANGELOG.md`, `docs/notes/2026-11-api-spike.md`, `tests/fixtures/<source>/` (one recorded response per endpoint)
- Modify: `collector/__init__.py`

- [x] **Step 1:** Git repo and public GitHub repo exist (done 2026-11-08: `rgaspary/TheCollector`, MIT). Work happens on the feature branches in the Branches section; they merge into `v2.0`, which merges into `main` at release.
- [x] **Step 2:** Add `__version__ = "2.0.0-dev"` to `collector/__init__.py`. Add `CHANGELOG.md` with an `## 2.0.0 (unreleased)` heading.
> Steps 3a–4b (research with real accounts and library files) need the user's keys and sample files. YouTube Music was checked with a real key on 2026-11-08 (Task 6 note). Steps 3a and 3 for Apple Music, Qobuz and TIDAL are postponed with those sources. Step 4b is done at the start of `feature/local-libraries`.

- [ ] **Step 3a:** Apple Music: get a 3-track playlist exported as XML, plain text and Unicode text from the Mac Music app and from iTunes for Windows (from the user, or a VM). Save trimmed copies to `tests/fixtures/apple_music/` (strip `Location` paths and personal data). Record the text-export column names, encodings and the `Time` unit. Check whether the Apple Music app for Windows can export a playlist; record the answer for the import screen's Windows note.
- [ ] **Step 3:** For each of Qobuz, TIDAL, YouTube Music, use the user's test credentials (ask the user for them, never commit them) to call the endpoint in the spec table once with `curl`. Save each trimmed response as `tests/fixtures/<source>/playlist.json` (and page 2 where paging exists). Strip personal data.
- [ ] **Step 4:** Write `docs/notes/2026-11-api-spike.md`: per source, the confirmed URL, auth header, paging field, and the JSON paths for title/artists/album/duration/ISRC/url. If an endpoint differs from the spec table, update the spec table.
- [ ] **Step 4b:** Get a MediaMonkey 5 `MM5.DB` (from the user's Windows PC or a fresh install with 3 tracks added). Record the `Songs` and `Medias` columns and how drive letters are stored in the spike notes. Do the same for an iTunes `iTunes Library.xml` from Windows and a Music app `Library.xml` from macOS (3 tracks each). Don't commit personal libraries.
- [ ] **Step 5:** Commit: `chore: start v2.0, record API spike`.

---

## Phase 1 — Backend foundation

### Task 2: Config — optional vault, export folder, per-OS paths

**Files:** Create `collector/platform_paths.py`; Modify `collector/config.py`, `config.example.toml`; Test `tests/test_config.py`

**Interfaces:**
- Produces: `platform_paths.data_dir(platform: str = sys.platform) -> Path` (Linux `$XDG_DATA_HOME/thecollector` or `~/.local/share/thecollector`, Windows `%APPDATA%/TheCollector`, macOS `~/Library/Application Support/TheCollector`); `platform_paths.default_library_path(kind: str, platform: str = sys.platform) -> Path | None` with the defaults in the spec's library table; `config.DATA_DIR = platform_paths.data_dir()`. `Config.library_type: str` (default `"strawberry"`), `Config.library_path: Path | None`, `Config.library_folders: list[Path]`, `Config.playlist_dir: Path`, `Config.vault_path: Path | None`, `Config.vault_name: str | None`, `Config.notes_folder: str | None`, `Config.export_dir: Path`, `Config.nextup_enabled -> bool` (property), `Config.legacy_spotify_client_id: str` (from `[spotify] client_id` or env `SPOTIFY_CLIENT_ID`). `Config.client_id` is removed.

- [ ] **Step 1: Failing tests**

```python
def test_no_vault_section(self):      # write a temp config without [vault]
    cfg = config.load(path)
    self.assertFalse(cfg.nextup_enabled); self.assertIsNone(cfg.vault_path)
def test_missing_nextup_file(self):   # [vault] nextup_config points to a missing file
    self.assertFalse(config.load(path).nextup_enabled)
def test_export_dir_default(self):
    self.assertEqual(config.load(path).export_dir, Path.home() / "Music/TheCollector Exports")
def test_data_dir_per_platform(self):  # env patched: APPDATA=C:/Users/a/AppData/Roaming
    self.assertEqual(platform_paths.data_dir("win32"), Path("C:/Users/a/AppData/Roaming/TheCollector"))
    self.assertEqual(platform_paths.data_dir("darwin"), Path.home() / "Library/Application Support/TheCollector")
def test_v1_library_keys_still_read(self):  # [library] strawberry_db = "..." with no type
    cfg = config.load(path); self.assertEqual((cfg.library_type, cfg.library_path), ("strawberry", Path("/x/strawberry.db")))
```

- [ ] **Step 2:** Run `python3 -m unittest tests.test_config -v` → FAIL.
- [ ] **Step 3:** Implement in `config.load`. Add `[export]` and the new `[library]` keys to `config.example.toml` (the user's own `config.toml` keeps working through the v1-key fallback).
- [ ] **Step 4:** Run → PASS. Full suite still passes.
- [ ] **Step 5:** Commit `feat(config): optional NextUp vault, export folder, per-OS paths`.

### Task 3: Track model + HTTP helper

**Files:** Create `collector/tracks.py`, `collector/http.py`; Modify `collector/matching.py`, `collector/vault.py`, `tests/test_collector.py`; Test `tests/test_http.py`

**Interfaces:**
- Produces:
  - `@dataclass SourceTrack(id: str, title: str, artists: list[str], album: str, duration: int, url: str, isrc: str = "")` with `.artist` property. `matching.SpotifyTrack = SourceTrack` kept as an alias for one release.
  - `@dataclass Playlist(source: str, id: str, name: str, url: str, tracks: list[SourceTrack])`
  - `http.request_json(method: str, url: str, *, headers: dict | None = None, form: dict | None = None, json_body: dict | None = None, basic_auth: tuple[str, str] | None = None) -> dict`
  - `class HttpError(Exception)`: `.status: int`, `.body: str`, `.retry_after: int | None`
  - Module-level `http.opener` (defaults to `urllib.request.urlopen`) that tests replace.

- [ ] **Step 1: Failing tests** — `test_http.py`: `test_retries_429_then_succeeds` (fake opener raises 429 with `Retry-After: 0` then returns `{"ok":1}` → result `{"ok":1}`, 2 calls); `test_raises_http_error_with_status` (403 → `HttpError.status == 403`, `.body` holds the text); `test_basic_auth_header` (header equals `"Basic " + b64("id:secret")`).
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement. Move `SpotifyTrack` to `tracks.SourceTrack`, update imports in `matching.py`, `vault.py`, tests.
- [ ] **Step 4:** Run full suite → PASS.
- [ ] **Step 5:** Commit `refactor: SourceTrack model and shared HTTP helper`.

### Task 4: Source interface, registry, credential store

**Files:** Create `collector/sources/__init__.py`, `collector/sources/base.py`, `collector/credentials.py`; Test `tests/test_credentials.py`

**Interfaces:**
- Produces:
  - `@dataclass Field(key: str, label: str, secret: bool = False, help: str = "", placeholder: str = "", multiline: bool = False)`
  - `class SourceError(Exception)` (user-facing message); `class CredentialError(SourceError)` (with `.fix: str`, the how-to-fix text)
  - `class Source` (abstract): attributes `id: str`, `name: str`, `icon: str` (file name in `static/icons/services/`), `fields: list[Field]`, `help_url: str`, `help_text: str`, `link_example: str`, `uses_oauth: bool = False`, `limits: str = ""`, `input: Literal["link", "file"] = "link"`, and for file sources `file_types: list[str]`, `intro: str`, `export_steps: dict[str, list[str]]` (keys `"darwin"`, `"win32"`; the screen shows `"darwin"` on Linux). Methods `parse_link(text: str) -> str` (raises `SourceError`), `matches_link(text: str) -> bool`, `parse_file(filename: str, data: bytes) -> list[Playlist]` (file sources only; raises `SourceError`), `test(creds: dict) -> str` (returns an OK message or raises `CredentialError`), `get_playlist(link: str, creds: dict) -> Playlist`. OAuth sources also `login_url(creds, redirect_uri) -> str`, `finish_login(creds, code, state, redirect_uri) -> dict` (returns the creds to save).
  - `sources.REGISTRY: dict[str, Source]` in tile order: spotify, youtube_music (apple_music, tidal, qobuz follow when built). `sources.get_source(id) -> Source` (raises `KeyError`). `sources.detect(link) -> str | None`.
  - `CredentialStore(path: Path = DATA_DIR / "credentials.json")`: `get(source_id) -> dict`, `save(source_id, values: dict) -> None` (merges; empty string for a secret key keeps the old value), `status(source: Source) -> dict` → `{"state": "ready"|"needs_setup"|"invalid", "error": str, "fix": str}`, `mark_invalid(source_id, error: str, fix: str)`, `mark_ok(source_id)`, `public_view(source: Source) -> dict` (field key → `{"value": str}` for non-secret, `{"set": bool}` for secret), `clear(source_id)`.
  - `status()` is `needs_setup` when any required field is empty, or (for OAuth) no token stored. A source with no fields (Apple Music) is always `ready`.

- [ ] **Step 1: Failing tests**

```python
def test_file_mode_is_600(self): store.save("tidal", {"client_id": "a", "client_secret": "b"}); self.assertEqual(path.stat().st_mode & 0o777, 0o600)
def test_blank_secret_keeps_old(self): store.save("tidal", {"client_secret": ""}); self.assertEqual(store.get("tidal")["client_secret"], "b")
def test_public_view_hides_secrets(self): self.assertEqual(store.public_view(TIDAL)["client_secret"], {"set": True})
def test_status_cycle(self): needs_setup → save → ready → mark_invalid("401", "Copy it again") → invalid with error/fix → mark_ok → ready
def test_corrupt_file_is_empty_store(self): path.write_text("{"); self.assertEqual(CredentialStore(path).get("tidal"), {})
```

Use a fake `Source` subclass in the test for `TIDAL`.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat: source interface and credential store`.

### Task 5: Spotify as a Source + migration

**Files:** Move `collector/spotify.py` → `collector/sources/spotify.py`; Modify `collector/choices.py`; Test `tests/test_sources_spotify.py`, `tests/test_collector.py`

**Interfaces:**
- Consumes: `Source`, `CredentialStore`, `http.request_json`, `Playlist`.
- Produces: `SpotifySource(Source)` with `id="spotify"`, fields `[Field("client_id", "Client ID")]`, `uses_oauth=True`. Tokens live in the creds dict (`access_token`, `refresh_token`, `expires_at`). `migrate_v1(store: CredentialStore, cfg: Config) -> None` copies `cfg.legacy_spotify_client_id` and `DATA_DIR/"token.json"` into the store if the store has no Spotify entry. `Choices.get(source: str, track_id: str)` and `Choices.update(source: str, decisions: dict[str, str])` store `"<source>:<id>"` keys, and `get("spotify", x)` falls back to the bare key `x`.
- `_to_track` also reads `external_ids.isrc`.
- On refresh failure or 401 after retry, raise `CredentialError("Spotify sign-in expired.", fix="Click Connect to sign in again.")`.

- [ ] **Step 1: Failing tests:** existing `test_parse_playlist_id` moved; `test_to_track_reads_isrc`; `test_get_playlist_pages` (fake opener serving `fixtures/spotify/page1.json`, `page2.json` → track count = sum); `test_refresh_failure_raises_credential_error`; `test_migrate_v1_copies_client_id_and_token`; `test_choices_reads_bare_v1_key`.
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5:** Commit `refactor(spotify): Spotify as a Source, migrate v1 settings`.

---

## Phase 2 — New sources

Each task follows the same steps. Tests replace `http.opener` and serve the Task 1 fixtures.

**Shared test list per source** (`tests/test_sources_<id>.py`):
- `test_parse_link_variants` — every link form in the spec table → expected ID; a link from another service raises `SourceError`.
- `test_maps_fixture_to_tracks` — first track's `title`, `artists`, `album`, `duration`, `url` (and `isrc` where the service gives it) equal the fixture values.
- `test_paging` — two fixture pages → combined track count.
- `test_auth_refused_is_credential_error` — opener returns 401 → `CredentialError` with a non-empty `.fix`.
- `test_not_found_is_source_error` — 404 → `SourceError` (not `CredentialError`) naming the service.
- `test_test_returns_ok_message` — `test(creds)` against a fixture → string containing the service name.

Commit after each source: `feat(sources): <Service>`.

### Task 6: YouTube Music

> Built 2026-11-08 with sample responses written from YouTube's published API formats (`tests/fixtures/youtube_music/`). Checked the same day with a real key against a public 167-song playlist: the live responses have every field the samples use, so the samples stay. Title clean-up was widened for labels seen in real titles ("[HD UPGRADE]", "(4K Official Music Video)", "(Closed-Captioned)", quoted titles, trailing web addresses); `test_real_world_titles` pins them. Titles uploaded as "Song - Artist" can't be told apart from "Artist - Song" and are left to matching.

**Files:** Create `collector/sources/youtube_music.py`; Modify `collector/sources/base.py` (add `parse_iso_duration`); Test `tests/test_sources_youtube_music.py`

**Interfaces:**
- `YouTubeMusicSource`: fields `[Field("api_key", "API key", secret=True)]`. `test()` calls `playlistItems.list` on a known public playlist ID constant. Title parsing: `split_youtube_title(video_title: str, channel: str) -> tuple[str, list[str]]` — channel ending in `" - Topic"` → artist = channel minus suffix, title unchanged; otherwise split on the first `" - "`, `" – "` or `" — "`; strip `(Official Video)`, `(Official Audio)`, `[Official Music Video]`, `(Lyrics)`, `(Visualizer)`. Durations from `videos.list?part=contentDetails` (ISO 8601 `PT#M#S`) in batches of 50, parsed by `base.parse_iso_duration(value: str) -> int` (seconds; 0 if unreadable).
- Extra tests: `test_split_topic_channel` (`("Creep", "Radiohead - Topic") → ("Creep", ["Radiohead"])`), `test_split_dash_title` (`("Radiohead - Creep (Official Video)", "Radiohead") → ("Creep", ["Radiohead"])`), `test_iso_duration` (`"PT3M59S" → 239`).

### Task 7: TIDAL and Qobuz

> **Postponed 2026-11-08.** Not part of v2.0; kept here for when it's picked up (see the spec's Future features).

**Files:** Create `collector/sources/tidal.py`, `collector/sources/qobuz.py`; Tests alike.

**Interfaces:**
- `TidalSource`: fields `client_id`, `client_secret` (secret), `country` (non-secret, default `"US"`, used as `countryCode`). Client-credentials token at `https://auth.tidal.com/v1/oauth2/token` (HTTP Basic). The token is cached in creds (`access_token`, `expires_at`) and only fetched again when expired. Follows `links.next` for paging. Durations are ISO 8601. Durations use `base.parse_iso_duration` (Task 6).
- `QobuzSource`: fields `app_id`, `app_secret` (secret), `email`, `password` (secret). `test()` and the first `get_playlist` call `user/login`, store `user_auth_token` in creds and drop `password` (the caller saves the token, then calls `CredentialStore.remove("qobuz", ["password"])`, since `save` never overwrites with a blank). If the token is later refused and no password is stored → `CredentialError(fix="Enter your Qobuz password again to sign in.")`.
- Extra tests: `test_password_not_kept_after_login` (`"password" not in store.get("qobuz")` and token set); `test_token_is_reused_until_expiry` for TIDAL (two `get_playlist` calls → one token request).

### Task 8: Apple Music (file import)

> **Postponed 2026-11-08** with the `/api/import-file` route and the import screen (Tasks 17 and 21). `location_to_path` and `read_plist` move to Task 10, which needs them for the iTunes library reader. The rest is kept here for later.

**Files:** Create `collector/itunes_xml.py`, `collector/sources/apple_music.py`; Test `tests/test_itunes_xml.py`, `tests/test_sources_apple_music.py`

**Interfaces:**
- `itunes_xml` (also used by the iTunes library reader in Task 10):
  - `location_to_path(url: str) -> str` — `file:///Users/a/Music/x%20y.m4a` → `/Users/a/Music/x y.m4a`; `file://localhost/C:/Users/a/Music/x%20y.m4a` → `C:/Users/a/Music/x y.m4a` (pure string work, same result on any OS).
  - `read_plist(data: bytes) -> dict` — `plistlib.loads`; any error → `SourceError("This doesn't look like a playlist exported from Apple Music or iTunes.")`.
  - `playlists_from_plist(plist: dict) -> list[Playlist]` — one `Playlist` per entry in `Playlists` that has `Playlist Items`, skipping the `Master`/`Library` playlist and `Distinguished Kind` system playlists. Track order follows `Playlist Items`. `SourceTrack.id` = `Persistent ID`, `duration` = `Total Time` / 1000, `url` = `""`, artist falls back to `Album Artist`.
  - `parse_text_export(filename: str, data: bytes) -> Playlist` — tab-separated with a header row. Decoding: UTF-16 by BOM (Unicode text), UTF-8 with or without BOM, else cp1252 on Windows-style CRLF files, else mac_roman. Columns found by header name (`Name`, `Artist`, `Album`, `Time`, `Album Artist`), with the names Task 1 recorded. `Time` accepts seconds or `m:ss`. Playlist name = file name without extension. `SourceTrack.id` = `"txt:" + sha1(artist|title|album)[:16]`.
- `AppleMusicSource`: `id="apple_music"`, `name="Apple Music"`, `fields=[]`, `input="file"`, `file_types=[".xml", ".txt"]`, `intro="No API key needed. Export the playlist from Apple Music, then drop the file here."`, `export_steps` = the Mac and Windows steps in the spec's screen 2′, word for word. `parse_file` dispatches on content (`<?xml`/`<plist` → plist, else text). `.m3u`/`.m3u8` or content starting `#EXTM3U` → `SourceError("This file only lists downloaded songs. Export again with Format set to XML.")`. Zero tracks → `SourceError("That playlist is empty.")`. `parse_link` always raises `SourceError("Apple Music playlists are imported from a file. Choose Apple Music and follow the steps.")`; `matches_link` is true for `music.apple.com` so a pasted Apple link gets the `wrong_source` hint.
- Tests (`test_itunes_xml.py`, `test_sources_apple_music.py`): `test_location_mac`, `test_location_windows_localhost`, `test_plist_playlist_order` (fixture: tracks listed in a different order in `Tracks` than in `Playlist Items` → output follows `Playlist Items`), `test_plist_skips_library_and_system_playlists`, `test_library_export_returns_several_playlists`, `test_streaming_track_without_location_is_kept`, `test_text_export_utf16` and `test_text_export_plain` (Task 1 fixtures → same 3 tracks as the XML fixture), `test_time_m_ss`, `test_m3u_is_refused_with_hint`, `test_garbage_is_source_error`, `test_apple_link_detected_as_apple_music`.

---

## Phase 3 — Local libraries

Each library reader turns the user's music app into the same `list[LocalTrack]` that `matching.match_playlist` already takes. Tests use small fixture files in `tests/fixtures/libraries/` (build them in the test `setUp` where possible instead of committing binaries).

### Task 9: Library interface + Strawberry reader

**Files:** Create `collector/libraries/__init__.py`, `collector/libraries/base.py`; Move `collector/library.py` → `collector/libraries/strawberry.py`; Modify `collector/web.py` (use `get_library`), `tests/test_collector.py`; Test `tests/test_libraries.py`

**Interfaces:**
- Consumes: `platform_paths.default_library_path`, `Config.library_*`.
- Produces:
  - `LocalTrack` moves to `collector/tracks.py` (re-exported from `collector.libraries`).
  - `class LibraryError(Exception)` (user-facing message, with `.fix: str`).
  - `class Library` (abstract): `id: str`, `name: str`, `subtitle: str`, `icon: str` (file in `static/icons/apps/`), `needs: Literal["file", "folders"]`, `help_text: str`, `recommended_player: str` (key in `exporters.players.PLAYERS`, Task 13). Methods `detect() -> Path | None`, `load(path: Path | None, folders: list[Path]) -> list[LocalTrack]` (raises `LibraryError`), `test(path, folders) -> str` ("Found 12,345 tracks").
  - `LIBRARIES: dict[str, Library]` in tile order `strawberry, itunes, mediamonkey, folder`; `get_library(id) -> Library`.
- `StrawberryLibrary.load` is v1 `load_library`. A missing file → `LibraryError("Strawberry's library file wasn't found at <path>.", fix="Open Strawberry once so it creates its library, or pick the file yourself.")`.

- [ ] **Step 1: Failing tests:** v1 `test_url_to_path` moved; `test_strawberry_loads_fixture_db` (fixture DB created in `setUp` with the v1 `songs` columns, 2 rows, 1 `unavailable=1` → 1 track); `test_strawberry_missing_file_is_library_error`; `test_registry_order`.
- [ ] **Step 2–4:** FAIL → implement → PASS (full suite).
- [ ] **Step 5:** Commit `refactor(library): library interface, Strawberry reader`.

### Task 10: iTunes / Apple Music library reader

**Files:** Create `collector/libraries/itunes.py`; Test `tests/test_libraries.py`

**Interfaces:**
- Creates `collector/itunes_xml.py` with `location_to_path(url: str) -> str` and `read_plist(data: bytes) -> dict` exactly as described in Task 8 (Task 8 is postponed, so they're built here), plus `test_location_mac` and `test_location_windows_localhost` in `tests/test_itunes_xml.py`.
- Produces: `ItunesLibrary(Library)` with `id="itunes"`, `name="iTunes / Apple Music"`, `needs="file"`. Reads with `itunes_xml.read_plist` (wrapping its error as `LibraryError`); skips tracks without `Location`, with `Track Type` = `"URL"`/`"Remote"`, or with `Podcast`/`Movie`/`TV Show` true. Duration from `Total Time` (ms). Artist falls back to `Album Artist`.
- `help_text` explains how to get the XML on macOS (Music → Settings → Advanced → "Share Library XML with other applications", or File → Library → Export Library) and on Windows (iTunes → Edit → Preferences → Advanced → "Share iTunes Library XML with other applications").

- [ ] **Step 1: Failing tests:** `test_loads_fixture_plist` (fixture built with `plistlib.dumps` in `setUp`: 3 tracks — one local file, one Apple Music stream with no `Location`, one podcast → 1 track with title/artist/album/duration), `test_bad_xml_is_library_error`.
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5:** Commit `feat(library): iTunes / Apple Music library XML`.

### Task 11: MediaMonkey library reader

**Files:** Create `collector/libraries/mediamonkey.py`; Test `tests/test_libraries.py`

**Interfaces:**
- Produces: `MediaMonkeyLibrary(Library)` with `id="mediamonkey"`, `needs="file"`. `detect()` tries `%APPDATA%/MediaMonkey5/MM5.DB`, then `%APPDATA%/MediaMonkey/MM.DB`. `load` copies the DB to a temp folder (as Strawberry does), opens it with `sqlite3`, calls `con.create_collation("IUNICODE", casefold_compare)`, and reads `Songs` (`SongTitle`, `Artist`, `Album`, `SongLength` ms, `SongPath`, `IDMedia`). Paths stored without a drive letter (starting `:\`) get the drive from `Medias.DriveLetter` (A = 0 … Z = 25), joined on `IDMedia`.
- The exact column names and the drive-letter rule are checked against a real MM5.DB in Task 1's spike (the user's or a fresh MediaMonkey install on Windows). Fix this task's interface from those notes before starting it.

> Built 2026-11-08 from MediaMonkey's documented schema, without a real MM5.DB. The reader checks the tables and columns it uses, so a different layout gives a clear error instead of a crash. When a real MM5.DB is available, load it once and adjust the column names or the drive-letter rule if they differ.

- [ ] **Step 1: Failing tests:** `test_loads_fixture_db` (DB built in `setUp` with the `Songs`/`Medias` columns above, a column declared `COLLATE IUNICODE`, 2 songs) → paths `C:\Music\a.mp3` and `D:\b.flac`; `test_query_with_iunicode_column_works`; `test_missing_db_is_library_error`.
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5:** Commit `feat(library): MediaMonkey`.

### Task 12: Music folder scan + tag readers

**Files:** Create `collector/libraries/tags.py`, `collector/libraries/folder.py`; Test `tests/test_tags.py`, `tests/test_libraries.py`

**Interfaces:**
- Produces:
  - `@dataclass Tags(title: str = "", artist: str = "", album: str = "", album_artist: str = "", duration: int = 0)`
  - `tags.read_tags(path: Path) -> Tags` dispatching on file signature (not extension): ID3v2.2/2.3/2.4 (`TIT2`/`TPE1`/`TALB`/`TPE2`/`TLEN`, UTF-16 and Latin-1 frames, unsynchronisation) with ID3v1 fallback; MP3 duration from the Xing/Info header, else `TLEN`, else 0. FLAC `STREAMINFO` + `VORBIS_COMMENT`. MP4/M4A `moov/udta/meta/ilst` (`©nam`, `©ART`, `©alb`, `aART`) + `mvhd` duration. Ogg Vorbis/Opus comment header + last granule position. WMA/ASF Content Description + Extended Content Description (`WM/AlbumTitle`, `WM/AlbumArtist`) + File Properties duration. Unknown/broken → `Tags()`, never an exception.
  - `FolderLibrary(Library)` with `id="folder"`, `name="Music folder"`, `subtitle="Winamp, VLC, Windows Media Player, others"`, `needs="folders"`. Walks the folders for `.mp3 .m4a .m4b .aac .alac .flac .ogg .oga .opus .wma .wav .aif .aiff`, skipping hidden folders. A track with no title gets one from the path: `Artist/Album/NN - Title.ext` or `Artist - Title.ext`. Cache in `DATA_DIR / "folder-index.json"` keyed by path → `[size, mtime_ns, tags]`; only changed files are read again.
- Why no Winamp/WMP database readers: the spec's library section explains.

- [ ] **Step 1: Failing tests** (fixtures are built byte-by-byte in the tests, a few hundred bytes each): `test_id3v24_utf8`, `test_id3v23_utf16`, `test_id3v1_fallback`, `test_flac_tags_and_duration` (sample rate 44100, 441000 samples → 10 s), `test_mp4_tags_and_duration`, `test_ogg_vorbis_comments`, `test_asf_title_author`, `test_garbage_file_returns_empty_tags`, `test_title_from_path` (`Radiohead/OK Computer/02 - Paranoid Android.flac` with no tags → title `Paranoid Android`, artist `Radiohead`, album `OK Computer`), `test_cache_skips_unchanged_files` (second `load` reads 0 files; touching one reads 1).
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5:** Commit `feat(library): music folder scan with built-in tag readers`.

---

## Phase 4 — Exporters

### Task 13: Playlist formats

**Files:** Create `collector/exporters/__init__.py`, `collector/exporters/playlist_formats.py`, `collector/exporters/players.py`; Modify `collector/playlist.py` (keep `safe_filename`, remove `write_m3u8`); Test `tests/test_exporters.py`

**Interfaces:**
- Consumes: `LocalTrack`, `SourceTrack`, `Playlist`.
- Produces:
  - `PathStyle = Literal["absolute", "relative", "name"]`; `playlist.format_path(track_path: str, export_dir: Path, style: PathStyle) -> str` (relative uses `os.path.relpath`, forward slashes).
  - `@dataclass ExportItem(local: LocalTrack, source: SourceTrack)`
  - `PLAYLIST_FORMATS: dict[str, PlaylistFormat]` keys `m3u8, m3u, pls, xspf, itunes_xml, wpl, csv, json`. `PlaylistFormat(key, label, ext, write: Callable[[str, list[ExportItem], Path, PathStyle], str])` — `write` returns the file text, the caller writes the file.
  - `export_playlist(playlist: Playlist, items: list[ExportItem], formats: list[str], folder: Path, style: PathStyle) -> list[Path]` — file name `safe_filename(playlist.name) + ext`. For `itunes_xml` the ext is `.xml`, for `m3u` `.m3u`.
  - `players.PLAYERS: dict[str, Player]` with `Player(key, name, icon, platforms: set[str], recommended: str, also: list[str], steps: str)`, keys and values exactly as the spec's "Which format for which app" table: `itunes, apple_music, strawberry, vlc, mediamonkey, winamp, wmp, media_player, other`. `players.default_player(library_id: str, platform: str) -> str` (strawberry→strawberry, itunes→`apple_music` on darwin else `itunes`, mediamonkey→mediamonkey, folder→`other`).
  - Paths in M3U/M3U8/PLS/WPL use the running OS's separators (`str(Path)`); tests pass a `PureWindowsPath`-style path string to check backslashes survive.
- Rules: XSPF `<location>` is a `file://` URI (`Path.as_uri()` for absolute; percent-encoded relative path otherwise). iTunes XML via `plistlib` with `Location` as `file://` URI, `Track ID` ints from 1. WPL: `<?wpl version="1.0"?>`, `<smil><head><title>`, `<media src="…"/>`. CSV header `Title,Artist,Album,Duration,ISRC,Path,Source URL`. JSON: `{"format": "thecollector-playlist", "version": 1, "name", "source", "source_url", "tracks": [...]}`.

- [ ] **Step 1: Failing tests:** `test_m3u8_matches_v1_output` (same text v1 wrote for the existing test data); one `test_<format>_parses_back` per format (XSPF/WPL with `xml.etree`, iTunes with `plistlib.loads`, CSV with `csv.DictReader`, JSON with `json.loads`, PLS: `NumberOfEntries=2`, `File1=`); `test_special_characters` (title `Tom & "Jerry", <Live>`, artist `Björk`, path `/music/a #1/b c.flac` round-trip exactly in every format); `test_relative_paths`; `test_unsafe_playlist_name` (`"AC/DC: Best?"` → file `ACDC Best.m3u8`); `test_windows_paths_kept` (`C:\Music\a b.mp3` appears unchanged in M3U8/PLS/WPL and as `file:///C:/Music/a%20b.mp3` in XSPF/iTunes XML); `test_every_player_format_exists` (each `PLAYERS[*].recommended` and `also` is a `PLAYLIST_FORMATS` key); `test_default_player`.
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5:** Commit `feat(export): playlist formats`.

> Built 2026-11-09. Two changes from the interface above: `write` takes the `Playlist` (not just its name), because JSON needs the source and its URL; and iTunes XML always uses absolute locations, since iTunes and the Music app can't import relative ones. `playlist.path_to_uri` turns Windows or POSIX paths into `file://` URIs on any OS. The v1 `write_m3u8` is gone; `/api/build` writes through `export_playlist`.

### Task 14: NextUp note for any source

**Files:** Modify `collector/vault.py`; Test `tests/test_collector.py`

**Interfaces:**
- Produces: `task_line(t: SourceTrack, service: str) -> str` (link text `[<service>](url)`); `write_missing_note(vault, folder, area, playlist: Playlist, service: str, missing, found, today=None) -> NoteResult`. Intro line: `Tracks from [the <service> playlist](<url>) that aren't in your library yet.` `_line_key` matches `\[[^\]]+\]\((https?://[^)]+)\)` at the end of the line, so old `[Spotify]` lines still match.
- Tests: existing note tests updated; `test_v1_spotify_note_still_merges` (v1 note text + same tracks → `added == 0`); `test_youtube_label` (line ends with `[YouTube Music](https://…)`).
- [ ] Steps FAIL → implement → PASS → commit `feat(vault): service-neutral missing note`.

### Task 15: Missing-track formats

**Files:** Create `collector/exporters/missing_formats.py`; Test `tests/test_exporters.py`

**Interfaces:**
- Produces: `MISSING_FORMATS: dict[str, MissingFormat]` keys `json, csv, md, txt`; `export_missing(playlist: Playlist, missing: list[SourceTrack], fmt: str, folder: Path, today: date | None = None) -> Path` → `<safe name> missing tracks.<ext>`. Markdown task lines reuse `vault.task_line(track, service)` (Task 14), so the Markdown export and the NextUp note use the same line format.
- Tests: `test_md_is_checklist` (every track line starts with `- [ ] Get "`), `test_txt_one_line_per_track` (`"Radiohead - Creep"`), `test_csv_headers` (`Title,Artist,Album,Duration,ISRC,URL`), `test_json_shape` (keys `playlist, source, source_url, exported_at, tracks`), `test_special_characters` (same values as Task 13).
- [ ] Steps FAIL → implement → PASS → commit `feat(export): missing-track formats`.

---

## Phase 5 — Server API

### Task 16: Library, source and credential routes

**Files:** Modify `collector/web.py`; Test `tests/test_web.py` (start `serve()` on port 0 in a thread, call with `urllib`, fake sources via `REGISTRY` patching)

**Interfaces (JSON over HTTP; all POSTs keep the same-origin + JSON content-type check):**
- `GET /api/status` → `{version, platform, nextup_enabled, export_dir, playlist_dir, library: {id, name, path, folders, configured: bool}}`
- `GET /api/libraries` → `[{id, name, subtitle, icon, needs, help_text, detected_path}]`
- `POST /api/library/test` `{id, path?, folders?}` → `{ok, message}` or `{ok: false, error, fix}` (never saves)
- `POST /api/library` `{id, path?, folders?}` → writes `[library]` into `config.toml` (rewrite only that table, keep the rest of the file and its comments) → `{library}`
- `GET /api/players` → `PLAYERS` as JSON plus `default` from `default_player(library, platform)`
- `GET /api/sources` → `[{id, name, icon, help_url, help_text, link_example, limits, uses_oauth, fields:[{key,label,secret,help,placeholder,multiline}], values: public_view, status: {state, error, fix}}]`
- `POST /api/sources/<id>/credentials` `{values}` → saves → `{status}`
- `POST /api/sources/<id>/test` `{values?}` → tests `values` merged over stored creds **without saving** → `{ok: true, message}` or `{ok: false, error, fix}` (HTTP 200 both ways). On success with no `values`, `mark_ok`.
- `GET /login/spotify` → Spotify sign-in redirect; `GET /callback` → save tokens → redirect `/?connected=spotify`. Spotify is the only source with a browser sign-in.
- `POST /api/sources/<id>/disconnect` → clears tokens only.
- Tests: `test_library_save_keeps_other_config_lines`, `test_library_test_does_not_save`, `test_sources_never_leak_secrets` (response body doesn't contain the saved secret string), `test_test_does_not_save`, `test_cross_origin_post_refused` (Origin `http://evil.test` → 403), `test_unknown_source_404`.
- [ ] FAIL → implement → PASS → commit `feat(api): library, sources and credentials`.

### Task 17: Analyze, resolve, export routes

**Files:** Modify `collector/web.py`; Test `tests/test_web.py`

**Interfaces:**
- *(Postponed with Apple Music)* `POST /api/import-file` `{source, filename, data_b64}` (body limit 64 MB; larger → 413 `{error: "That file is too big. Export just the one playlist."}`) → calls `parse_file`, keeps the result in `App.imports` (same 10-entry limit as analyses) → `{import_id, playlists: [{index, name, count, preview: [{title, artist}] × 5}]}`.
- `POST /api/analyze` `{source, url}` (later also `{source, import_id, playlist_index}`) → v1 payload plus `playlist.source`, `playlist.service`. Loads the library with the configured reader. On `LibraryError`: 400 `{error, fix, code: "library"}`. On `CredentialError`: `mark_invalid` and HTTP 401 `{error, fix, code: "credentials", source}`. If `sources.detect(url)` names another source: 400 `{error, code: "wrong_source", detected}`.
- `POST /api/resolve` `{analysis_id, decisions}` → validates every close match is decided, saves choices, stores the result in the analysis → `{matched, missing}`.
- `POST /api/export/playlist` `{analysis_id, formats: [...], path_style, folder?}` → `{files: [path, ...]}`. `folder` defaults to `cfg.export_dir`; `m3u8` with no folder given still goes to `cfg.playlist_dir` (v1 behaviour for Strawberry).
- `POST /api/export/missing` `{analysis_id, format, nextup: bool}` → `{file, note_path, note_added, note_ticked, obsidian_url}`; `nextup` ignored when not enabled.
- `POST /api/reveal` `{path}` → opens the containing folder with `xdg-open` / `open` / `explorer` (by `sys.platform`). Only paths written in this server's lifetime are allowed (kept in `App.written: set[Path]`), else 403.
- `/api/build` removed.
- Tests: `test_analyze_credentials_error_shape`, `test_wrong_source_hint`, `test_resolve_requires_all_decisions`, `test_export_writes_selected_formats`, `test_reveal_refuses_unknown_path`.
- [ ] FAIL → implement → PASS → commit `feat(api): analyze, resolve and export routes`.

---

## Phase 6 — Frontend

No JS test runner exists, so each task ends with a manual check in the browser pane (`python3 -m collector --no-browser`, open `http://127.0.0.1:8766`). Use a fake source registered when `COLLECTOR_FAKE_SOURCES=1` (add in Task 18: `collector/sources/fake.py`, returns fixed tracks, credential test passes when `token == "ok"`) so screens can be checked without real accounts.

### Task 18: Screen shell, router, transitions

**Files:** Modify `static/index.html`, `static/style.css`; Create `static/js/main.js`, `static/js/router.js`, `static/js/api.js`, `static/js/state.js`, `collector/sources/fake.py`; Delete `static/app.js`

**Interfaces:**
- `router.js`: `register(name: string, {render(el, state), onEnter?(el, state)})`, `go(name: string, {direction: "forward"|"back"} = {direction: "forward"}) -> Promise<void>`, `back() -> Promise<void>` (keeps a history stack). Screens: `library, source, credentials, link, import, review, export, missing, done`. Start screen: `library` when `status.library.configured` is false, else `source`. While a transition runs, new `go()` calls queue rather than overlap.
- `api.js`: `get(url)`, `post(url, body)`; throws `ApiError` with `.status`, `.code`, `.data`.
- `state.js`: single object `{library, source, sourceInfo, link, importResult, analysis, decisions, exportResult, missingResult, returnTo}`.
- CSS: `.screen` absolutely stacked in `.stage`; classes `.enter-from-right`, `.enter-from-left`, `.exit-to-left`, `.exit-to-right`, `.active`, using the Global Constraints timing and a reduced-motion block. Step bar `<ol class="steps">` with `aria-current="step"`. After transition, focus the new screen's `h2` (`tabindex="-1"`).
- [ ] **Check:** with placeholder screens, Next/Back slide in the right direction with a fade; DevTools "Emulate prefers-reduced-motion" → fade only; fast double-click doesn't stack two screens; Tab focus lands on the heading.
- [ ] Commit `feat(ui): screen router with slide and fade`.

### Task 19: Library and source tiles, icons

**Files:** Create `static/js/screens/library.js`, `static/js/screens/source.js`, `static/icons/services/{spotify,youtube-music}.svg`, `static/icons/apps/{strawberry,itunes,apple-music,mediamonkey,vlc,winamp,wmp,media-player,folder}.svg`, `static/icons/services/SOURCES.md`

- [ ] **Step 1:** Get each service and app icon from its official brand/press kit or the app's own source/repo (ask the user before downloading; record URL, date, and brand-guideline notes in `SOURCES.md`). `folder.svg` is a plain folder glyph drawn for this app (ask the user before downloading; record URL, date, and brand-guideline notes in `SOURCES.md`). Use the single-colour or full-colour mark as each guideline requires; don't recolour or crop.
- [ ] **Step 2:** `source.js` renders `GET /api/sources` as a grid of `<button class="tile">` elements (icon 48 px, name below, badge "Set up" for `needs_setup`, "Needs attention" for `invalid`). Keyboard: arrow keys move between tiles. Click → `state.source = id`; not `ready` → `go("credentials")`; `ready` → `go(input === "file" ? "import" : "link")`.
- [ ] **Step 3:** `library.js`: tiles from `GET /api/libraries` (icon, name, subtitle). Picking one shows its `help_text`, a path field prefilled with `detected_path` (or a folder list with **Add folder** for `needs="folders"`), **Test** ("Found N tracks" or error + fix) and **Save & continue** → `go("source")`. Header shows "Library: <name> · Change" on every screen; **Change** → `go("library", {direction: "back"})`.
- [ ] **Check:** 2 source tiles in REGISTRY order and 4 library tiles, labels under icons, badges right for fake states, works in light and dark mode and at 375 px width. First run (no `[library] type`) opens on the library screen; a `LibraryError` during Analyze lands on it with the message.
- [ ] Commit `feat(ui): library and source picker tiles`.

### Task 20: Credentials set-up and fix sub-steps

**Files:** Create `static/js/screens/credentials.js`

- [ ] **Step 1:** One screen with two modes from `sourceInfo.status.state`: `needs_setup` → heading "Set up <Service>"; `invalid` → heading "Fix <Service> connection" plus a red box with `status.error` and `status.fix`. Fields from `fields` (secret → `type=password`, placeholder "Saved" when `values[key].set`; multiline → `<textarea>`). Help text + "Where to get these" link (`help_url`). `limits` shown as a muted note.
- [ ] **Step 2:** Buttons: **Test** (optional; calls `/test` with the typed values, shows a green "✓ <message>" or the red error + fix inline, never blocks), **Save & continue** (saves; for OAuth sources it then shows **Connect**, which opens `/login/<id>` in the browser and polls `/api/sources` every 2 s until `ready`). After success: `go(state.returnTo || "link")`.
- [ ] **Step 3:** In `main.js`, any `ApiError` with `code === "credentials"` sets `state.returnTo` to the current screen, refreshes the source status, and calls `go("credentials", {direction: "back"})`.
- [ ] **Check (fake source):** blank store → set-up screen; Test with `token=bad` shows error and fix; Test with `ok` shows ✓; Save → link screen; set the fake source to fail on analyze → lands on the Fix screen with the message, Save & try again returns to the link screen with the link still filled in.
- [ ] Commit `feat(ui): credential set-up, fix and test`.

### Task 21: Link, file import and review screens

**Files:** Create `static/js/screens/link.js`, `static/js/screens/import.js`, `static/js/screens/review.js`

- [ ] **Step 1:** `link.js`: source icon + name, input with `link_example` as placeholder, **Analyze** with "Analyzing…" state. `wrong_source` error → message with a **Switch to <Service>** button.
- [ ] **Step 1b (postponed with Apple Music):** `import.js`: the source's `intro` as one short line; Mac / Windows tabs with `export_steps` as a numbered list, opening on the tab for `status.platform` (Mac on Linux); a drop zone (`dragover`/`drop`) plus **Choose file…** (`<input type=file accept=".xml,.txt">`). Read with `FileReader.readAsArrayBuffer`, base64 it, `POST /api/import-file`. One playlist → show "**<name>** · N tracks", the 5-track preview, **Use a different file** and **Continue**. Several → a list to pick one first. Errors appear under the drop zone with the server's message. **Continue** → `POST /api/analyze` with `import_id` → `go("review")`.
- [ ] **Step 2:** `review.js`: port `renderResults`/`updateBuild` from v1 `app.js` (chips, close-match radios, bulk buttons, details lists). "Open in <Service>" link. **Continue** posts `/api/resolve`, then goes to `export`, or to `missing` when `matched == 0`, or to `done` when both are empty.
- [ ] **Check:** full fake run to review; remembered choices pre-selected; Continue disabled until all decided. (Later, with Apple Music: drop the XML fixture → preview shows 3 tracks → Continue → review; drop the text fixture → same; drop an `.m3u8` → the "Export again with Format set to XML" message; keyboard-only (Tab to **Choose file…**, Enter) works.)
- [ ] Commit `feat(ui): link, file import and review screens`.

### Task 22: Export, missing and done screens

**Files:** Create `static/js/screens/export.js`, `static/js/screens/missing.js`, `static/js/screens/done.js`

- [ ] **Step 1:** `export.js`: "Which app will you open this in?" tiles from `GET /api/players` (only players whose `platforms` include `status.platform`, plus Other), preselected with `default` or the last pick from `localStorage`. Picking one ticks its `recommended` format and shows its `steps`. "Show all formats" reveals every format as a checkbox. Path-style radios, folder text field (default from status), **Export** and **Skip**.
- [ ] **Step 2:** `missing.js`: count + preview of the first 5 missing tracks, radio cards JSON / CSV / Markdown / TXT (each with a one-line "good for" hint), "Also update my NextUp note" checkbox only when `nextup_enabled`, **Export** and **Skip**.
- [ ] **Step 3:** `done.js`: list of written files with **Open folder** (`/api/reveal`), NextUp note summary + **Open in Obsidian**, **Start over** (`go("source")`, clears state except source).
- [ ] **Check:** written files open in VLC (m3u8, pls, xspf), and the CSV opens in LibreOffice; the `.md` renders as a checklist in Obsidian. The player tiles show only players for this OS.
- [ ] Commit `feat(ui): export and done screens`.

### Task 23: Player import check (Linux, Windows, macOS)

**Files:** Create `docs/compatibility.md`; Modify `collector/exporters/players.py` and the spec table only if a row fails

- [ ] **Step 1:** Export one 3-track playlist (one title with `&` and `"`, one non-Latin artist, one path with spaces) in every format, on each OS, from that OS's own library type.
- [ ] **Step 2:** Import each app's recommended format with the steps shown on screen, and note whether all 3 tracks load:
  - Linux (here): Strawberry, VLC.
  - Windows (user or a Windows VM): iTunes, MediaMonkey, Winamp, VLC, Windows Media Player (Legacy), Media Player (Windows 11).
  - macOS (user or a Mac): Apple Music, VLC.
- [ ] **Step 3:** Write the results table in `docs/compatibility.md` (app, version, OS, format, result, date). For any failure, switch that app's `recommended` to a format that passed, update the spec table, re-run `tests.test_exporters`.
- [ ] **Step 4:** Commit `docs: player compatibility results`.

---

## Phase 7 — Release

### Task 24: Docs, version, final check

**Files:** Modify `README.md`, `CHANGELOG.md`, `collector/__init__.py`, `static/index.html` (version in footer), `collector-launch.sh` (no change expected; verify)

- [ ] **Step 1:** README: install and run on Linux, Windows and macOS (`python -m collector`), library choices, sources table with set-up links, the new flow, "which format for which app" table (link `docs/compatibility.md`), credentials file location per OS, v1→v2 migration notes.
- [ ] **Step 2:** CHANGELOG `## 2.0.0 — <date>`: Added / Changed / Removed (`/api/build`, `config.toml [spotify] client_id` now only used for migration).
- [ ] **Step 3:** `__version__ = "2.0.0"`.
- [ ] **Step 4:** Run `python3 -m unittest discover tests` → all pass (also on Windows and macOS if available). Run the app from the launcher with the real v1 data directory copied to a temp `XDG_DATA_HOME`. Spotify playlist end-to-end with the existing note: no duplicate tasks.
- [ ] **Step 5:** Commit `release: v2.0.0` and tag `v2.0.0`.

---

## Decisions log

- 2026-11-08: TIDAL, Qobuz and the Apple Music file import postponed to after v2.0. v2.0 ships with Spotify and YouTube Music. The iTunes / Apple Music *library* reader (Task 10) stays.

- 2026-11-08: SoundCloud moved to Future features (see the spec). Registering an app needs an Artist Pro plan.

- 2026-11-08: Apple Music uses file import (exported XML or text), so no API, developer account or token signing is needed.
- 2026-11-08: Amazon Music removed from v2.0. It has no playlist export and its API is invite-only, so users would need a third-party (sometimes paid) export tool.
- 2026-11-08: Libraries beyond Strawberry (iTunes/Apple Music, MediaMonkey, music folder) and per-player export formats are in scope.
