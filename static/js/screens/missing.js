// Screen 5: save the songs that aren't in the library, as a file and/or into the NextUp note.
import { get, post } from "../api.js";
import { handleApiError } from "../errors.js";
import { folderRow, wireBrowse } from "../browse.js";
import { back, go } from "../router.js";
import { busy, esc, showError } from "../ui.js";

const HINTS = {
  md: "A checklist for Obsidian, Logseq, Joplin, GitHub or VS Code.",
  txt: "One song per line. Pastes into any to-do app.",
  csv: "Opens in a spreadsheet.",
  json: "For scripts and other tools.",
};
const ORDER = ["md", "txt", "csv", "json"];
const LAST_FORMAT = "thecollector.missing-format";

let formats = null;
let picked = null;       // format key, or "" for no file (NextUp only)
let nextup = true;
let folder = "";         // where the file goes; starts in Documents
let pickedFor = null;    // analysis id the picks belong to

export function missingTracks(state) {
  const d = state.decisions;
  return state.analysis.tracks
    .filter((t) => t.status === "missing" || (t.status === "close" && d[t.index] === "missing"))
    .map((t) => t.track);
}

export const missingScreen = {
  async render(el, state) {
    if (!state.resolved) return go("review", { direction: "back" });
    if (!formats) {
      try {
        formats = (await get("/api/players")).missing_formats;
      } catch (err) {
        showError(err.message);
        return;
      }
    }
    if (pickedFor !== state.analysis.analysis_id) {
      pickedFor = state.analysis.analysis_id;
      let last = null;
      try { last = localStorage.getItem(LAST_FORMAT); } catch { /* private mode */ }
      picked = last !== null && (last === "" || formats.some((f) => f.key === last)) ? last : "md";
      if (picked === "" && !state.status.nextup_enabled) picked = "md";
      nextup = true;
      folder = state.status.missing_dir;
    }
    const tracks = missingTracks(state);
    const options = ORDER.map((k) => formats.find((f) => f.key === k)).filter(Boolean);

    el.innerHTML = `<div class="card">
      <h2>${tracks.length} song${tracks.length === 1 ? "" : "s"} you don't have yet</h2>
      <ol class="list">${tracks.slice(0, 5).map((t) => `<li>${esc(t.title)} <span class="meta">— ${esc(t.artist)}</span></li>`).join("")}</ol>
      ${tracks.length > 5 ? `<p class="muted small">…and ${tracks.length - 5} more.</p>` : ""}

      <fieldset class="cards"><legend>Save the list as</legend>
        ${options.map((f) => `<label class="opt"><input type="radio" name="missing-format" value="${esc(f.key)}"
            ${picked === f.key ? "checked" : ""}>
          <span><b>${esc(f.label)}</b> <span class="muted">(${esc(f.ext)})</span><span class="reason">${esc(HINTS[f.key] || "")}</span></span></label>`).join("")}
        ${state.status.nextup_enabled ? `<label class="opt"><input type="radio" name="missing-format" value=""
            ${picked === "" ? "checked" : ""}><span><b>No file</b><span class="reason">Only update the NextUp note.</span></span></label>` : ""}
      </fieldset>
      <div class="missing-folder" ${picked ? "" : "hidden"}>
        <label for="missing-folder">Save to folder</label>
        ${folderRow("missing-folder", esc(folder))}
      </div>
      ${state.status.nextup_enabled ? `<label class="check nextup"><input type="checkbox" ${nextup ? "checked" : ""}>
        Also update my NextUp note (adds these songs, ticks off ones now in your library)</label>` : ""}

      <div class="nav">
        <button type="button" data-back>Back</button>
        <button type="button" data-skip>Skip</button>
        <button type="button" class="primary" data-export>Save</button>
      </div></div>`;

    const saveBtn = el.querySelector("[data-export]");
    const update = () => { saveBtn.disabled = !picked && !(state.status.nextup_enabled && nextup); };
    el.querySelectorAll('input[name="missing-format"]').forEach((r) => r.addEventListener("change", () => {
      picked = r.value;
      try { localStorage.setItem(LAST_FORMAT, picked); } catch { /* private mode */ }
      el.querySelector(".missing-folder").hidden = !picked;
      update();
    }));
    el.querySelector("#missing-folder").addEventListener("input", (e) => { folder = e.target.value; });
    wireBrowse(el);
    el.querySelector(".nextup input")?.addEventListener("change", (e) => { nextup = e.target.checked; update(); });
    el.querySelector("[data-back]").addEventListener("click", () => back());
    el.querySelector("[data-skip]").addEventListener("click", () => { state.missingResult = null; go("done"); });
    saveBtn.addEventListener("click", async () => {
      showError("");
      const done = busy(saveBtn, "Saving…");
      try {
        state.missingResult = await post("/api/export/missing", {
          analysis_id: state.analysis.analysis_id,
          format: picked || null,
          folder: folder.trim(),
          nextup: state.status.nextup_enabled && nextup,
        });
        await go("done");
      } catch (err) {
        await handleApiError(err);
      } finally {
        done();
        update();
      }
    });
    update();
  },
};
