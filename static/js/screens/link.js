// Screen 2: paste the playlist link and analyze it against the library.
import { get, post } from "../api.js";
import { handleApiError } from "../errors.js";
import { back, go } from "../router.js";
import { busy, esc, iconHTML, showError } from "../ui.js";

async function sourceInfo(id) {
  const sources = await get("/api/sources");
  return sources.find((s) => s.id === id);
}

export const linkScreen = {
  async render(el, state) {
    const s = state.sourceInfo;
    if (!s) return go("source", { direction: "back" });
    el.innerHTML = `<div class="card">
      <div class="source-head"><span class="tile-icon small">${iconHTML("services", s.icon)}</span>
        <h2>Paste the ${esc(s.name)} playlist link</h2></div>
      <form class="link-form" novalidate>
        <label for="playlist-url">Playlist link</label>
        <div class="row">
          <input id="playlist-url" type="text" value="${esc(state.link)}" placeholder="${esc(s.link_example)}"
            autocomplete="off" spellcheck="false">
          <button type="submit" class="primary">Analyze</button>
        </div>
        ${s.limits ? `<p class="muted small">${esc(s.limits)}</p>` : ""}
      </form>
      <div class="hint" aria-live="polite"></div>
      <div class="nav"><button type="button" data-back>Back</button></div>
    </div>`;

    const input = el.querySelector("#playlist-url");
    const hint = el.querySelector(".hint");
    input.addEventListener("input", () => { state.link = input.value; });
    el.querySelector("[data-back]").addEventListener("click", () => back());

    el.querySelector("form").addEventListener("submit", async (e) => {
      e.preventDefault();
      showError("");
      hint.innerHTML = "";
      state.link = input.value.trim();
      if (!state.link) {
        showError("Paste a playlist link first.");
        input.focus();
        return;
      }
      const done = busy(e.submitter || el.querySelector("button[type=submit]"), "Analyzing…");
      input.disabled = true;
      try {
        const analysis = await post("/api/analyze", { source: s.id, url: state.link });
        state.analysis = analysis;
        state.decisions = {};
        for (const t of analysis.tracks) {
          if (t.status === "close" && t.remembered) state.decisions[t.index] = t.remembered;
        }
        state.exportResult = null;
        state.missingResult = null;
        await go("review");
      } catch (err) {
        if (err.code === "wrong_source") {
          const other = await sourceInfo(err.data.detected).catch(() => null);
          hint.innerHTML = `<div class="problem">${esc(err.message)}
            ${other ? `<p><button type="button" class="primary" data-switch>Switch to ${esc(other.name)}</button></p>` : ""}</div>`;
          hint.querySelector("[data-switch]")?.addEventListener("click", async () => {
            state.source = other.id;
            state.sourceInfo = other;
            if (other.status.state === "ready") {
              await linkScreen.render(el, state);  // same screen, other service, link kept
              el.querySelector("h2").focus();
            } else {
              state.returnTo = "link";
              go("credentials");
            }
          });
        } else {
          await handleApiError(err);
        }
      } finally {
        input.disabled = false;
        done();
      }
    });
  },
};
