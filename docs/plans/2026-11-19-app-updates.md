# App Updates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** TheCollector tells people when a newer GitHub release exists and installs it with one click: it downloads and checks the release, puts it in place at the next start, and can restart itself.

**Architecture:** A new `collector/updates.py` owns everything about updates:
- the version check and its state file;
- the staged download;
- the swap at start-up;
- the restart.

`collector/http.py` gains a binary `download()`. `web.py` exposes four endpoints, and `__main__.py` applies a staged update before the server starts and restarts on request. A new `static/js/update.js` shows the two popups and the "ready" line.

**Tech Stack:** Python 3.11+ standard library only (urllib, tarfile, subprocess, os.execv) · vanilla ES modules · unittest.

**Spec:** `docs/specs/2026-11-19-app-updates-design.md`. Read it first; this plan argues from it.

## Global Constraints

- No dependencies beyond Python 3.11+. All web requests go through `collector/http.py` (tests replace `http.opener`).
- Repo is fixed in code: `rgaspary/TheCollector`. Release info: `https://api.github.com/repos/rgaspary/TheCollector/releases/latest`. Tarball: `https://api.github.com/repos/rgaspary/TheCollector/tarball/v<version>`.
- Downloads only from hosts `api.github.com`, `github.com`, `codeload.github.com`.
- Check GitHub at most once every 24 hours. A failed check means "no update", and no error is shown.
- State file `DATA_DIR/update.json` holds `checked_at`, `latest`, `url` and `skipped`. Write it with `files.atomic_write`.
- Staging lives in `<install>/.update/`:
  - `staging-<version>/`: the unpacked release.
  - `ready.json`: written once the staged copy checks out.
  - `previous-<old version>/`: the old files, set aside during the swap.
- Keep list (never moved): `config.toml`, `collector.log`, `.update`, `.git`, `.venv`.
- Moves are `os.replace`/`Path.rename` only, never rewrites in place.
- Versions:
  - **The installed version** is compared on its numbers only (`2.0.0-dev` → `(2, 0, 0)`).
  - **A release tag** must match `v<int>.<int>.<int>`. Anything else means "no update".
- A folder with `.git` gets no Update button: no download, `git: true`.
- New POST endpoints go through the existing `_known_host` and `_same_origin` checks (they do so automatically by living in the `routes` dict).
- Plain-language copy, matching the spec's popups exactly:
  - "A new version of TheCollector is available"
  - "Installed:" / "Available:"
  - "What's new ↗"
  - "Update now" / "Updating…"
  - "Skip this version"
  - "TheCollector <v> is ready"
  - "Restart now to start using it, or keep working and it will switch over the next time you open TheCollector."
  - "Close and restart" / "Keep working" / "Restarting…"
  - "TheCollector didn't come back. Open it again from your app menu."
  - "TheCollector <v> is ready · Restart to use it"
  - "This copy is a git checkout. Update it with git."
