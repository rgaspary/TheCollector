# TheCollector

Paste a Spotify playlist link and get the same playlist built from your own music (Strawberry
library). Tracks you don't have go to an Obsidian note, `<Playlist> missing tracks`, which shows up
on NextUp's **Music** card.

No dependencies beyond Python 3.11+.

## Setup (once)

1. In your app at https://developer.spotify.com/dashboard, add the Redirect URI
   `http://127.0.0.1:8766/callback`.
2. Paste the app's Client ID into `config.toml` → `[spotify] client_id`
   (or set the `SPOTIFY_CLIENT_ID` environment variable). `config.toml` is created from
   `config.example.toml` the first time the app runs; it holds your own settings and is not
   committed to git.
3. Restart NextUp so it picks up the new Music area: `~/dev/NextUp/nextup-launch.sh stop`, then open it again.

## Install as an app

```bash
~/dev/TheCollector/collector-launch.sh install
```

This adds **TheCollector** to your app menu with its icon (already done on this machine). Opening
it starts the server in the background and shows TheCollector in its own window (GTK + WebKitGTK,
app ID `dev.thecollector.TheCollector`), so the taskbar shows its icon, just like NextUp. Without
WebKitGTK it falls back to a Chromium app window, then your default browser.

- Right-click the icon → **Stop TheCollector**, or `collector-launch.sh stop`, stops the server.
- `collector-launch.sh uninstall` removes the menu entry.
- Server output goes to `collector.log`.
- Spotify sign-in opens in your normal browser; the app window switches over by itself once you're connected.

## Run from a terminal

```bash
python3 -m collector
```

It opens http://127.0.0.1:8766 in your browser. Connect Spotify, paste a playlist link, click **Analyze**.

- **In your library:** the same song, artist, version and album. Added automatically.
- **Close matches:** same song but a live/acoustic/remix/demo version, a different album, or a
  slightly different title. You pick your copy, or **Add to missing tracks**. Your pick is
  remembered for next time. Remasters alone don't count as different.
- **Missing:** not in your library. Goes to the to-do note.

**Build playlist** writes `~/Music/Playlists/<Playlist>.m3u8` (open it in Strawberry with
Playlist → Load playlist) and creates or updates
`Entertainment/Missing Tracks/<Playlist> missing tracks.md` in your vault.

Running the same playlist again doesn't duplicate tasks: new missing tracks are added, and tracks
you've since got are ticked off.

## Files

| Path | What |
|---|---|
| `collector/matching.py` | Title/version/album matching (ported from spotify-itunes-gap-analyzer) |
| `collector/spotify.py` | Spotify login (PKCE) and playlist reading |
| `collector/library.py` | Reads Strawberry's database (from a copy, so Strawberry can stay open) |
| `collector/vault.py` | Writes the missing-tracks note in NextUp's task format |
| `~/.local/share/thecollector/` | Spotify login token and remembered choices |

Tests: `python3 -m unittest discover tests`

## Spotify limits

Apps in Spotify's development mode may only be allowed to read playlists you own or collaborate on.
If a playlist is refused, save a copy of it to your own account and use that link.

## License

MIT. See [LICENSE](LICENSE).
