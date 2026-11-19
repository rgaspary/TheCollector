// The "Library: <name> · Change" line under the title.
import { go } from "./router.js";
import { state } from "./state.js";
import { $, esc } from "./ui.js";

export function renderLibraryBadge() {
  const el = $("#library-badge");
  const lib = state.library;
  if (!lib || !lib.configured) {
    el.hidden = true;
    return;
  }
  el.hidden = false;
  el.innerHTML = `Library: <b>${esc(lib.name)}</b> · <button type="button" class="link" id="change-library">Change</button>`;
  $("#change-library").onclick = () => go("library", { direction: "back" });
}
