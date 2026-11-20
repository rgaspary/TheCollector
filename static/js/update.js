// Telling the person a new version is out, installing it, and restarting onto it.
import { get, post } from "./api.js";
import { $, esc } from "./ui.js";

const WAIT_FOR_RESTART_MS = 60000;
let dialog = null;
let info = null;
let restarting = false;
let installing = false;

function readyLine() {
  const el = $("#update-badge");
  el.hidden = false;
  el.innerHTML = `TheCollector ${esc(info.latest)} is ready · <button type="button" class="link" id="update-restart">Restart to use it</button>`;
  $("#update-restart").onclick = restart;
}

// Put keyboard focus on the main button after the dialog's contents are swapped.
function focusMain() {
  const button = $("button.primary", dialog) || $("button", dialog);
  if (button) button.focus();
}

function closeDialog() {
  if (dialog) dialog.close();
}

function open() {
  if (dialog) return;
  dialog = document.createElement("dialog");
  dialog.className = "update";
  dialog.setAttribute("aria-labelledby", "update-title");
  // Escape does the same as the cross, and is ignored while updating or restarting.
  dialog.addEventListener("cancel", (e) => {
    e.preventDefault();
    if (!restarting && !installing) dismiss();
  });
  dialog.addEventListener("close", () => {
    dialog.remove();
    dialog = null;
  });
  document.body.append(dialog);
  dialog.showModal();
}

async function dismiss() {
  if (restarting || installing) return;
  const box = $("#update-skip");
  if (box && box.checked) {
    try {
      await post("/api/update/skip", { version: info.latest });
    } catch { /* closing matters more than remembering the skip */ }
  }
  closeDialog();
}

function notice(error = "") {
  open();
  const action = info.git
    ? `<p class="update-git">This copy is a git checkout. Update it with git.</p>`
    : `<button type="button" class="primary" id="update-now">${error ? "Try again" : "Update now"}</button>`;
  dialog.innerHTML = `
    <h2 id="update-title">A new version of TheCollector is available</h2>
    <dl class="update-versions">
      <dt>Installed:</dt><dd>${esc(info.current)}</dd>
      <dt>Available:</dt><dd>${esc(info.latest)} <a href="${esc(info.url)}" target="_blank" rel="noopener">What's new ↗</a></dd>
    </dl>
    ${error ? `<p class="error" role="alert">${esc(error)}</p>` : ""}
    ${action}
    <div class="update-foot">
      <label class="update-skip"><input type="checkbox" id="update-skip"> Skip this version</label>
      <button type="button" id="update-close" aria-label="Close">✕</button>
    </div>`;
  $("#update-close", dialog).onclick = dismiss;
  const now = $("#update-now", dialog);
  if (now) now.onclick = () => install(now);
  focusMain();
}

async function install(button) {
  installing = true;
  button.disabled = true;
  button.textContent = "Updating…";
  $("#update-close", dialog).disabled = true;
  try {
    // Pressing Update un-skips, so a failed try still offers itself next time.
    if ($("#update-skip", dialog).checked) await post("/api/update/skip", { version: "" });
    info = { ...info, ...(await post("/api/update/download")) };
    while (info.state !== "ready" && info.state !== "failed") {
      await new Promise((r) => setTimeout(r, 1000));
      info = { ...info, ...(await get("/api/update")) };
    }
  } catch (err) {
    installing = false;
    return notice(err.message);
  }
  installing = false;
  if (info.state === "failed") return notice(info.error || "The update didn't finish. Please try again.");
  ready();
}

function ready() {
  open();
  dialog.innerHTML = `
    <h2 id="update-title">TheCollector ${esc(info.latest)} is ready</h2>
    <p>Restart now to start using it, or keep working and it will switch over the next time you open TheCollector.</p>
    <div class="update-buttons">
      <button type="button" class="primary" id="update-restart-now">Close and restart</button>
      <button type="button" id="update-keep">Keep working</button>
    </div>`;
  $("#update-restart-now", dialog).onclick = () => restart();
  $("#update-keep", dialog).onclick = () => {
    closeDialog();
    readyLine();
  };
  focusMain();
}

async function restart() {
  restarting = true;
  open();
  dialog.innerHTML = `<h2 id="update-title">Restarting…</h2><p class="update-wait" role="status">Restarting…</p>`;
  try {
    await post("/api/update/restart");
  } catch (err) {
    restarting = false;
    return notice(err.message);
  }
  const until = Date.now() + WAIT_FOR_RESTART_MS;
  while (Date.now() < until) {
    await new Promise((r) => setTimeout(r, 1000));
    try {
      const status = await get("/api/status");
      if (status.version === info.latest) return location.reload();
    } catch { /* the app is down for a moment while it restarts */ }
  }
  restarting = false;  // nothing more will happen, so let Escape and the button close this
  dialog.innerHTML = `<h2 id="update-title">Restarting…</h2><p class="error">TheCollector didn't come back. Open it again from your app menu.</p>
    <button type="button" class="primary" id="update-gone">Close</button>`;
  $("#update-gone", dialog).onclick = closeDialog;
  focusMain();
}

export async function checkForUpdate() {
  try {
    info = await get("/api/update");
    if (info.state === "ready") readyLine();
    else if (info.show) notice();
  } catch { /* an update check must never get in the way */ }
}
