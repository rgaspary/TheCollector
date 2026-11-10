// The Browse… button next to a folder field: opens the desktop's own folder picker.
import { post } from "./api.js";
import { busy, showError } from "./ui.js";

export function folderRow(id, value) {
  return `<div class="folder-row">
      <input type="text" id="${id}" class="wide" value="${value}" spellcheck="false">
      <button type="button" data-browse="${id}">Browse…</button>
    </div>`;
}

export function wireBrowse(root) {
  root.querySelectorAll("[data-browse]").forEach((button) => button.addEventListener("click", async () => {
    const input = root.querySelector(`#${button.dataset.browse}`);
    showError("");
    const done = busy(button, "Choosing…");
    try {
      const r = await post("/api/choose-folder", { start: input.value.trim() });
      if (r.folder) {
        input.value = r.folder;
        input.dispatchEvent(new Event("input", { bubbles: true }));
      }
    } catch (err) {
      showError(err.message);
    } finally {
      done();
      input.focus();
    }
  }));
}
