// Screen 0: which music app's library to match against. Shown on first run and from "Change".
import { get, post } from "../api.js";
import { renderLibraryBadge } from "../header.js";
import { back, canGoBack, go } from "../router.js";
import { arrowKeys, busy, esc, iconHTML, showError } from "../ui.js";

let libraries = null;
let chosen = null;        // library id picked on this screen
const typed = {};         // id → {path, folders}: what was typed, kept when switching tiles

function draft(lib, state) {
  if (!typed[lib.id]) {
    const current = state.library && state.library.id === lib.id ? state.library : null;
    typed[lib.id] = {
      path: current ? current.path : (lib.detected_path || ""),
      folders: current && current.folders.length ? [...current.folders]
        : (lib.needs === "folders" && lib.detected_path ? [lib.detected_path] : [""]),
    };
  }
  return typed[lib.id];
}

function body(lib, d) {
  return lib.needs === "folders"
    ? { id: lib.id, folders: d.folders.map((f) => f.trim()).filter(Boolean) }
    : { id: lib.id, path: d.path.trim() };
}

function detailHTML(lib, d) {
  const input = lib.needs === "folders"
    ? `<label>Music folders</label>
       <div class="folder-list">${d.folders.map((f, i) => `
         <div class="row"><input type="text" data-folder="${i}" value="${esc(f)}" placeholder="/home/you/Music"
             aria-label="Music folder ${i + 1}">
           ${d.folders.length > 1 ? `<button type="button" data-remove="${i}" aria-label="Remove folder ${i + 1}">Remove</button>` : ""}
         </div>`).join("")}</div>
       <button type="button" class="link add-folder" data-add>+ Add folder</button>`
    : `<label for="lib-path">Library file</label>
       <input type="text" id="lib-path" value="${esc(d.path)}" placeholder="${esc(lib.detected_path || "Full path to the file")}">
       ${lib.detected_path ? "" : '<p class="muted small">TheCollector didn\'t find it in the usual place, so type or paste its location.</p>'}`;
  return `<div class="lib-detail">
      <p>${esc(lib.help_text)}</p>
      ${input}
      <div class="result" aria-live="polite"></div>
    </div>`;
}

export const libraryScreen = {
  // Each visit starts from the saved choice, with freshly detected paths.
  async render(el, state) {
    libraries = null;
    chosen = state.library && state.library.configured ? state.library.id : null;
    return draw(el, state);
  },
};

async function draw(el, state) {
  if (!libraries) {
    try {
      libraries = await get("/api/libraries");
    } catch (err) {
      showError(err.message);
      return;
    }
  }
  const lib = libraries.find((l) => l.id === chosen);
  const d = lib ? draft(lib, state) : null;

  el.innerHTML = `<div class="card">
    <h2>Your music library</h2>
    <p class="muted">Which app keeps your music? TheCollector matches playlists against it. It only reads the library and never changes it.</p>
    <div class="tiles" role="radiogroup" aria-label="Music library">
      ${libraries.map((l) => `
        <button type="button" class="tile${l.id === chosen ? " selected" : ""}" data-id="${esc(l.id)}"
            role="radio" aria-checked="${l.id === chosen}">
          <span class="tile-icon">${iconHTML("apps", l.icon)}</span>
          <span class="tile-name">${esc(l.name)}</span>
          ${l.subtitle ? `<span class="tile-sub">${esc(l.subtitle)}</span>` : ""}
        </button>`).join("")}
    </div>
    ${lib ? detailHTML(lib, d) : ""}
    <div class="nav">
      ${canGoBack() ? '<button type="button" data-back>Back</button>' : ""}
      ${lib ? '<button type="button" data-test>Test</button>' : ""}
      <button type="button" class="primary" data-save ${lib ? "" : "disabled"}>Save &amp; continue</button>
    </div></div>`;

  const grid = el.querySelector(".tiles");
  arrowKeys(grid);
  grid.querySelectorAll(".tile").forEach((tile) => tile.addEventListener("click", async () => {
    chosen = tile.dataset.id;
    await draw(el, state);
    el.querySelector(`.tile[data-id="${chosen}"]`)?.focus();
  }));
  el.querySelector("[data-back]")?.addEventListener("click", () => back());
  if (!lib) return;

  // Keep what's typed when tiles or folder rows are re-rendered.
  el.querySelector("#lib-path")?.addEventListener("input", (e) => { d.path = e.target.value; });
  el.querySelectorAll("[data-folder]").forEach((input) =>
    input.addEventListener("input", () => { d.folders[+input.dataset.folder] = input.value; }));
  el.querySelector("[data-add]")?.addEventListener("click", async () => {
    d.folders.push("");
    await draw(el, state);
    el.querySelector(`[data-folder="${d.folders.length - 1}"]`)?.focus();
  });
  el.querySelectorAll("[data-remove]").forEach((btn) => btn.addEventListener("click", async () => {
    d.folders.splice(+btn.dataset.remove, 1);
    await draw(el, state);
  }));

  const result = el.querySelector(".result");
  el.querySelector("[data-test]").addEventListener("click", async (e) => {
    const done = busy(e.target, "Testing…");
    result.className = "result";
    result.textContent = "";
    try {
      const r = await post("/api/library/test", body(lib, d));
      result.className = `result ${r.ok ? "ok" : "bad"}`;
      result.innerHTML = r.ok ? `✓ ${esc(r.message)}` : `${esc(r.error)}${r.fix ? `<br><span>${esc(r.fix)}</span>` : ""}`;
    } catch (err) {
      result.className = "result bad";
      result.textContent = err.message;
    } finally {
      done();
    }
  });
  el.querySelector("[data-save]").addEventListener("click", async (e) => {
    const done = busy(e.target, "Saving…");
    try {
      const r = await post("/api/library", body(lib, d));
      state.library = r.library;
      renderLibraryBadge();
      await go("source");
    } catch (err) {
      showError(err.message);
    } finally {
      done();
    }
  });
}
