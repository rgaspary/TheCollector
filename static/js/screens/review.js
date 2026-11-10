// Screen 3: what's in the library, what's close, what's missing. Close matches need a decision
// (one of my files, or "add to missing") before Continue.
import { post } from "../api.js";
import { handleApiError } from "../errors.js";
import { back, go } from "../router.js";
import { busy, esc, showError, time } from "../ui.js";

const MISSING = "missing";

function trackLine(t) {
  return `<div class="track">${esc(t.title)}</div>
    <div class="meta">${esc(t.artist)}${t.album ? " · " + esc(t.album) : ""}${t.duration ? " · " + time(t.duration) : ""}</div>`;
}

function choiceHTML(t, decisions) {
  const remembered = (value) => (t.remembered === value ? '<span class="tag">chosen last time</span>' : "");
  const opts = t.candidates.map((c) => `
    <label class="opt"><input type="radio" name="c${t.index}" value="${esc(c.path)}" ${decisions[t.index] === c.path ? "checked" : ""}>
      <span><b>Use mine:</b> ${esc(c.title)} <span class="meta">— ${esc(c.artist)} · ${esc(c.album || "no album")}${c.duration ? " · " + time(c.duration) : ""}</span>
        ${remembered(c.path)}
        <span class="reason">${esc(c.reason)}</span>
        <span class="path">${esc(c.path)}</span></span></label>`).join("");
  return `<fieldset class="choice"><legend class="sr-only">${esc(t.track.title)} by ${esc(t.track.artist)}</legend>
    ${trackLine(t.track)}
    <div class="options">${opts}
      <label class="opt missing-opt"><input type="radio" name="c${t.index}" value="${MISSING}" ${decisions[t.index] === MISSING ? "checked" : ""}>
        <span><b>Add to missing songs</b>${remembered(MISSING)}
        <span class="reason">I want this exact version</span></span></label>
    </div></fieldset>`;
}

function list(items, empty) {
  return items.length
    ? `<ol class="list">${items.map((t) => `<li>${esc(t.track.title)} <span class="meta">— ${esc(t.track.artist)}</span></li>`).join("")}</ol>`
    : `<p class="meta">${empty}</p>`;
}

function draw(el, state) {
  const a = state.analysis;
  const decisions = state.decisions;
  const exact = a.tracks.filter((t) => t.status === "exact");
  const close = a.tracks.filter((t) => t.status === "close");
  const missing = a.tracks.filter((t) => t.status === "missing");

  el.innerHTML = `<div class="card">
      <div class="playlist-title"><h2>${esc(a.playlist.name)}</h2>
        ${a.playlist.url ? `<a href="${esc(a.playlist.url)}" target="_blank" rel="noopener">Open in ${esc(a.playlist.service)} ↗</a>` : ""}</div>
      <div class="summary">
        <span class="chip ok"><b>${exact.length}</b> in your library</span>
        <span class="chip ask"><b>${close.length}</b> close match${close.length === 1 ? "" : "es"}</span>
        <span class="chip miss"><b>${missing.length}</b> missing</span>
        <span class="chip">${a.library_count.toLocaleString()} song${a.library_count === 1 ? "" : "s"} in your library</span>
      </div>
      ${a.library_warning ? `<p class="library-warning">${esc(a.library_warning)}</p>` : ""}
      ${close.length ? `<h3>Close matches — pick one for each</h3>
        <div class="bulk"><button type="button" data-bulk="best">Use my best match for all</button>
          <button type="button" data-bulk="missing">Send all to missing</button></div>
        <div class="choices">${close.map((t) => choiceHTML(t, decisions)).join("")}</div>` : ""}
      <details><summary>In your library (${exact.length})</summary>${list(exact, "None.")}</details>
      <details ${missing.length && !close.length ? "open" : ""}><summary>Missing (${missing.length})</summary>${list(missing, "Nothing missing.")}</details>
    </div>
    <div class="build">
      <button type="button" data-back>Back</button>
      <span class="left" aria-live="polite"></span>
      <button type="button" class="primary" data-continue>Continue</button>
    </div>`;

  const left = el.querySelector(".left");
  const cont = el.querySelector("[data-continue]");
  const update = () => {
    const open = close.filter((t) => !decisions[t.index]).length;
    left.textContent = open ? `${open} close match${open === 1 ? "" : "es"} left to decide` : "";
    cont.disabled = open > 0;
  };
  el.querySelectorAll("input[type=radio]").forEach((r) =>
    r.addEventListener("change", () => { decisions[Number(r.name.slice(1))] = r.value; update(); }));
  el.querySelectorAll("[data-bulk]").forEach((b) => b.addEventListener("click", () => {
    for (const t of close) decisions[t.index] = b.dataset.bulk === "best" ? t.candidates[0].path : MISSING;
    const y = window.scrollY;
    draw(el, state);
    window.scrollTo({ top: y });
    el.querySelector(`[data-bulk="${b.dataset.bulk}"]`)?.focus();
  }));
  el.querySelector("[data-back]").addEventListener("click", () => back());
  cont.addEventListener("click", async () => {
    showError("");
    const done = busy(cont, "Saving…");
    try {
      const r = await post("/api/resolve", { analysis_id: a.analysis_id, decisions });
      state.resolved = r;
      await go(r.matched ? "export" : r.missing ? "missing" : "done");
    } catch (err) {
      await handleApiError(err);
    } finally {
      done();
      update();
    }
  });
  update();
}

export const reviewScreen = {
  render(el, state) {
    if (!state.analysis) return go("link", { direction: "back" });
    draw(el, state);
  },
};
