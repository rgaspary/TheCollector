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
