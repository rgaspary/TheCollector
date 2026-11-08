# Changelog

## 2.0.0 (unreleased)

### Added
- Version number (`collector.__version__`).
- Runs its data folder per OS: Linux `~/.local/share/thecollector`, Windows `%APPDATA%\TheCollector`, macOS `~/Library/Application Support/TheCollector`.
- `[export] dir` setting and new `[library] type / path / folders` settings.

### Changed
- NextUp is optional: without a `[vault]` section (or NextUp's config file) the app still runs.

### Removed
