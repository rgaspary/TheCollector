// Screens 1a/1b: set up a service's login, or fix one that stopped working. Test is optional and
// never saves; Save & continue saves, and for Spotify then offers Connect (browser sign-in).
import { get, post } from "../api.js";
import { back, currentScreen, go } from "../router.js";
import { busy, esc, showError } from "../ui.js";

let polling = null;

function stopPolling() {
  if (polling) clearInterval(polling);
  polling = null;
}

function fieldHTML(f, value) {
  const id = `cred-${esc(f.key)}`;
  const saved = f.secret && value && value.set;
  const current = f.secret ? "" : (value && value.value) || "";
  const placeholder = saved ? "Saved — leave blank to keep it" : f.placeholder || "";
  const control = f.multiline
    ? `<textarea id="${id}" data-key="${esc(f.key)}" rows="4" placeholder="${esc(placeholder)}">${esc(current)}</textarea>`
    : `<input type="${f.secret ? "password" : "text"}" id="${id}" data-key="${esc(f.key)}" value="${esc(current)}"
         placeholder="${esc(placeholder)}" autocomplete="off" spellcheck="false">`;
  return `<div class="field"><label for="${id}">${esc(f.label)}</label>${control}
    ${f.help ? `<p class="muted small">${esc(f.help)}</p>` : ""}</div>`;
}

function typedValues(el) {
  const values = {};
  el.querySelectorAll("[data-key]").forEach((input) => { values[input.dataset.key] = input.value.trim(); });
  return values;
}

function nextScreen(state) {
  const target = state.returnTo || (state.sourceInfo.input === "file" ? "import" : "link");
  state.returnTo = null;
  return target;
}

export const credentialsScreen = {
  async render(el, state) {
    stopPolling();
    try {  // fresh status and saved values
      const sources = await get("/api/sources");
      state.sourceInfo = sources.find((s) => s.id === state.source) || state.sourceInfo;
    } catch (err) {
      showError(err.message);
    }
    const s = state.sourceInfo;
    if (!s) return go("source", { direction: "back" });
    const fixing = s.status.state === "invalid";
    const needsConnect = s.uses_oauth && s.fields.every((f) => !f.secret || s.values[f.key]?.set)
      && s.fields.every((f) => f.secret || s.values[f.key]?.value);

    el.innerHTML = `<div class="card">
      <h2>${fixing ? `Fix the ${esc(s.name)} connection` : `Set up ${esc(s.name)}`}</h2>
      ${fixing ? `<div class="problem" role="alert"><b>${esc(s.status.error)}</b>
        ${s.status.fix ? `<p>${esc(s.status.fix)}</p>` : ""}</div>` : ""}
      <p>${esc(s.help_text)}
        ${s.help_url ? ` <a href="${esc(s.help_url)}" target="_blank" rel="noopener">Where to get these ↗</a>` : ""}</p>
      ${s.uses_oauth && state.status?.redirect_uri ? `<p class="muted small">Redirect URI to add to your app:
        <code>${esc(state.status.redirect_uri)}</code></p>` : ""}
      <form class="fields" novalidate>${s.fields.map((f) => fieldHTML(f, s.values[f.key])).join("")}</form>
      ${s.limits ? `<p class="muted small">${esc(s.limits)}</p>` : ""}
      <div class="result" aria-live="polite"></div>
      <div class="connect" hidden>
        <p>Now sign in to ${esc(s.name)} in your browser. This page carries on by itself when you're connected.</p>
        <a class="btn primary" href="/login/${esc(s.id)}" target="_blank" rel="noopener" data-connect>Connect ${esc(s.name)}</a>
      </div>
      <div class="nav">
        <button type="button" data-back>Back</button>
        <button type="button" data-test>Test</button>
        <button type="button" class="primary" data-save>${fixing ? "Save &amp; try again" : "Save &amp; continue"}</button>
      </div></div>`;

    const result = el.querySelector(".result");
    const connect = el.querySelector(".connect");
    const show = (ok, message, fix = "") => {
      result.className = `result ${ok ? "ok" : "bad"}`;
      result.innerHTML = ok ? `✓ ${esc(message)}` : `${esc(message)}${fix ? `<br><span>${esc(fix)}</span>` : ""}`;
    };
    const waitForSignIn = () => {
      connect.hidden = false;
      stopPolling();
      polling = setInterval(async () => {
        if (currentScreen() !== "credentials") return stopPolling();
        try {
          const sources = await get("/api/sources");
          const now = sources.find((x) => x.id === s.id);
          if (now && now.status.state === "ready") {
            stopPolling();
            state.sourceInfo = now;
            go(nextScreen(state));
          }
        } catch { /* keep waiting */ }
      }, 2000);
    };

    el.querySelector("form").addEventListener("submit", (e) => { e.preventDefault(); el.querySelector("[data-save]").click(); });
    el.querySelector("[data-back]").addEventListener("click", () => { stopPolling(); state.returnTo = null; back(); });
    el.querySelector("[data-test]").addEventListener("click", async (e) => {
      const done = busy(e.target, "Testing…");
      try {
        const r = await post(`/api/sources/${encodeURIComponent(s.id)}/test`, { values: typedValues(el) });
        show(r.ok, r.ok ? r.message : r.error, r.fix);
      } catch (err) {
        show(false, err.message);
      } finally {
        done();
      }
    });
    el.querySelector("[data-save]").addEventListener("click", async (e) => {
      const done = busy(e.target, "Saving…");
      try {
        const r = await post(`/api/sources/${encodeURIComponent(s.id)}/credentials`, { values: typedValues(el) });
        if (r.status.state === "ready") {
          await go(nextScreen(state));
        } else if (s.uses_oauth && s.fields.every((f) => typedValues(el)[f.key] || s.values[f.key]?.set
            || s.values[f.key]?.value)) {
          show(true, "Saved.");
          waitForSignIn();
        } else {
          show(false, "Fill in every field first.");
        }
      } catch (err) {
        show(false, err.message);
      } finally {
        done();
      }
    });
    if (needsConnect && s.status.state !== "ready") waitForSignIn();
  },
};
