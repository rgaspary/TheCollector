// Screen 4: save the matched playlist for the app the user will open it in.
import { get, post } from "../api.js";
import { handleApiError } from "../errors.js";
import { folderRow, wireBrowse } from "../browse.js";
import { back, go } from "../router.js";
import { arrowKeys, busy, esc, iconHTML, showError } from "../ui.js";

const LAST_PLAYER = "thecollector.player";
const STYLES = [
  ["absolute", "Full paths", "Works on this computer."],
  ["relative", "Relative to the folder", "Works if you copy the music and the playlist to another computer or a portable player together."],
  ["name", "File names only", "For players that look the files up themselves."],
];

let info = null;          // GET /api/players
let choice = null;        // {player, formats:Set, style, folder, folderEdited, showAll}

// Where playlists go unless the user picks another folder: the Playlists folder inside Music.
function defaultFolder(state) {
  return state.status.playlist_dir;
}

function pickPlayer(state, key) {
  const player = info.players.find((p) => p.key === key);
  choice.player = key;
  choice.style = player.path_style;
  choice.formats = new Set([player.recommended]);
  if (!choice.folderEdited) choice.folder = defaultFolder(state);
  try { localStorage.setItem(LAST_PLAYER, key); } catch { /* private mode */ }
}

function nextAfterExport(state) {
  return state.resolved && state.resolved.missing ? "missing" : "done";
}

export async function finishWithoutMissing(state) {
  // Nothing missing: still tick off songs in the NextUp note that are now in the library.
  if (state.status.nextup_enabled) {
    try {
      state.missingResult = await post("/api/export/missing", { analysis_id: state.analysis.analysis_id, nextup: true });
    } catch (err) {
      showError(err.message);
    }
  }
  return go("done");
}

function draw(el, state) {
  const players = info.players.filter((p) => p.platforms.includes(state.status.platform) || p.key === "other");
  const player = info.players.find((p) => p.key === choice.player);
  const fmtLabel = (key) => info.formats.find((f) => f.key === key);
  const shown = choice.showAll ? info.formats.map((f) => f.key) : [player.recommended, ...player.also];

  el.innerHTML = `<div class="card">
    <h2>Which app will you open this in?</h2>
    <p class="muted">${state.resolved.matched} song${state.resolved.matched === 1 ? "" : "s"} from your library ${state.resolved.matched === 1 ? "goes" : "go"} into the playlist.</p>
    <div class="tiles players" role="radiogroup" aria-label="Music app">
      ${players.map((p) => `<button type="button" class="tile${p.key === choice.player ? " selected" : ""}" role="radio"
          aria-checked="${p.key === choice.player}" data-player="${esc(p.key)}">
        <span class="tile-icon">${iconHTML("apps", p.icon)}</span><span class="tile-name">${esc(p.name)}</span></button>`).join("")}
    </div>
    <div class="steps-box"><b>How to open it in ${esc(player.name)}:</b> ${esc(player.steps)}</div>

    <fieldset class="formats"><legend>Format</legend>
      ${shown.map((key) => {
        const f = fmtLabel(key);
        return `<label class="check"><input type="checkbox" value="${esc(key)}" ${choice.formats.has(key) ? "checked" : ""}>
          ${esc(f.label)} <span class="muted">(${esc(f.ext)})</span>${key === player.recommended ? ' <span class="tag">best for this app</span>' : ""}</label>`;
      }).join("")}
      <button type="button" class="link" data-all>${choice.showAll ? "Show fewer formats" : "Show all formats"}</button>
    </fieldset>

    <fieldset class="styles"><legend>Song locations in the file</legend>
      ${STYLES.map(([key, label, hint]) => `<label class="check"><input type="radio" name="style" value="${key}"
          ${choice.style === key ? "checked" : ""}> ${esc(label)} <span class="muted">— ${esc(hint)}</span></label>`).join("")}
      ${shown.includes("itunes_xml") && choice.formats.has("itunes_xml") ? '<p class="muted small">iTunes / Music XML always uses full paths; Apple\'s apps need them.</p>' : ""}
    </fieldset>

    <label for="export-folder">Save to folder</label>
    ${folderRow("export-folder", esc(choice.folder))}

    <div class="nav">
      <button type="button" data-back>Back</button>
      <button type="button" data-skip>Skip</button>
      <button type="button" class="primary" data-export>Export</button>
    </div></div>`;

  arrowKeys(el.querySelector(".players"));
  el.querySelectorAll("[data-player]").forEach((t) => t.addEventListener("click", () => {
    pickPlayer(state, t.dataset.player);
    draw(el, state);
    el.querySelector(`[data-player="${t.dataset.player}"]`)?.focus();
  }));
  el.querySelectorAll(".formats input").forEach((c) => c.addEventListener("change", () => {
    if (c.checked) choice.formats.add(c.value); else choice.formats.delete(c.value);
    el.querySelector("[data-export]").disabled = choice.formats.size === 0;
  }));
  el.querySelector("[data-all]").addEventListener("click", () => {
    choice.showAll = !choice.showAll;
    draw(el, state);
    el.querySelector("[data-all]").focus();
  });
  el.querySelectorAll(".styles input").forEach((r) => r.addEventListener("change", () => { choice.style = r.value; }));
  el.querySelector("#export-folder").addEventListener("input", (e) => {
    choice.folder = e.target.value;
    choice.folderEdited = true;
  });
  wireBrowse(el);
  el.querySelector("[data-back]").addEventListener("click", () => back());
  el.querySelector("[data-skip]").addEventListener("click", () => {
    state.exportResult = null;
    if (nextAfterExport(state) === "done") finishWithoutMissing(state); else go("missing");
  });
  const exportBtn = el.querySelector("[data-export]");
  exportBtn.disabled = choice.formats.size === 0;
  exportBtn.addEventListener("click", async () => {
    showError("");
    const done = busy(exportBtn, "Exporting…");
    try {
      state.exportResult = await post("/api/export/playlist", {
        analysis_id: state.analysis.analysis_id,
        formats: info.formats.map((f) => f.key).filter((k) => choice.formats.has(k)),
        path_style: choice.style,
        folder: choice.folder.trim(),
      });
      state.exportResult.player = player.name;
      state.exportResult.steps = player.steps;
      if (nextAfterExport(state) === "done") await finishWithoutMissing(state); else await go("missing");
    } catch (err) {
      await handleApiError(err);
    } finally {
      done();
      exportBtn.disabled = choice.formats.size === 0;
    }
  });
}

export const exportScreen = {
  async render(el, state) {
    if (!state.resolved) return go("review", { direction: "back" });
    const fresh = !choice || choice.analysisId !== state.analysis.analysis_id;
    if (!info || fresh) {  // the default app follows the library, which may have changed
      try {
        info = await get("/api/players");
      } catch (err) {
        showError(err.message);
        return;
      }
    }
    if (fresh) {
      let last = null;
      try { last = localStorage.getItem(LAST_PLAYER); } catch { /* private mode */ }
      const known = (key) => info.players.some((p) => p.key === key
        && (p.platforms.includes(state.status.platform) || key === "other"));
      // The library decides, except a music folder, which could be any app: there the last pick wins.
      const start = state.library.id === "folder" && known(last) ? last : info.default;
      choice = { analysisId: state.analysis.analysis_id, style: "absolute", folderEdited: false, showAll: false };
      pickPlayer(state, known(start) ? start : "other");
    }
    draw(el, state);
  },
};
