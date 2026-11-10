# Changelog

## 2.0.0 (unreleased)

### Added
- Browse… buttons next to the playlist and missing-list folders. They open your desktop's own folder picker: the KDE or GNOME dialog through the desktop portal on Linux (or kdialog / zenity), the folder dialog on Windows, and Finder's on macOS.
- A folder field on the Missing step, so the missing-songs list can be saved anywhere.
- Rockbox (iPods and other players running Rockbox) in the Export step's app list. It picks M3U8 with paths relative to the playlist, and explains how to copy the music and playlist so the paths still work on the player.
- A warning on the Library and Review steps when Strawberry's library is missing music files that are in its folders (Strawberry hasn't rescanned), with how to fix it.
- Export, Missing and Done steps: pick the app you'll open the playlist in (its best format is ticked and its import steps shown), save the missing songs as a file and/or into the NextUp note, then open the folder or the note from the Done screen.
- Playlist and Review steps: paste a link from the chosen service (a link from another service offers to switch), then decide close matches one by one or all at once. Last time's choices are pre-selected.
- Library and music-service tiles. Services show a "Set up" or "Needs attention" badge; the set-up and fix screens have an optional Test button that never saves, and Spotify adds a Connect button.
- `COLLECTOR_CONFIG` environment variable to use another config file.
- Missing-tracks export without NextUp: JSON, CSV, a Markdown checklist (works in Obsidian, Logseq, Joplin, GitHub, VS Code) or plain text with one song per line.
- Playlist export in M3U8, M3U, PLS, XSPF, iTunes / Music XML, Windows Media Playlist (WPL), CSV and JSON, with absolute, relative or file-name-only paths, plus a table of which format each music app imports best and how.
- Music libraries besides Strawberry: iTunes / Apple Music (library XML), MediaMonkey (MM5.DB / MM.DB), and any music folder, which covers Winamp, VLC, Windows Media Player and other players.
- Built-in tag reading for MP3, FLAC, M4A, Ogg Vorbis, Opus and WMA files. Folder scans are cached, so later scans only read new or changed files.
- YouTube Music source: public and unlisted playlists with a free YouTube Data API v3 key. Artist and title come from the video title or the artist's "Topic" channel.
- Version number (`collector.__version__`).
- Runs its data folder per OS: Linux `~/.local/share/thecollector`, Windows `%APPDATA%\TheCollector`, macOS `~/Library/Application Support/TheCollector`.
- Saved settings per streaming service in `credentials.json` in the data folder (readable only by you). Your v1 Spotify Client ID and login move there automatically.
- New `[library] type / path / folders` settings, and `[export] playlist_dir / missing_dir`.

### Changed
- Playlists are saved to the Playlists folder inside your Music folder, and missing-song lists to your Documents folder, unless you pick another folder. Both follow the system's own Music and Documents folders (translated names, OneDrive, another drive). `[library] playlist_dir` from v1 still works; `[export] dir` is no longer used.
- Starting the app when it's already running opens the running copy instead of crashing. If another program has the port, a short message says so.
- The page is now a series of steps (Library, Service, Playlist, Review, Export, Missing, Done) that slide left and right with a fade, or only fade when the system asks for reduced motion.
- New JSON API for the step-by-step screens: library choice and test, sources and saved logins (set up, test, disconnect), analyze any source, resolve, export playlist and missing tracks, and show a saved file's folder.
- Songs from playlists without album names (YouTube Music) are no longer marked "Different album", so they can match exactly.
- The NextUp missing-tracks note names the playlist's service ("[YouTube Music](…)" and so on). Existing notes with "[Spotify](…)" links keep merging and ticking off.
- Remembered close-match picks are stored per service (v1 picks still apply).
- NextUp is optional: without a `[vault]` section (or NextUp's config file) the app still runs.

### Removed
