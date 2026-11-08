#!/usr/bin/env bash
# Start TheCollector (if it isn't running) and open its window. Mirrors NextUp's launcher.
#   collector-launch.sh            start + open
#   collector-launch.sh stop       stop the background server
#   collector-launch.sh install    add TheCollector to the app menu
#   collector-launch.sh uninstall  remove it from the app menu
set -u
MODE="${1:-}"
DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
PORT="${COLLECTOR_PORT:-8766}"
URL="http://127.0.0.1:${PORT}"
LOG="$DIR/collector.log"
CONTAINER="${COLLECTOR_DISTROBOX:-${NEXTUP_DISTROBOX:-}}"
APP_ID="dev.thecollector.TheCollector"
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"

running() { (exec 3<>"/dev/tcp/127.0.0.1/${PORT}") 2>/dev/null; }

notify() {
  command -v notify-send >/dev/null && notify-send -a TheCollector -i "$DIR/static/icon.svg" "TheCollector" "$1"
  echo "$1" >&2
}

# Prefer the host's Python 3.11+, otherwise run inside a distrobox container if one is named
# (COLLECTOR_DISTROBOX or NEXTUP_DISTROBOX).
run_cmd() {
  if command -v python3 >/dev/null && python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
    env PYTHONPATH="$DIR" "$@"
  elif [ -n "$CONTAINER" ] && command -v distrobox >/dev/null; then
    distrobox enter "$CONTAINER" -- env PYTHONPATH="$DIR" "$@"
  else
    notify "TheCollector needs Python 3.11 or newer."
    return 1
  fi
}

case "$MODE" in
  install)
    mkdir -p "$APPS"
    cat >"$APPS/$APP_ID.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=TheCollector
GenericName=Playlist builder
Comment=Build Spotify playlists from your own music library
Exec=$DIR/collector-launch.sh
Icon=$DIR/static/icon.svg
Terminal=false
Categories=AudioVideo;Audio;Music;
Keywords=spotify;playlist;music;strawberry;obsidian;
StartupWMClass=$APP_ID
StartupNotify=true
Actions=stop;

[Desktop Action stop]
Name=Stop TheCollector
Exec=$DIR/collector-launch.sh stop
EOF
    command -v update-desktop-database >/dev/null && update-desktop-database "$APPS" 2>/dev/null
    echo "Installed: $APPS/$APP_ID.desktop"
    exit 0
    ;;
  uninstall)
    rm -f "$APPS/$APP_ID.desktop"
    echo "Removed TheCollector from the app menu."
    exit 0
    ;;
  stop)
    if running; then
      # Ask the server to shut itself down (no curl needed).
      exec 3<>"/dev/tcp/127.0.0.1/${PORT}" &&
        printf 'POST /api/shutdown HTTP/1.0\r\nHost: 127.0.0.1\r\nContent-Length: 0\r\n\r\n' >&3 &&
        cat <&3 >/dev/null
      exec 3>&-
      for _ in $(seq 1 20); do running || break; sleep 0.25; done
      running && notify "Couldn't stop TheCollector" || notify "Stopped"
    fi
    exit 0
    ;;
esac

if ! running; then
  cd "$DIR" || exit 1
  setsid -f bash -c "$(declare -f run_cmd notify); DIR='$DIR' CONTAINER='$CONTAINER'; run_cmd python3 -m collector --no-browser" >>"$LOG" 2>&1 </dev/null
  for _ in $(seq 1 60); do running && break; sleep 0.5; done
  if ! running; then
    notify "Couldn't start. See $LOG"
    exit 1
  fi
fi

[ "${COLLECTOR_NO_BROWSER:-}" = 1 ] && exit 0

# Best option: TheCollector's own window (GTK + WebKitGTK), so the taskbar shows its icon.
if [ "${COLLECTOR_BROWSER:-}" = "" ] &&
   python3 -c 'import gi; gi.require_version("Gtk", "3.0"); gi.require_version("WebKit2", "4.1")' 2>/dev/null; then
  setsid -f python3 "$DIR/collector/window.py" "$URL" >>"$LOG" 2>&1 </dev/null
  exit 0
fi

# Otherwise a Chromium app window in its own profile, else the default browser.
PROFILE="${XDG_DATA_HOME:-$HOME/.local/share}/thecollector/browser"
for b in chromium chromium-browser google-chrome google-chrome-stable brave-browser microsoft-edge vivaldi; do
  if command -v "$b" >/dev/null; then
    mkdir -p "$PROFILE"
    setsid -f "$b" --user-data-dir="$PROFILE" --no-first-run --no-default-browser-check \
      --app="$URL" --class=TheCollector >/dev/null 2>&1
    exit 0
  fi
done
setsid -f xdg-open "$URL" >/dev/null 2>&1
