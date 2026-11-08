# TheCollector v2.0 — Design

Status: draft for review · 2026-11-08

## What changes

| # | Request | v2.0 answer |
|---|---|---|
| 1 | More sources | Apple Music, Qobuz, Amazon Music, SoundCloud, TIDAL, YouTube Music, next to Spotify |
| 2 | Playlist export | M3U8, M3U, PLS, XSPF (the XML option), iTunes/Music XML, WPL, CSV, JSON |
| 3 | Missing-tracks export for people without NextUp | User picks JSON, CSV, Markdown or TXT. The NextUp note becomes optional |
| 4 | Step-by-step screens | One screen per step, sliding left to right with a fade |
| 5 | Source picker + credentials | Tiles with official icons; setup sub-step, fix sub-step, optional **Test** button; credentials saved for next time |

Version: `2.0.0` (breaking: config layout, API routes, missing-note link label).

## What stays

- Python 3.11+ standard library only, no pip installs. Vanilla JS/CSS frontend, no build step.
- Strawberry is still the local library that tracks are matched against (`library.py`, `matching.py` unchanged apart from the track type rename).
- Local server on `127.0.0.1:8766`, GTK window, launcher script.

## Sources

Every source implements one interface (`collector/sources/base.py`). What each needs from the user:

| Source | Link it accepts | What the user provides | How the app reads the playlist | Limits to tell the user |
|---|---|---|---|---|
| Spotify | `open.spotify.com/playlist/…`, `spotify:playlist:…` | Client ID, then **Connect** (browser sign-in, PKCE) | Web API `/playlists/{id}/items` | Dev-mode apps may only read playlists the user owns or follows |
| Apple Music | `music.apple.com/…/playlist/…/pl.…` | Team ID, Key ID, MusicKit private key (`.p8`) | App signs an ES256 developer token; catalog API `/v1/catalog/{storefront}/playlists/{id}` | Needs a paid Apple Developer account. Shared/public playlists only in v2.0 (personal library needs a MusicKit JS sign-in, deferred) |
| Qobuz | `open.qobuz.com/playlist/…`, `play.qobuz.com/playlist/…`, `qobuz.com/…/playlists/…/<id>` | App ID, App secret, email, password | `user/login` → user token (password is **not** stored, only the token); `playlist/get?extra=tracks` | App ID/secret come from Qobuz on request (api@qobuz.com) |
| Amazon Music | `music.amazon.*/playlists/…`, `…/user-playlists/…` | Security Profile client ID + secret, API key, then **Connect** (Login with Amazon) | Amazon Music Web API v2 (`api.music.amazon.com`) | API is closed beta: only works for developers Amazon has approved. The tile says so |
| SoundCloud | `soundcloud.com/<user>/sets/<name>`, `on.soundcloud.com/…` | Client ID, Client secret | Client-credentials token (HTTP Basic), `/resolve?url=` then the playlist's tracks | Registering an app needs an Artist Pro plan. Token issuance is rate-limited (50/12 h), so the token is cached |
| TIDAL | `tidal.com/(browse/)playlist/<uuid>`, `listen.tidal.com/playlist/<uuid>` | Client ID, Client secret | Client-credentials token; `openapi.tidal.com/v2/playlists/{id}/relationships/items?include=items` | Public playlists only in v2.0 |
| YouTube Music | `music.youtube.com/playlist?list=…`, `youtube.com/playlist?list=…` | YouTube Data API v3 key | `playlistItems.list` + `videos.list` (durations) | Public/unlisted playlists only. Titles like "Artist - Song" and "Artist - Topic" channels are parsed into artist/title |

The Task 1 spike confirms each endpoint before any source is built; the plan updates this table with what it finds.

## Credentials

- Stored in `~/.local/share/thecollector/credentials.json`, mode `0600`, written atomically. Same place and protection as today's `token.json`.
- The browser never gets a stored secret back. The API returns which fields are set; secret fields show as "saved" placeholders. A blank secret field on save means "keep the saved one".
- Each source has a status: `ready`, `needs_setup` (nothing stored), or `invalid` (stored but the last call was refused, with the reason).
- `invalid` is set when a test fails or any API call answers 401/403 for auth reasons. A later successful test or fetch clears it.
- Spotify's `client_id` moves from `config.toml` into the store on first v2 start. The config key is still read as a fallback.

## Screens and flow

```
1 Source ──► 1a Set up credentials ─┐
   │         1b Fix credentials ────┤ (only when needed)
   ▼                                ▼
2 Playlist link ──► 3 Review matches ──► 4 Export playlist ──► 5 Missing tracks ──► 6 Done
```

