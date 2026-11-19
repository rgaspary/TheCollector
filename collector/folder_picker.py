"""Ask the desktop to show its own folder picker, for the Browse buttons.

Linux asks the desktop portal first (the dialog KDE, GNOME and others use for every app), then
falls back to kdialog, zenity, yad or qarma. Windows uses PowerShell's folder dialog, macOS AppleScript.
Python's tkinter is the last resort anywhere. The page can't do this itself: a browser never tells a
page the real path of a folder.
"""
import importlib.util
import os
import secrets
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

from . import dbus

TITLE = "Choose a folder"
WAIT = 30 * 60  # seconds before giving up on an open dialog


class PickerUnavailable(Exception):
    """No folder picker could be shown. The message says what to do instead."""


def existing_start(start: str) -> Path:
    """The folder to open the dialog in: the given one, or the nearest parent that exists."""
    path = Path(start).expanduser() if start.strip() else Path.home()
    while not path.is_dir() and path != path.parent:
        path = path.parent
    return path if path.is_dir() else Path.home()


# ---- the desktop portal (org.freedesktop.portal.FileChooser) ------------------------------------

PORTAL = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"
REQUEST = "org.freedesktop.portal.Request"


def request_path(unique_name: str, token: str) -> str:
    """Where the portal will answer, worked out ahead so the answer can't arrive unseen."""
    return f"{PORTAL_PATH}/request/{unique_name.lstrip(':').replace('.', '_')}/{token}"


def portal_options(start: Path, token: str) -> dict:
    return {"handle_token": ("s", token), "directory": ("b", True), "modal": ("b", True),
            "current_folder": ("ay", os.fsencode(str(start)) + b"\0")}


def folder_from_response(code: int, results: dict) -> str | None:
    """The chosen folder from the portal's Response (0 chosen, 1 cancelled, 2 failed)."""
    if code == 2:
        raise PickerUnavailable
    uris = results.get("uris") or []
    if code != 0 or not uris:
        return None
    return unquote(urlparse(uris[0]).path)


def _watch(conn: dbus.Connection, path: str) -> None:
    conn.call("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "AddMatch", "s",
              (f"type='signal',interface='{REQUEST}',member='Response',path='{path}'",))


def _portal(start: Path) -> str | None:
    try:
        conn = dbus.Connection.session()
    except OSError as e:
        raise PickerUnavailable from e
    except dbus.DBusError as e:
        raise PickerUnavailable from e
    try:
        token = "thecollector_" + secrets.token_hex(6)
        expected = request_path(conn.unique_name, token)
        _watch(conn, expected)
        handle = conn.call(PORTAL, PORTAL_PATH, "org.freedesktop.portal.FileChooser", "OpenFile", "ssa{sv}",
                           ("", TITLE, portal_options(start, token)))[0]
        if handle != expected:  # very old portals ignore handle_token
            _watch(conn, handle)
        try:
            code, results = conn.wait_for_signal(handle, REQUEST, "Response", WAIT)
        except TimeoutError:
            return None  # left open too long: treat as cancelled rather than open another dialog
        return folder_from_response(code, results)
    except (OSError, dbus.DBusError) as e:
        raise PickerUnavailable from e
    finally:
        conn.close()


# ---- separate dialog programs -----------------------------------------------------------------------

_POWERSHELL = (
    "[Console]::OutputEncoding = [Text.Encoding]::UTF8; Add-Type -AssemblyName System.Windows.Forms; "
    "$owner = New-Object System.Windows.Forms.Form -Property @{TopMost = $true}; "
    "$d = New-Object System.Windows.Forms.FolderBrowserDialog; $d.Description = 'Choose a folder'; "
    "$d.SelectedPath = $env:TC_START; $d.ShowNewFolderButton = $true; "
    "if ($d.ShowDialog($owner) -eq 'OK') { [Console]::Out.Write($d.SelectedPath) }"
)
_APPLESCRIPT = ('POSIX path of (choose folder with prompt "Choose a folder" '
                'default location (POSIX file (system attribute "TC_START")))')
_TKINTER = ("import os, tkinter, tkinter.filedialog as f; r = tkinter.Tk(); r.withdraw(); "
            "r.attributes('-topmost', True); "
            "print(f.askdirectory(initialdir=os.environ['TC_START'], title='Choose a folder') or '', end='')")


def fallback_commands(start: Path, platform: str, env: dict, which) -> list[list[str]]:
    """Dialog programs to try in order. The start folder also reaches them as $TC_START."""
    commands = []
    if platform == "win32":
        commands.append(["powershell", "-NoProfile", "-STA", "-Command", _POWERSHELL])
    elif platform == "darwin":
        commands.append(["osascript", "-e", _APPLESCRIPT])
    else:
        kde = "KDE" in env.get("XDG_CURRENT_DESKTOP", "").upper()
        tools = {
            "kdialog": ["kdialog", "--title", TITLE, "--getexistingdirectory", str(start)],
            "zenity": ["zenity", "--file-selection", "--directory", f"--title={TITLE}", f"--filename={start}/"],
            "yad": ["yad", "--file", "--directory", f"--title={TITLE}", f"--filename={start}/"],
            "qarma": ["qarma", "--file-selection", "--directory", f"--title={TITLE}", f"--filename={start}/"],
        }
        order = ["kdialog", "zenity", "yad", "qarma"] if kde else ["zenity", "kdialog", "yad", "qarma"]
        commands += [tools[name] for name in order if which(name)]
    if importlib.util.find_spec("tkinter"):
        commands.append([sys.executable, "-c", _TKINTER])
    return commands


def choose_folder(start: str, platform: str = sys.platform) -> str | None:
    """Show a folder picker and wait for it. The chosen folder, or None if the user cancelled."""
    folder = existing_start(start)
    if platform not in ("win32", "darwin"):
        try:
            return _portal(folder)
        except PickerUnavailable:
            pass
    env = {**os.environ, "TC_START": str(folder)}
    for command in fallback_commands(folder, platform, os.environ, shutil.which):
        try:
            done = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", env=env, timeout=WAIT)
        except (OSError, subprocess.SubprocessError):
            continue
        chosen = done.stdout.strip()
        if done.returncode == 0:
            if not chosen:
                return None
            return chosen.rstrip("/") or "/" if platform == "darwin" else chosen
        if done.returncode == 1:  # every one of these exits with 1 on Cancel
            return None
    hint = " Installing zenity or kdialog adds one." if platform not in ("win32", "darwin") else ""
    raise PickerUnavailable(f"There's no folder picker on this computer, so type the folder instead.{hint}")
