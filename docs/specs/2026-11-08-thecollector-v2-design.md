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
| 6 | Works with the user's own music app, not only Strawberry | Reads the library from Strawberry, iTunes/Apple Music, MediaMonkey, or any music folder (covers Winamp, VLC, Windows Media Player). Export asks "Which app will you open this in?" and picks the right format |
| 7 | Runs for other people | Runs on Linux, Windows and macOS (`python -m collector` opens it in the browser). The GTK window and launcher stay Linux extras |

Version: `2.0.0` (breaking: config layout, API routes, missing-note link label).

## What stays

- Python 3.11+ standard library only, no pip installs. Vanilla JS/CSS frontend, no build step.
- Matching logic (`matching.py`) is unchanged apart from the track type rename. Every library is turned into the same `LocalTrack` list first.
- Local server on `127.0.0.1:8766`. GTK window and launcher script on Linux.

## Local libraries

The app needs a list of the user's tracks (title, artist, album, duration, file path) to match against. Four readers, picked once on a "Your music library" screen and changeable later:

| Library | Covers | What it reads | Default location |
|---|---|---|---|
| Strawberry | Strawberry (and Clementine with the same schema) | SQLite `strawberry.db`, read from a temp copy (v1 code) | Linux `~/.local/share/strawberry/strawberry/strawberry.db`, Windows `%LOCALAPPDATA%\strawberry\strawberry\strawberry.db`, macOS `~/Library/Application Support/Strawberry/Strawberry/strawberry.db` |
| iTunes / Apple Music | iTunes (Windows, older macOS), Music app (macOS) | Library XML (`plistlib`): `Tracks` dict, `Location` file URLs | Windows `%USERPROFILE%\Music\iTunes\iTunes Library.xml`. macOS: the user turns on Music → Settings → Advanced → "Share Library XML with other applications", or uses File → Library → Export Library; the screen explains this |
| MediaMonkey | MediaMonkey 4 and 5 (Windows) | SQLite `MM.DB` / `MM5.DB` from a temp copy. Registers a stand-in `IUNICODE` collation (case-insensitive compare) so queries don't fail | `%APPDATA%\MediaMonkey\MM.DB`, `%APPDATA%\MediaMonkey5\MM5.DB` |
| Music folder | Winamp, VLC, Windows Media Player, foobar2000, MusicBee, anything else | Scans one or more folders and reads tags with small built-in readers: ID3v1/v2 (MP3), FLAC, MP4/M4A, Ogg Vorbis/Opus, WMA (ASF). Falls back to `Artist/Album/NN Title.ext` from the path. Results cached by path + size + modified time | `~/Music` (Windows `%USERPROFILE%\Music`) |

Why a folder scan for Winamp and Windows Media Player: their libraries are in formats Python can't read without extra packages (Winamp's NDE files, WMP's ESE database), and both are built from the user's music folders anyway. VLC desktop has no library database.

## Which format for which app

The Export screen opens with "Which app will you open this in?" as tiles. Picking one ticks its recommended format and shows the import steps. "Show all formats" opens the full checkbox list.

| App | Recommended | Also works | How to import (shown on screen) |
|---|---|---|---|
| iTunes (Windows) | iTunes XML (`.xml`) | M3U | File → Library → Import Playlist |
| Apple Music (macOS) | iTunes XML (`.xml`) | M3U8, M3U (community-reported, not documented by Apple) | File → Library → Import Playlist |
| Strawberry | M3U8 | XSPF, PLS | Playlist → Load playlist, or drag the file in |
| VLC | XSPF | M3U8, PLS | Media → Open File, or drag the file in |
| MediaMonkey | M3U8 | M3U, PLS | File → Import → Playlists, or drag the file onto Playlists |
| Winamp | M3U8 | PLS, M3U | Drag into the playlist editor, or Library → Playlists → Import |
| Windows Media Player (Legacy) | WPL | M3U | Drag the file into the Library, or open it |
| Media Player (Windows 11) | M3U | WPL | Open the file with Media Player (playlist import support to be confirmed in testing) |
| Other / not sure | M3U8 | everything | — |