- **1 Source:** grid of tiles, each with the service's official icon and its name underneath. A small badge on the tile shows "Set up" or "Needs attention".
- **1a Set up:** "Where to get these" help with a link to the service's developer page, the fields, an optional **Test** button that reports OK or the exact error, and **Save & continue**. OAuth sources (Spotify, Amazon) add a **Connect** button after the fields are saved.
- **1b Fix:** like 1a, plus a red box saying what went wrong (the service's message) and how to fix it (per-source text, e.g. "Your TIDAL client secret was rejected. Copy it again from developer.tidal.com → Dashboard"). Fields come prefilled, secrets show as saved. **Save & try again** goes back to where the user was (source pick or analyze).
- **2 Link:** paste field with the chosen service's example link, **Analyze**, progress state. A link from the wrong service gets a hint ("That's a Spotify link — switch source?").
- **3 Review:** today's results card (chips, close-match choices, bulk buttons). **Continue** is enabled once every close match is decided.
- **4 Export playlist:** checkboxes for formats (M3U8 pre-ticked), a path-style choice (absolute / relative to the export folder / file name only), the folder, and **Export**. Skippable when nothing matched.
- **5 Missing tracks:** pick one of JSON, CSV, Markdown, TXT, plus an "Also update my NextUp note" toggle (shown only when NextUp is configured). Skipped automatically when nothing is missing.
- **6 Done:** what was written where, **Open folder**, **Open note in Obsidian** (if used), **Start over**.
- A step bar at the top; **Back** on every screen after 1. Going back keeps answers.

### Motion

- Forward: the current screen slides out to the left and fades out while the next one slides in from the right and fades in. Back is the mirror image. 320 ms, `cubic-bezier(.2,.7,.2,1)`, `translateX(±48px)` + opacity 0→1.
- `prefers-reduced-motion: reduce` → fade only, 150 ms.
- Focus moves to the new screen's heading after each transition (keyboard and screen-reader users).

## Export formats

Playlist export writes the matched **local** files. The formats were picked to load in common desktop players on Windows, macOS and Linux:

| Format | Ext | Opens in | Notes |
|---|---|---|---|
| Extended M3U, UTF-8 | `.m3u8` | Strawberry, VLC, foobar2000, MusicBee, Winamp, Audacious, Rhythmbox, Clementine, mpv, Apple Music (Mac) | Default, unchanged from v1 |
| Extended M3U | `.m3u` | Same, for players that ignore `.m3u8` | Also UTF-8 with BOM-free `#EXTM3U` header |
| PLS | `.pls` | VLC, Winamp, Audacious, Clementine/Strawberry, foobar2000 | `[playlist]`, `FileN`/`TitleN`/`LengthN`, `NumberOfEntries`, `Version=2` |
| XSPF (XML) | `.xspf` | VLC, Strawberry, Clementine, Audacious, Rhythmbox, foobar2000 (plugin) | The **XML** option. Open standard, `file://` URIs in `<location>` |
| iTunes / Music library XML | `.xml` | Apple Music on Mac (File → Library → Import Playlist), iTunes on Windows | Apple plist with `Tracks` + `Playlists` dicts. Suggested addition |
| Windows Media Playlist | `.wpl` | Windows Media Player, Windows "Media Player" app | SMIL-based XML. Suggested addition |
| CSV | `.csv` | Spreadsheets, Soundiiz/TuneMyMusic-style importers | `Title,Artist,Album,Duration,ISRC,Path,Source URL`, UTF-8, RFC 4180 quoting |
| JSON | `.json` | Scripts, other tools | `{format, version, name, source, tracks:[…]}` |

Path style applies to M3U/M3U8/PLS/XSPF/WPL/XML: absolute (works on this machine), relative to the export folder (works when the music folder is copied together with the playlist), or file name only.

Not included, with reasons: ASX (superseded by WPL), Rhythmbox/Banshee DB formats (they import M3U/PLS/XSPF anyway), CUE (for single-file albums, not playlists).

### Missing tracks export

| Format | Shape |
|---|---|
| JSON | `{playlist, source, source_url, exported_at, tracks:[{title, artist, album, duration, isrc, url}]}` |
| CSV | `Title,Artist,Album,Duration,ISRC,URL` |
| Markdown | `# <Playlist> missing tracks`, intro line, then `- [ ] Get "Title" by Artist (Album) [Service](url)` lines. Works as a to-do list in Obsidian, Logseq, Joplin, GitHub, VS Code |
| TXT | `Artist - Title` per line, one blank-line-free list. Pastes into any to-do app, one task per line |

Files go to `[export] dir` (default `~/Music/TheCollector Exports`) as `<Playlist> missing tracks.<ext>`. Re-exporting overwrites the file. (The merge/tick-off behaviour stays a feature of the NextUp note only.)

## Config changes

```toml
[export]
dir = "~/Music/TheCollector Exports"

[vault]            # whole section optional now
nextup_config = "~/dev/NextUp/config.toml"
```

`[spotify] client_id` is read once for migration and then ignored if the store has a value.

## Out of scope for v2.0

- Reading private/library playlists for Apple Music, TIDAL, YouTube Music (needs per-user OAuth flows).
- Local libraries other than Strawberry.
- Writing playlists back to streaming services.
