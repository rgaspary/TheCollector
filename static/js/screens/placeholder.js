// Stand-in for the one screen not built yet: the Apple Music file import (postponed).
import { back, go } from "../router.js";

export const importPlaceholder = {
  render(el) {
    el.innerHTML = `
      <div class="card">
        <h2>Import the playlist file</h2>
        <p class="muted">This screen is still being built.</p>
        <div class="nav">
          <button type="button" data-back>Back</button>
          <button type="button" class="primary" data-next>Continue</button>
        </div>
      </div>`;
    el.querySelector("[data-back]").addEventListener("click", () => back());
    el.querySelector("[data-next]").addEventListener("click", () => go("review"));
  },
};
