# Changelog

## 2.0.0 (unreleased)

### Added
- YouTube Music source: public and unlisted playlists with a free YouTube Data API v3 key. Artist and title come from the video title or the artist's "Topic" channel.
- Version number (`collector.__version__`).
- Runs its data folder per OS: Linux `~/.local/share/thecollector`, Windows `%APPDATA%\TheCollector`, macOS `~/Library/Application Support/TheCollector`.
- Saved settings per streaming service in `credentials.json` in the data folder (readable only by you). Your v1 Spotify Client ID and login move there automatically.
- `[export] dir` setting and new `[library] type / path / folders` settings.

### Changed
- Remembered close-match picks are stored per service (v1 picks still apply).
- NextUp is optional: without a `[vault]` section (or NextUp's config file) the app still runs.

### Removed
