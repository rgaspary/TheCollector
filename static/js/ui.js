// Small helpers shared by the screens.

export const $ = (selector, root = document) => root.querySelector(selector);

export const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

export const time = (s) => (s ? `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}` : "");

export function showError(message) {
  const el = $("#error");
  el.textContent = message || "";
  el.hidden = !message;
}

export function showNotice(message) {
  const el = $("#notice");
  el.textContent = message || "";
  el.hidden = !message;
}

// Logos that need a different version on dark backgrounds (see static/icons/SOURCES.md).
const DARK_VARIANTS = { "services/spotify.svg": "services/spotify-white.svg" };

export function iconHTML(folder, name, alt = "") {
  const key = `${folder}/${name}`;
  const img = `<img src="/static/icons/${esc(key)}" alt="${esc(alt)}" draggable="false">`;
  const dark = DARK_VARIANTS[key];
  if (!dark) return img;
  return `<picture><source srcset="/static/icons/${esc(dark)}" media="(prefers-color-scheme: dark)">${img}</picture>`;
}

// Arrow keys move focus between the tiles of a grid.
export function arrowKeys(grid) {
  grid.addEventListener("keydown", (e) => {
    const keys = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 };
    if (!(e.key in keys)) return;
    const tiles = [...grid.querySelectorAll(".tile")];
    const at = tiles.indexOf(document.activeElement);
    if (at < 0) return;
    e.preventDefault();
    let step = keys[e.key];
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      const perRow = Math.max(1, tiles.filter((t) => t.offsetTop === tiles[0].offsetTop).length);
      step *= perRow;
    }
    tiles[Math.min(tiles.length - 1, Math.max(0, at + step))].focus();
  });
}

export function busy(button, label) {
  const old = button.textContent;
  button.disabled = true;
  button.textContent = label;
  return () => { button.disabled = false; button.textContent = old; };
}