File paths in the export use the running OS's form (backslashes on Windows for M3U/PLS/WPL; `file:///` URIs in XSPF and iTunes XML). The playlist is meant to be opened on the same computer the app runs on. The "relative paths" option is for copying music + playlist to another computer.

The compatibility table is checked by hand before release (plan Task 23). Rows that fail get their recommendation changed.

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

- Stored in the app's data folder as `credentials.json`: Linux `~/.local/share/thecollector/` (as today), Windows `%APPDATA%\TheCollector\`, macOS `~/Library/Application Support/TheCollector/`. Mode `0600` where the OS supports it (on Windows the folder is already private to the user), written atomically. Same place and protection as today's `token.json`.
- The browser never gets a stored secret back. The API returns which fields are set; secret fields show as "saved" placeholders. A blank secret field on save means "keep the saved one".
- Each source has a status: `ready`, `needs_setup` (nothing stored), or `invalid` (stored but the last call was refused, with the reason).
- `invalid` is set when a test fails or any API call answers 401/403 for auth reasons. A later successful test or fetch clears it.
- Spotify's `client_id` moves from `config.toml` into the store on first v2 start. The config key is still read as a fallback.

## Screens and flow

```
0 Your music library (first run, or "Change library" in the header)
   ▼
1 Source ──► 1a Set up credentials ─┐
   │         1b Fix credentials ────┤ (only when needed)
   ▼                                ▼
2 Playlist link ──► 3 Review matches ──► 4 Export playlist ──► 5 Missing tracks ──► 6 Done
```

- **0 Library:** tiles for Strawberry, iTunes / Apple Music, MediaMonkey, Music folder (subtitle "Winamp, VLC, Windows Media Player, others"). The app fills in the detected path; **Test** reports "Found 12,345 tracks" or what's wrong. **Save & continue**. Shown once; the header shows the library name with a **Change** link.
- **1 Source:** grid of tiles, each with the service's official icon and its name underneath. A small badge on the tile shows "Set up" or "Needs attention".
- **1a Set up:** "Where to get these" help with a link to the service's developer page, the fields, an optional **Test** button that reports OK or the exact error, and **Save & continue**. OAuth sources (Spotify, Amazon) add a **Connect** button after the fields are saved.
- **1b Fix:** like 1a, plus a red box saying what went wrong (the service's message) and how to fix it (per-source text, e.g. "Your TIDAL client secret was rejected. Copy it again from developer.tidal.com → Dashboard"). Fields come prefilled, secrets show as saved. **Save & try again** goes back to where the user was (source pick or analyze).
- **2 Link:** paste field with the chosen service's example link, **Analyze**, progress state. A link from the wrong service gets a hint ("That's a Spotify link — switch source?").
- **3 Review:** today's results card (chips, close-match choices, bulk buttons). **Continue** is enabled once every close match is decided.
- **4 Export playlist:** "Which app will you open this in?" tiles (pre-selected from the library choice: Strawberry → Strawberry, iTunes/Apple Music → iTunes or Apple Music by OS, MediaMonkey → MediaMonkey, folder → last pick), import steps for that app, "Show all formats" with checkboxes, a path-style choice (absolute / relative to the export folder / file name only), the folder, and **Export**. Skippable when nothing matched.
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

[library]
type = "strawberry"          # strawberry | itunes | mediamonkey | folder
path = ""                    # empty = detected default for this OS
folders = ["~/Music"]        # used by type = "folder"
playlist_dir = "~/Music/Playlists"

[vault]            # whole section optional now
nextup_config = "~/dev/NextUp/config.toml"
```

`[spotify] client_id` is read once for migration and then ignored if the store has a value.

## Out of scope for v2.0

- Reading private/library playlists for Apple Music, TIDAL, YouTube Music (needs per-user OAuth flows).
- Reading Winamp's or Windows Media Player's own library databases (the folder scan covers them).
- Adding the playlist into the player automatically (the user imports the file).
- Packaged installers for Windows/macOS (people run it with Python 3.11+ in v2.0).
- Writing playlists back to streaming services.
