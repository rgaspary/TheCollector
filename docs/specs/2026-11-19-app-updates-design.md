# App updates: notice, one-click update, restart

Date: 2026-11-19 · Status: approved in conversation, ready to plan

## Why

TheCollector is meant for people who are not developers. They will never run `git pull` or any
other terminal command. Today, the only way for them to get a new version is to download it again
by hand and set it up again. The app should tell them when a new release is on GitHub and install
it for them when they click a button.

## What the person sees

**1. Update notice.** This pops up when the app opens and a newer release exists that they haven't skipped:

```
┌──────────────────────────────────────────────┐
│  A new version of TheCollector is available  │
│                                              │
│  Installed:  2.0.0                           │
│  Available:  2.1.0          What's new ↗     │
│                                              │
│  [ Update now ]                              │
│                                              │
│  ☐ Skip this version                  [ ✕ ]  │
└──────────────────────────────────────────────┘
```

- **Asked for by the user:** the message, the installed and available versions, an Update button,
  and a "Skip this version" checkbox.
- **Skip this version:** ticking the box (then closing, or pressing Update, which un-skips) records
  that version. No popup appears again until a newer release is out.
- **✕ (my call):** closes the popup for this page load only. It returns the next time the app opens.
- **What's new (my call):** links to the release page on GitHub and opens in the normal browser.
- **Update now:** the button changes to "Updating…" and the popup stays open. If the update fails,
  the popup shows a short plain-language reason ("Couldn't reach GitHub. Check your internet
  connection and try again.") and a Try again button. The running app is not touched.

**2. Update ready.** This replaces the notice once the download is unpacked and checked:

```
┌──────────────────────────────────────────────┐
│  TheCollector 2.1.0 is ready                 │
│                                              │
│  Restart now to start using it, or keep      │
│  working and it will switch over the next    │
│  time you open TheCollector.                 │
│                                              │
│  [ Close and restart ]   [ Keep working ]    │
└──────────────────────────────────────────────┘
```

- **Close and restart:** the app restarts on the new version and the open window reloads, with no
  further input. While it waits, the popup shows "Restarting…".
- **Keep working:** closes the popup. The current version keeps running. The new version is put in
  place the next time the app starts.
- **Reloading the page while an update is waiting (my call):** shows a small line under the title
  with a Restart button instead of the full popup again: "TheCollector 2.1.0 is ready ·
  Restart to use it".

## Goals

- Tell the person about a new release without any setup on their part.
- Update with one click: no terminal, no uninstall, no reinstall.
- An update never loses anything:
  - `config.toml` stays in place.
  - Everything in the data folder (logins, choices, caches, update state) stays.
  - The menu entry keeps working, because the install folder path doesn't change.
- A failed download or a broken release never leaves the app unable to start.

## Non-goals

- Windows and macOS launchers. The update code should not do anything Linux-only that can be
  avoided, but it only has to work on Linux for now.
- An automatic or silent update with no click.
- Beta or pre-release channels: only GitHub's "latest" release counts.
- A setting to turn checks off.
- Updating the system's Python or the WebKitGTK window libraries.

## Anti-goals (would make this a failure even if it "works")

- Any step that needs a terminal or a password.
- Showing the popup again for a version the person skipped.
- Replacing files under the running app. The running server reads `static/` from disk on every
  request, so the old program would serve new pages and break in odd ways.
- Installing an older version over a newer one, or downloading from anywhere other than this repo.
- Any personal information sent to GitHub. Only the normal `TheCollector/<version>` User-Agent is sent.

## Constraints from the project

- **Standard library only:** no dependencies beyond Python 3.11+. Downloads use `collector/http.py`
  (the one place the app talks to the web), not curl. curl isn't always installed, and tests already
  replace `http.opener`.
- **An install is the project folder itself.**
  - What's in that folder:
    - `collector-launch.sh`: starts the server with `setsid … python3 -m collector --no-browser` and
      writes the menu entry, which points at that folder.
    - `config.toml`: user settings, created from `config.example.toml`.
    - `collector.log`: server output.
  - Everything else the person owns lives in the data folder (`config.DATA_DIR`).
- **Existing pieces to reuse:**
  - `__version__` in `collector/__init__.py`.
  - `atomic_write` in `collector/files.py`.
  - `/api/status` already returns `version`.
- **Security:**
  - New POST endpoints get the same same-origin and Host checks as every other POST.
  - The download target is fixed in code (`rgaspary/TheCollector`) and never comes from the request.

## Approaches considered

1. **`git pull`.** Simple, but only works for git clones. The people this is for won't have one.
   Rejected.
2. **Download the release from GitHub and swap the files.** Works for any install. **Chosen by the user.**
3. **Both, picking by install type.** Not needed, because the audience doesn't use git.

**Within approach 2:**
- **Swap right away: rejected.** "Keep working" would then run old code against new files.
- **Two stages: chosen.** The download is staged first, and the files are swapped at the next start.

## How it works

### Checking for a release

- **Where it asks:** `GET https://api.github.com/repos/rgaspary/TheCollector/releases/latest`.
- **What it reads:**
  - `tag_name`, for example `v2.1.0`. Strip the leading `v` and compare as a tuple of integers.
  - `html_url`, used for the What's new link.
- **When it counts as an update:** only when `latest > __version__`.
- **When it checks:**
  - When the page loads, the frontend calls `GET /api/update`.
  - The server asks GitHub at most once every 24 hours. It stores the result and when it checked.
  - If the check fails (offline, rate limited, odd answer), no error is shown, and the last
    answer that worked (if any) is kept. It is tried again after the 24 hours.
- **Saved state:** `DATA_DIR/update.json`, written with `atomic_write`, holds:
  `checked_at`, `latest` (version and url) and `skipped` (a version string).
- **When the popup shows:** `latest > __version__`, `latest != skipped`, and no update is already
  staged.

### Downloading and staging (POST /api/update/download)

The server does this in a background thread. The frontend polls `GET /api/update` for its `state`:
`idle | downloading | ready | failed`, plus `error`.

1. Download the release's source tarball through `collector/http.py`, from
   `https://api.github.com/repos/rgaspary/TheCollector/tarball/v<version>`. It redirects to
   codeload.github.com. Follow that redirect, and only accept github.com hosts.
2. Unpack it into a fresh `<install>/.update/staging-<version>/`, safely:
   - No absolute paths, no `..`, no links that point outside the folder, no device files.
   - Use `tarfile`'s `filter="data"` where it exists (3.11.4+). Otherwise do the same checks by hand.
   - Keep the executable bit on `collector-launch.sh`.
   - GitHub wraps everything in one top-level folder (`rgaspary-TheCollector-<sha>/`). Its contents
     are the new install.
3. Check the staged copy before calling it ready:
   - `collector/__init__.py` says the expected version.
   - It imports: run `sys.executable -I -c "import collector.web, collector.__main__"` with the
     staged folder as the working directory and `PYTHONPATH`, and require exit 0.
4. Write `<install>/.update/ready.json` with the version and staging folder, then set state `ready`.
   - **If any step fails:** delete the staging folder, set state `failed` with a plain-language
     message, and leave the running app untouched.
   - **Only one download at a time:** a second POST while downloading returns the current state.

### Putting the new version in place (at the next start)

- **When it runs:** first thing in `collector/__main__.py`'s `main()`, before the server starts.
  If `<install>/.update/ready.json` exists:
  1. Move every top-level entry of the install folder into `<install>/.update/previous-<old version>/`,
     except the keep list: `config.toml`, `collector.log`, `.update`, `.git`, `.venv`.
  2. Move every top-level entry of the staged folder into the install folder.
  3. Delete `ready.json` and the empty staging folder.
  4. Restart the process with `os.execv(sys.executable, [sys.executable, "-m", "collector", *args])`,
     so the new code is what runs.
- **If step 1 or 2 fails** (for example, a permission error): move everything back from
  `previous-…`, delete `ready.json`, log the reason, and carry on starting the old version.
  The staging folder is deleted, so the next page load offers the update again.
- **Clean-up:** the new version deletes `.update/previous-*` once its server has started.
- **Renames only:** files are moved with renames, never rewritten in place. Bash is still reading
  `collector-launch.sh` while it waits for the server, and a rename leaves the old file intact for it.
- **Version suffixes (my call):** `2.0.0-dev` is compared on its numbers only. A tag that isn't
  `v<int>.<int>.<int>` counts as "no update".
- **Why this is safe enough:**
  - The staged copy was proven to import before it was marked ready.
  - The swap is a few renames inside one folder on the same disk.

### Restarting (POST /api/update/restart)

- **What the server does:**
  1. Reply `{ok: true}`.
  2. Shut down the server and close its socket.
  3. `os.execv` itself with the same arguments, plus `--no-browser` so no new browser tab opens.
- **Why `execv`:** it keeps the process detached exactly as the launcher started it, and the port
  is free before the new copy binds. The new process applies the staged update, then execs once more.
- **What the page does:** shows "Restarting…" and polls `/api/status` until it answers with the new
  version, then reloads. After 60 seconds without an answer, it says "TheCollector didn't come back.
  Open it again from your app menu."
- **The app window** (`collector/window.py`, GTK) just shows the page, so the page reload is enough.

### Skipping (POST /api/update/skip `{version}`)

- Saves `skipped`. An empty version clears it.

### A git checkout (my call)

- **When:** the install folder contains `.git`.
- **What changes:** the notice still appears, but Update is replaced by "This copy is a git
  checkout. Update it with git." plus the What's new link.
- **Why:** swapping files would bury a developer's uncommitted work in `.update/previous-…`.

## API summary

| Endpoint | Does |
|---|---|
| `GET /api/update` | `{current, latest, url, skipped, state, error, git}`. Checks GitHub if the last check is over 24 h old. |
| `POST /api/update/download` | Start downloading and staging `latest`. |
| `POST /api/update/skip` | `{version}`: skip that version (empty clears it). |
| `POST /api/update/restart` | Shut down and restart, applying a staged update. |

## Left to the builder

- Module layout. A suggestion: `collector/updates.py` for check, download, stage, apply and state,
  and `static/js/update.js` for the popups.
- The popup's styling. Follow the existing look in `static/style.css`, use a `<dialog>`, and keep
  keyboard focus inside it.
- Exact wording of error messages, in the plain style the app already uses.
- Tests. Use the existing unittest style and fake `http.opener`. Build small tarballs in a temp dir
  to cover:
  - version compare, the 24-hour cache, skip, and unsafe tarball members;
  - a failed import check;
  - applying an update and rolling it back;
  - the git-checkout guard.
- A CHANGELOG entry and a short README note ("TheCollector tells you when there's a new version").