- Commit messages: no Co-Authored-By line (user's instruction for this repo).

## Review Focus

1. **The app is closed mid-download.** A `staging-*` folder is left without `ready.json`. The next start must delete it and start normally. Tested in Task 4 (`test_leftover_staging_without_ready_is_removed`).
2. **GitHub rate-limits or sends junk** (403, HTML, missing `tag_name`). There's no popup and no error. `checked_at` is still recorded, so the app doesn't call GitHub on every page load. Tested in Task 2 (`test_failed_check_waits_a_day`).
3. **`update.json` is corrupt or empty.** It's treated as no state and never crashes `/api/update`. Tested in Task 2 (`test_corrupt_state_file_is_ignored`).
4. **The install folder can't be written** (disk full, read-only) while staging. The state becomes `failed` with a plain message, and no `staging-*` folder is left behind. Tested in Task 3 (`test_unwritable_folder_fails_cleanly`).
5. **A redirect leaves GitHub,** for example a hijacked DNS or proxy that sends the tarball elsewhere. The download is refused and no file is written. Tested in Task 1 (`test_redirect_off_github_is_refused`).

---

### Task 1: Binary download in `http.py`

**Files:**
- Modify: `collector/http.py`
- Test: `tests/test_http.py`

**Interfaces:**
- Produces: `download(url: str, dest: Path, *, allowed_hosts: tuple[str, ...], max_bytes: int = 50_000_000) -> None`.
  - Writes the body to `dest`.
  - Raises `HttpError(status, body)` on HTTP errors and `HttpError(0, reason)` on network errors.
  - Raises `HttpError(0, "Download came from an unexpected address.")` when the final URL's host (`resp.geturl()`) isn't in `allowed_hosts`.
  - Raises `HttpError(0, "Download is larger than expected.")` past `max_bytes`.
  - Deletes a partial `dest` on any failure.

- [ ] **Step 1: Write the failing tests** in `tests/test_http.py`, using the file's existing fake-opener style. The fake response needs `read(n)`, `geturl()` and context-manager methods.
  - `test_download_writes_file`: 3 bytes from `https://codeload.github.com/x` → `dest.read_bytes() == b"abc"`.
  - `test_redirect_off_github_is_refused`: `geturl()` returns `https://evil.example/x` → `HttpError` raised, `not dest.exists()`.
  - `test_download_too_large`: `max_bytes=2` with 3 bytes → `HttpError`, `not dest.exists()`.
  - `test_download_http_error`: opener raises `urllib.error.HTTPError(…, 404, …)` → `HttpError` with `status == 404`.
- [ ] **Step 2: Run** `python3 -m unittest tests.test_http -v`. Expected: the 4 new tests FAIL (`download` missing).
- [ ] **Step 3: Implement `download`.** Read in 64 KiB chunks and check the host before writing anything. Send the same `User-Agent` header as `request_json`.
- [ ] **Step 4: Run** `python3 -m unittest tests.test_http -v`. Expected: all PASS.
- [ ] **Step 5: Commit:** `git add collector/http.py tests/test_http.py && git commit -m "feat: binary downloads limited to given hosts"`

### Task 2: Version check and update state

**Files:**
- Create: `collector/updates.py`
- Test: `tests/test_updates.py`

**Interfaces:**
- Produces (module level in `collector/updates.py`):
  - `REPO = "rgaspary/TheCollector"`, `LATEST_URL`, `TARBALL_URL` (with a `{version}` placeholder), `CHECK_EVERY = 24 * 3600`, `KEEP = frozenset({...})`, `GITHUB_HOSTS = ("api.github.com", "github.com", "codeload.github.com")`.
  - `parse_tag(tag: str) -> tuple[int, int, int] | None`: strict `v<int>.<int>.<int>`.
  - `parse_version(v: str) -> tuple[int, int, int]`: lenient, ignores a `-suffix`.
  - `class UpdateError(Exception)`: its message is shown to the person as is.
  - `class Updater`, created as `Updater(root: Path = config.ROOT, state_path: Path = config.DATA_DIR / "update.json", current: str = __version__, clock: Callable[[], float] = time.time)`.
    - `info() -> dict`: returns `{"current", "latest", "url", "skipped", "state", "error", "git", "show"}`.
      - `state` is one of `"idle" | "downloading" | "ready" | "failed"`.
      - `show` is true when `latest > current`, `latest != skipped`, and `state != "ready"`.
      - Calls GitHub only when `clock() - checked_at >= CHECK_EVERY`.
    - `skip(version: str) -> None`: `""` clears the skip.
    - `ready_version() -> str | None`: the version in `<root>/.update/ready.json`, or None.

- [ ] **Step 1: Write the failing tests** in `tests/test_updates.py`.
  - **Test setup:** a temp `root` and `state_path`, a fake `clock`, and `http.opener` patched to answer `LATEST_URL` with `{"tag_name": …, "html_url": "https://github.com/rgaspary/TheCollector/releases/tag/v2.1.0"}`. The opener counts its calls.
  - `test_parse`:
    - `parse_tag("v2.1.0") == (2, 1, 0)`
    - `parse_tag("2.1.0") is None`, `parse_tag("v2.1") is None`, `parse_tag("v2.1.0-rc1") is None`
    - `parse_version("2.0.0-dev") == (2, 0, 0)`
  - `test_newer_release_shows`: current `"2.0.0"`, tag `v2.1.0` → `info()` includes `latest == "2.1.0"`, `show is True`, `state == "idle"`, `git is False`, and `url` is the html_url.
  - `test_same_or_older_release_hidden`: tag `v2.0.0`, then a new Updater with tag `v1.9.0` → `show is False` both times.
  - `test_checks_once_a_day`: two `info()` calls at clock 0 and 3600 → opener called once. At `CHECK_EVERY + 1` → called twice.
  - `test_failed_check_waits_a_day`: the opener raises `HTTPError` 403 → `show is False` and `error is None`. A second `info()` at clock 3600 doesn't call the opener. A body without `tag_name` gives the same result.
  - `test_skip_hides_until_newer`:
    - `skip("2.1.0")` → `show is False`.
    - A fresh `Updater` on the same state file (tag still v2.1.0) → `show is False`.
    - Tag `v2.2.0` after 24 h → `show is True`.
  - `test_corrupt_state_file_is_ignored`: `state_path.write_text("{nope")` → `info()` returns normally with `show is True`.
  - `test_git_checkout_flagged`: `(root / ".git").mkdir()` → `info()["git"] is True`.
  - `test_ready_update_hides_popup`: write `root/.update/ready.json` = `{"version": "2.1.0", "folder": "staging-2.1.0"}` → `ready_version() == "2.1.0"`, `info()["state"] == "ready"`, `show is False`.
- [ ] **Step 2: Run** `python3 -m unittest tests.test_updates -v`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement** the constants, `parse_tag`, `parse_version`, `UpdateError` and `Updater`.
  - Use `http.request_json("GET", LATEST_URL)`, and catch `HttpError` and malformed bodies.
  - Persist state with `atomic_write` (a JSON dict). A missing or corrupt file means `{}`.
  - Guard state changes with a `threading.Lock`.
- [ ] **Step 4: Run** `python3 -m unittest tests.test_updates -v`. Expected: PASS.
- [ ] **Step 5: Commit:** `git commit -m "feat: check GitHub for a newer release, with skip"`

### Task 3: Download, unpack, check and stage

**Files:**
- Modify: `collector/updates.py`
- Test: `tests/test_updates.py`

**Interfaces:**
- Consumes: `http.download` (Task 1), `Updater` (Task 2).
- Produces:
  - `extract_release(tar_path: Path, dest: Path) -> Path`: unpacks safely and returns the single top-level folder inside `dest`. Raises `UpdateError("The download looks damaged. Try again later.")` for:
    - absolute paths, `..`, or links pointing outside;
    - device files;
    - not exactly one top-level folder.
  - `verify_staged(folder: Path, version: str) -> None`: raises `UpdateError` when `collector/__init__.py` doesn't contain `__version__ = "<version>"`, or when `subprocess.run([sys.executable, "-I", "-c", "import sys; sys.path.insert(0, '.'); import collector.web, collector.__main__"], cwd=folder, timeout=60)` exits non-zero. `-I` keeps the running app's own folder off the path, so only the staged copy is imported.
  - `Updater.start_download() -> dict`: unless the install is a git checkout, already downloading, or already ready, starts a daemon thread running `stage()`. Returns `info()`. In a git checkout it raises `UpdateError("This copy is a git checkout. Update it with git.")`.
  - `Updater.stage() -> None`: runs synchronously and sets `state` and `error`. Tests call it directly. Steps:
    - download the tarball to `.update/download-<version>.tar.gz`;
    - extract it into `.update/staging-<version>/`;
    - verify it;
    - write `ready.json` as `{"version", "folder"}` (folder is relative to `.update`);
    - delete the tarball.
    - **On any failure:** remove the staging folder and the tarball, set `state = "failed"`, and set `error` to the `UpdateError` message. A network `HttpError` maps to "Couldn't reach GitHub. Check your internet connection and try again."

- [ ] **Step 1: Write the failing tests.**
  - **Test helper:** `make_release(dir, version, *, extra=None, broken=False) -> Path` writes a `.tar.gz` with one top folder `rgaspary-TheCollector-abc123/`. It contains:
    - `collector/__init__.py` with the version line (and a `raise SystemExit(1)` if `broken`);
    - empty `collector/web.py` and `collector/__main__.py`;
    - `collector-launch.sh` with mode `0o755`.
  - The fake opener serves this file for the tarball URL, with `geturl()` on `codeload.github.com`.
  - `test_stage_success`: `stage()` → `state == "ready"`, `ready_version() == "2.1.0"`, `(root/".update/staging-2.1.0/collector-launch.sh").stat().st_mode & 0o111`, and no `download-*` file left.
  - `test_unsafe_members_rejected`: tarballs with the members `../evil`, `/abs`, and a symlink to `/etc/passwd`. `extract_release` raises `UpdateError` for each, and nothing appears outside `dest`.
  - `test_broken_release_not_staged`: `broken=True` → `state == "failed"`, `ready_version() is None`, no `staging-*` folder.
  - `test_wrong_version_not_staged`: the tarball says 2.0.9 when 2.1.0 is expected → `failed`.
  - `test_network_error_message`: the opener raises `URLError` → `error == "Couldn't reach GitHub. Check your internet connection and try again."`.
  - `test_unwritable_folder_fails_cleanly`: patch `updates.extract_release` to raise `OSError(28, "No space left on device")` → `state == "failed"`, `error` is a plain sentence (no errno text), and no `staging-*`.
  - `test_git_checkout_refuses_download`: with `.git` present, `start_download()` raises `UpdateError`.
- [ ] **Step 2: Run** `python3 -m unittest tests.test_updates -v`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement.** Use `tarfile.open(...).extractall(dest, filter="data")` when `hasattr(tarfile, "data_filter")`. Otherwise, check every member by hand: reject `isdev()`, absolute or `..` names, and links whose resolved target leaves `dest`. Do the hand check either way before extracting, so the error message is the same. OSError → "Couldn't save the update. Check that there's free space on your disk and try again."
- [ ] **Step 4: Run** `python3 -m unittest tests.test_updates -v`. Expected: PASS.
- [ ] **Step 5: Commit:** `git commit -m "feat: download and check a release before using it"`

### Task 4: Swap at start-up, clean-up, restart

**Files:**
- Modify: `collector/updates.py`, `collector/__main__.py`, `collector/web.py:600-601` (`serve` keeps its signature)
- Test: `tests/test_updates.py`, `tests/test_main.py`

**Interfaces:**
- Consumes: the `ready.json` format from Task 3.
- Produces:
  - `apply_staged(root: Path) -> bool`.
    - **When `ready.json` is valid:** move each top-level entry of `root` (except `KEEP`) into `.update/previous-<current __version__>/`, move each top-level entry of the staging folder into `root`, delete `ready.json` and the empty staging folder, then return True.
    - **When it isn't:** return False. A missing `ready.json` deletes any `staging-*` and `download-*` leftovers. A bad `ready.json` is deleted too.
    - **If any move fails:** move everything back, delete `ready.json` and the staging folder, print the reason, and return False.
  - `cleanup_previous(root: Path) -> None`: deletes `.update/previous-*` (with `shutil.rmtree`, ignoring errors).
  - `restart(argv: list[str]) -> NoReturn`: `os.execv(sys.executable, [sys.executable, "-m", "collector", *argv_with_no_browser])`, where `argv_with_no_browser` is `argv` plus `"--no-browser"` if it isn't already there.
  - `App.restart_requested: bool` (default False) in `web.py`.
  - In `__main__.main`:
    - At the very top: `if updates.apply_staged(config.ROOT): updates.restart(argv)`.
    - It builds the `App` itself and passes it to `serve(cfg, app)`.
    - Right after the server is bound: `updates.cleanup_previous(config.ROOT)`.
    - After `serve_forever` returns and the socket is closed: `if app.restart_requested: updates.restart(argv)`.

- [ ] **Step 1: Write the failing tests.**
  - `test_apply_swaps_and_keeps_settings`:
    - **Set up** `root` with `collector/old.py`, `config.toml` = "mine", `collector.log`, `.git/` and `static/`, plus a staged `.update/staging-2.1.0/` holding `collector/new.py` and `static/`, and a `ready.json`.
    - **Expect** `apply_staged(root) is True`, `root/collector/new.py` exists, `root/collector/old.py` doesn't, `config.toml` still reads "mine", `.git` is untouched, `ready.json` is gone, and `.update/previous-<__version__>/collector/old.py` exists.
  - `test_apply_rolls_back_on_failure`: patch `os.replace` (or `Path.rename`, whichever the code uses) to raise `OSError` on the 2nd call → returns False, the original files are back in place, and `ready.json` is gone.
  - `test_leftover_staging_without_ready_is_removed`: `.update/staging-2.1.0/` with no `ready.json` → returns False and the folder is gone.
  - `test_nothing_staged`: no `.update` → returns False and nothing is created.
  - `test_cleanup_previous`: removes `.update/previous-2.0.0/`.
  - `test_restart_adds_no_browser`: patch `os.execv` → called with `[sys.executable, "-m", "collector", "--no-browser"]` for `argv=[]`, with no duplicate when already present.
  - In `tests/test_main.py`, patch `updates.apply_staged`, `updates.restart` and `updates.cleanup_previous`:
    - `test_staged_update_restarts_before_serving`: `apply_staged` returns True → `restart` is called and `serve` is not.
    - `test_restart_requested_execs_after_shutdown`: start `main(["--no-browser"])` in a thread on port 0 config. Set `app.restart_requested = True`, call `server.shutdown()`, and expect `restart` to be called once with `["--no-browser"]`.
      - To get at the app, patch `web.App` to capture the instance, or expose `serve`'s server via a patched `serve`. Use whichever the existing test_main helpers make easier.
- [ ] **Step 2: Run** `python3 -m unittest tests.test_updates tests.test_main -v`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement** `apply_staged`, `cleanup_previous` and `restart`, and wire `__main__`. Record each completed move in a list, so a rollback undoes them in reverse.
- [ ] **Step 4: Run** `python3 -m unittest discover tests`. Expected: everything passes (the 255 existing tests plus the new ones).
- [ ] **Step 5: Commit:** `git commit -m "feat: put a staged update in place at start-up and restart on request"`

### Task 5: Update endpoints

**Files:**
- Modify: `collector/web.py` (add `updater: Updater` to `App` with `field(default_factory=Updater)`, the GET route next to `/api/status`, and the POST routes in the `routes` dict)
- Test: `tests/test_web.py`

**Interfaces:**
- Consumes: `Updater.info/skip/start_download` (Tasks 2–3), `App.restart_requested` (Task 4).
- Produces (the frontend's contract):
  - `GET /api/update` → `Updater.info()`.
  - `POST /api/update/download` → `info()`. An `UpdateError` returns `{"error": msg}` with status 409.
  - `POST /api/update/skip {version: str}` → `info()`. A non-string `version` returns 400.
  - `POST /api/update/restart` → `{"ok": true}`, then sets `app.restart_requested = True` and calls `server.shutdown()` in a thread (same pattern as `/api/shutdown`).

- [ ] **Step 1: Write the failing tests** in a new `class Updates(ApiTest)`.
  - **Test setup:** `ApiTest.setUp` passes `updater=Updater(root=d/"install", state_path=d/"update.json")` to `web.App`. Add that keyword to the existing `web.App(...)` call. Patch `http.opener` to serve `v2.1.0`.
  - `test_update_info`: `GET /api/update` → 200 and `show is True`.
  - `test_skip`: `POST /api/update/skip {"version": "2.1.0"}` → `show is False`. `{"version": 5}` → 400.
  - `test_download_refused_for_git_checkout`: create `install/.git` → `POST /api/update/download` returns 409 with the git message.
  - `test_update_posts_need_same_origin`: `POST /api/update/restart` with header `Origin: http://evil.example` → 403, and `restart_requested` stays False.
  - `test_restart_sets_flag`: same-origin POST → 200, and `app.restart_requested is True` (wait up to 2 s for `serve_forever` to stop).
- [ ] **Step 2: Run** `python3 -m unittest tests.test_web -v`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement** the routes. The App methods `update_info`, `update_download(body)`, `update_skip(body)` and `update_restart` follow the existing `routes` style.
  - Handle `/api/update/restart` in `do_POST` beside `/api/shutdown`, after `_same_origin`, because it needs `self.server`.
- [ ] **Step 4: Run** `python3 -m unittest discover tests`. Expected: all PASS.
- [ ] **Step 5: Commit:** `git commit -m "feat: update check, download, skip and restart endpoints"`

### Task 6: Popups, ready line, docs

**Files:**
- Create: `static/js/update.js`
- Modify:
  - `static/js/main.js`: after `renderLibraryBadge()` in `start()`, call `checkForUpdate()` without awaiting it.
  - `static/index.html`: add `<p id="update-badge" class="account" hidden></p>` after `#library-badge`.
  - `static/style.css`: dialog styles using the existing variables.
  - `CHANGELOG.md`: a new `## Unreleased` section with `### Added`.
  - `README.md`: one short paragraph.
- Test: manual, in the running app (there are no JS unit tests in this project).

**Interfaces:**
- Consumes: the Task 5 endpoints. `get` and `post` come from `api.js`, and `$` and `esc` from `ui.js`.
- Produces: `export async function checkForUpdate(): Promise<void>`. It never throws; any error is ignored silently.

- [ ] **Step 1: Implement `update.js`.**
  - **Showing the popup:** `GET /api/update`. If `show`, open a `<dialog>` (`showModal()`, `aria-labelledby` on its heading) with the notice layout from the spec.
    - The "What's new ↗" link uses `target="_blank" rel="noopener"`, which the GTK window already hands to the browser.
    - In a git checkout (`git: true`), replace the Update button with the git sentence.
  - **✕ and Escape:** both close the popup. If "Skip this version" is ticked, `POST /api/update/skip {version: latest}` first.
  - **Update now:**
    - Clear any skip with `POST /api/update/skip {version: ""}` if the box was ticked.
    - Then `POST /api/update/download`, disable the button and change its label to "Updating…".
    - Poll `GET /api/update` every second until `state` is `ready` or `failed`.
    - On `failed`, show `error` and a "Try again" button that repeats the download.
  - **Ready:** swap the dialog body for the ready layout.
    - "Keep working" closes the dialog and shows the ready line.
    - "Close and restart": `POST /api/update/restart`, show "Restarting…", then poll `/api/status` every second. When the answered `version` equals `latest`, call `location.reload()`. After 60 s, show "TheCollector didn't come back. Open it again from your app menu."
  - **On page load with `state == "ready"`:** show only the ready line in `#update-badge`: "TheCollector <v> is ready · " plus a Restart `button.link` that runs the same restart flow.
- [ ] **Step 2: CSS.** Add `dialog.update` with `background: var(--card)`, `color: var(--text)`, `border: 1px solid var(--line)`, `border-radius: 10px`, `max-width: 28rem`, and a `::backdrop` dim. Lay out the version lines in two columns. It must look right in both light and dark themes.
- [ ] **Step 3: Manual check.**
  - **Setup:**
    - Copy the working tree without `.git` into a scratch folder, and set its `collector/__init__.py` to `__version__ = "1.9.0"`.
    - Run it there with `COLLECTOR_CONFIG` pointing at a scratch config and a free port.
    - Set `XDG_DATA_HOME` to a scratch folder too, so your real data folder isn't touched.
  - **Expect:**
    - The popup shows Installed 1.9.0 and Available 2.0.0.
    - Ticking Skip and then ✕ means no popup after a reload.
    - Clearing `skipped` in `update.json` brings the popup back.
    - Update now leads to the ready popup. "Close and restart" reloads on 2.0.0, and `.update/previous-1.9.0/` is gone.
  - **Separately, run the real checkout:** the popup shows the git sentence instead of Update.
- [ ] **Step 4: Docs.**
  - **CHANGELOG `## Unreleased` / `### Added`:** "TheCollector tells you when a new version is out and installs it with one click. You can restart right away or keep working and switch over the next time you open it. "Skip this version" hides the notice until a newer one comes out."
  - **README:** add a section "Updates" with 2–3 sentences in the same voice.
- [ ] **Step 5: Run** `python3 -m unittest discover tests` and `uvx ruff check collector tests`. Expected: all pass, no new lint.
- [ ] **Step 6: Commit:** `git commit -m "feat: update popups and ready line; changelog and readme"`
