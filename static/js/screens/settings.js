// Settings: the music library, each service's login, and where files are saved. Opened from the header.
import { get, post } from "../api.js";
import { folderRow, wireBrowse } from "../browse.js";
import { renderLibraryBadge } from "../header.js";
import { back, canGoBack, go } from "../router.js";
import { busy, esc, iconHTML, showError, showNotice } from "../ui.js";

const STATUS = {
  ready: ["Connected", "ok"],
  needs_setup: ["Not set up", "setup"],
  invalid: ["Needs attention", "bad"],
};

function libraryLine(lib) {
  if (!lib || !lib.configured) return '<p class="muted">No library chosen yet.</p>';
  const where = lib.folders && lib.folders.length ? lib.folders.join(", ") : lib.path;
  return `<p><b>${esc(lib.name)}</b>${where ? `<br><span class="muted small path">${esc(where)}</span>` : ""}</p>`;
}

// Spotify's logo already spells its name (and must be shown whole), so the name is for screen readers only.
const WORDMARKS = new Set(["spotify.svg"]);

function serviceRow(s) {
  const set = s.status.state !== "needs_setup" || Object.values(s.values).some((v) => v.set || v.value);
  let [label, cls] = STATUS[s.status.state] || ["", ""];
  if (s.status.state === "needs_setup" && set) label = s.uses_oauth ? "Not signed in" : "Not finished";
  return `<li class="service-row" data-id="${esc(s.id)}">
      <span class="tile-icon small">${iconHTML("services", s.icon)}</span>
      <span class="service-name"><b class="${WORDMARKS.has(s.icon) ? "sr-only" : ""}">${esc(s.name)}</b> <span class="badge ${cls}">${esc(label)}</span>
        ${s.status.state === "invalid" && s.status.error ? `<br><span class="muted small">${esc(s.status.error)}</span>` : ""}</span>
      <span class="service-actions">
        ${s.setup_steps.length ? `<button type="button" class="link" data-guide>How to set up</button>` : ""}
        ${set ? `<button type="button" data-disconnect>Disconnect</button>` : ""}
        <button type="button" ${set ? "" : 'class="primary"'} data-setup>${set ? "Change" : "Set up"}</button>
      </span>
    </li>`;
}

export const settingsScreen = {
  async render(el, state) {
    let sources;
    try {
      [sources, state.status] = await Promise.all([get("/api/sources"), get("/api/status")]);
    } catch (err) {
      showError(err.message);
      return;
    }
    state.library = state.status.library;

    el.innerHTML = `<div class="card settings">
      <h2>Settings</h2>

      <section>
        <h3>Music library</h3>
        <p class="muted small">The music TheCollector matches playlists against. It only reads it.</p>
        ${libraryLine(state.library)}
        <button type="button" data-library>Change library</button>
      </section>

      <section>
        <h3>Music services</h3>
        <p class="muted small">Your API keys and logins are kept on this computer, readable only by you.</p>
        <ul class="services">${sources.map(serviceRow).join("")}</ul>
      </section>

      <section>
        <h3>Where files are saved</h3>
        <p class="muted small">Where the Export and Missing steps start. You can still pick another folder each time.</p>
        <label for="set-playlist-dir">Playlists</label>
        ${folderRow("set-playlist-dir", esc(state.status.playlist_dir))}
        <label for="set-missing-dir">Missing-song lists</label>
        ${folderRow("set-missing-dir", esc(state.status.missing_dir))}
        <div class="result" aria-live="polite"></div>
        <button type="button" data-save-folders>Save folders</button>
      </section>

      <div class="nav">
        <button type="button" data-back>Back</button>
      </div></div>`;

    el.querySelector("[data-library]").addEventListener("click", () => {
      state.returnTo = "settings";
      go("library");
    });

    el.querySelectorAll(".service-row").forEach((row) => {
      const info = sources.find((s) => s.id === row.dataset.id);
      row.querySelector("[data-setup]").addEventListener("click", () => {
        state.source = info.id;
        state.sourceInfo = info;
        state.returnTo = "settings";
        go("credentials");
      });
      row.querySelector("[data-guide]")?.addEventListener("click", () => {
        state.helpFor = info.id;
        go("help");
      });
      row.querySelector("[data-disconnect]")?.addEventListener("click", async (e) => {
        if (!confirm(`Remove your saved ${info.name} settings from this computer?`)) return;
        const done = busy(e.target, "Removing…");
        try {
          await post(`/api/sources/${info.id}/disconnect`);
          showNotice(`${info.name} is disconnected.`);
          await settingsScreen.render(el, state);
        } catch (err) {
          showError(err.message);
          done();
        }
      });
    });

    wireBrowse(el);
    const result = el.querySelector(".result");
    el.querySelector("[data-save-folders]").addEventListener("click", async (e) => {
      const done = busy(e.target, "Saving…");
      result.className = "result";
      result.textContent = "";
      try {
        const saved = await post("/api/settings/folders", {
          playlist_dir: el.querySelector("#set-playlist-dir").value.trim(),
          missing_dir: el.querySelector("#set-missing-dir").value.trim(),
        });
        Object.assign(state.status, saved);
        result.className = "result ok";
        result.textContent = "✓ Saved. New exports start in these folders.";
      } catch (err) {
        result.className = "result bad";
        result.textContent = err.message;
      } finally {
        done();
      }
    });
    el.querySelector("[data-back]").addEventListener("click", () => {
      if (canGoBack()) back();
      else go(state.library.configured ? "source" : "library", { direction: "back" });
    });
    renderLibraryBadge();
  },
};
