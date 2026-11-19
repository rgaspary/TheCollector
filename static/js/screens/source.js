// Screen 1: pick the music service. Tiles show the official icon (where allowed) and a badge when
// the service needs setting up or fixing.
import { get } from "../api.js";
import { go } from "../router.js";
import { arrowKeys, esc, iconHTML, showError } from "../ui.js";

const BADGES = { needs_setup: ["Set up", "setup"], invalid: ["Needs attention", "bad"] };

export const sourceScreen = {
  async render(el, state) {
    el.innerHTML = `<div class="card"><h2>Choose a music service</h2>
      <p class="muted">Where's the playlist you want to bring into your library?</p>
      <div class="tiles" role="list"><p class="muted">Loading…</p></div></div>`;
    let sources;
    try {
      sources = await get("/api/sources");
    } catch (err) {
      showError(err.message);
      return;
    }
    const grid = el.querySelector(".tiles");
    grid.innerHTML = sources.map((s) => {
      const badge = BADGES[s.status.state];
      return `<button type="button" class="tile${s.id === state.source ? " selected" : ""}" data-id="${esc(s.id)}"
          role="listitem" aria-describedby="badge-${esc(s.id)}">
        <span class="tile-icon">${iconHTML("services", s.icon)}</span>
        <span class="tile-name">${esc(s.name)}</span>
        <span class="badge ${badge ? badge[1] : ""}" id="badge-${esc(s.id)}">${badge ? esc(badge[0]) : ""}</span>
      </button>`;
    }).join("");
    arrowKeys(grid);
    grid.querySelectorAll(".tile").forEach((tile) => {
      tile.addEventListener("click", () => {
        const info = sources.find((s) => s.id === tile.dataset.id);
        if (state.source !== info.id) state.link = "";  // a new service means a new link
        state.source = info.id;
        state.sourceInfo = info;
        state.returnTo = null;
        if (info.status.state !== "ready") go("credentials");
        else go(info.input === "file" ? "import" : "link");
      });
    });
  },
};
