// Screen 6: what was saved where, with shortcuts to open it.
import { post } from "../api.js";
import { go } from "../router.js";
import { esc, showError } from "../ui.js";

function fileRow(path) {
  const name = path.split(/[\\/]/).pop();
  return `<li><span class="file-name">${esc(name)}</span>
    <span class="path">${esc(path)}</span>
    <button type="button" class="link" data-reveal="${esc(path)}">Open folder</button></li>`;
}

function noteText(m) {
  if (!m.note_path) return "No NextUp note was needed: nothing is missing and nothing to tick off.";
  if (m.note_added || m.note_ticked) {
    const parts = [];
    if (m.note_added) parts.push(`${m.note_added} added`);
    if (m.note_ticked) parts.push(`${m.note_ticked} ticked off (now in your library)`);
    return `NextUp note updated: ${parts.join(", ")}.`;
  }
  return "The NextUp note already lists every missing song.";
}

export const doneScreen = {
  render(el, state) {
    const ex = state.exportResult;
    const m = state.missingResult;
    const files = [...(ex ? ex.files : []), ...(m && m.file ? [m.file] : [])];
    const noteUsed = m && (m.note_path !== undefined) && state.status.nextup_enabled;

    el.innerHTML = `<div class="card done">
      <h2>Done</h2>
      ${ex ? `<p>The playlist has <b>${state.resolved.matched}</b> song${state.resolved.matched === 1 ? "" : "s"}.
</p>${ex.steps ? `<div class="steps-box"><b>To open it in ${esc(ex.player)}:</b> ${esc(ex.steps)}</div>` : ""}`
        : state.resolved && state.resolved.matched ? "<p>You skipped the playlist export.</p>"
        : "<p>None of these songs are in your library, so there was no playlist to save.</p>"}
      ${files.length ? `<ul class="files">${files.map(fileRow).join("")}</ul>` : "<p class=\"muted\">No files were saved.</p>"}
      ${noteUsed ? `<p>${esc(noteText(m))}${m.note_path ? ` <span class="path">${esc(m.note_path)}</span>` : ""}</p>` : ""}
      <div class="actions">
        ${m && m.obsidian_url ? `<a class="btn" href="${esc(m.obsidian_url)}">Open note in Obsidian</a>` : ""}
        <button type="button" class="primary" data-restart>Start over</button>
      </div></div>`;

    el.querySelectorAll("[data-reveal]").forEach((b) => b.addEventListener("click", async () => {
      try {
        await post("/api/reveal", { path: b.dataset.reveal });
      } catch (err) {
        showError(err.message);
      }
    }));
    el.querySelector("[data-restart]").addEventListener("click", () => {
      Object.assign(state, {
        link: "", analysis: null, decisions: {}, resolved: null, exportResult: null, missingResult: null, returnTo: null,
      });
      go("source", { direction: "back" });
    });
  },
};
