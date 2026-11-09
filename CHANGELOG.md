# Changelog

## 2.0.0 (unreleased)

### Added
- Playlist export in M3U8, M3U, PLS, XSPF, iTunes / Music XML, Windows Media Playlist (WPL), CSV and JSON, with absolute, relative or file-name-only paths, plus a table of which format each music app imports best and how.
- Music libraries besides Strawberry: iTunes / Apple Music (library XML), MediaMonkey (MM5.DB / MM.DB), and any music folder, which covers Winamp, VLC, Windows Media Player and other players.
- Built-in tag reading for MP3, FLAC, M4A, Ogg Vorbis, Opus and WMA files. Folder scans are cached, so later scans only read new or changed files.
- YouTube Music source: public and unlisted playlists with a free YouTube Data API v3 key. Artist and title come from the video title or the artist's "Topic" channel.
- Version number (`collector.__version__`).
- Runs its data folder per OS: Linux `~/.local/share/thecollector`, Windows `%APPDATA%\TheCollector`, macOS `~/Library/Application Support/TheCollector`.
- Saved settings per streaming service in `credentials.json` in the data folder (readable only by you). Your v1 Spotify Client ID and login move there automatically.
- `[export] dir` setting and new `[library] type / path / folders` settings.

### Changed
- Remembered close-match picks are stored per service (v1 picks still apply).
- NextUp is optional: without a `[vault]` section (or NextUp's config file) the app still runs.

### Removed
