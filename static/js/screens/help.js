// Help: step-by-step set-up for each music service (from the server), then common questions.
import { get } from "../api.js";
import { back, canGoBack, go } from "../router.js";
import { esc, iconHTML, showError } from "../ui.js";

const DATA_FOLDERS = {
  linux: "~/.local/share/thecollector",
  win32: "%APPDATA%\\TheCollector",
  darwin: "~/Library/Application Support/TheCollector",
};

const FAQ = [
  ["Where are my API keys and logins stored?", (s) =>
    `In <code>credentials.json</code> in TheCollector's data folder, <code>${esc(DATA_FOLDERS[s.platform] || DATA_FOLDERS.linux)}</code>.
     Only your user account can read it. It's never inside TheCollector's own folder, so it can't end up on GitHub.
     To remove one, use Disconnect in Settings.`],
  ["Why are songs I own listed as missing?", () =>
    `Usually the library doesn't know about them yet. Strawberry only lists songs it has scanned: open it and choose
     Tools → Update collection, or pick <b>Music folder</b> as your library so TheCollector reads your files directly.
     Songs can also be missed when the artist or title in the file's tags is very different from the service's.`],
  ["Which music library should I choose?", () =>
    `The app you play music in. If it isn't listed, or you use several, choose <b>Music folder</b> and add the folders
     your music is in. That works for any player, including Winamp, VLC and Rockbox.`],
  ["Where do my playlists and lists go?", (s) =>
    `Playlists go to <code>${esc(s.playlist_dir)}</code> and missing-song lists to <code>${esc(s.missing_dir)}</code>.
     Change these in Settings, or pick another folder on the Export and Missing steps.`],
  ["Which playlist format should I pick?", () =>
    `Pick the app you'll open the playlist in on the Export step, and TheCollector ticks the format that app reads
     best and shows how to open it. When in doubt, M3U8 works in most players.`],
  ["Spotify says the redirect URI is invalid", (s) =>
    `The Redirect URI in your Spotify app must be exactly <code>${esc(s.redirect_uri)}</code>, including
     <code>http://</code>, the port and <code>/callback</code>. Spotify doesn't accept <code>localhost</code> here,
     only <code>127.0.0.1</code>.`],
  ["YouTube says the daily quota is used up", () =>
    `The free quota resets at midnight Pacific Time. Try again then, or use a key from another Google Cloud project.`],
];

function linkify(text, redirect) {
  let html = esc(text).replace(/(https:\/\/[^\s<]*[^\s<.,;:)])/g, '<a href="$1" target="_blank" rel="noopener">$1 ↗</a>');
  if (redirect) html = html.split(esc(redirect)).join(`<code>${esc(redirect)}</code>`);
  return html;
}

export const helpScreen = {
  async render(el, state) {
    let sources;
    try {
      sources = (await get("/api/sources")).filter((s) => s.setup_steps.length);
    } catch (err) {
      showError(err.message);
      return;
    }
    const s = state.status;
    el.innerHTML = `<div class="card help">
      <h2>Help</h2>
      <p class="muted">How to connect each music service, and answers to common questions.</p>
      <nav class="toc" aria-label="On this page">
        ${sources.map((src) => `<a href="#help-${esc(src.id)}">Set up ${esc(src.name)}</a>`).join("")}
        <a href="#help-faq">Questions</a>
      </nav>

      ${sources.map((src) => `<section id="help-${esc(src.id)}">
        <h3><span class="tile-icon small">${iconHTML("services", src.icon)}</span> Set up ${esc(src.name)}</h3>
        <ol class="steps-list">${src.setup_steps.map((t) => `<li>${linkify(t, s.redirect_uri)}</li>`).join("")}</ol>
        ${src.setup_notes.length ? `<ul class="notes">${src.setup_notes.map((t) => `<li>${linkify(t)}</li>`).join("")}</ul>` : ""}
        <button type="button" data-setup="${esc(src.id)}">Set up ${esc(src.name)} now</button>
      </section>`).join("")}

      <section id="help-faq">
        <h3>Questions</h3>
        ${FAQ.map(([q, a]) => `<details><summary>${esc(q)}</summary><p>${a(s)}</p></details>`).join("")}
      </section>

      <div class="nav"><button type="button" data-back>Back</button></div></div>`;

    el.querySelectorAll(".toc a").forEach((a) => a.addEventListener("click", (e) => {
      e.preventDefault();
      el.querySelector(a.getAttribute("href"))?.scrollIntoView({ behavior: "smooth", block: "start" });
    }));
    el.querySelectorAll("[data-setup]").forEach((b) => b.addEventListener("click", () => {
      const info = sources.find((src) => src.id === b.dataset.setup);
      state.source = info.id;
      state.sourceInfo = info;
      state.returnTo = "settings";
      go("credentials");
    }));
    el.querySelector("[data-back]").addEventListener("click", () => {
      if (canGoBack()) back();
      else go(state.library?.configured ? "source" : "library", { direction: "back" });
    });
  },

  onEnter(el, state) {
    if (!state.helpFor) return;
    el.querySelector(`#help-${state.helpFor}`)?.scrollIntoView({ block: "start" });
    state.helpFor = null;
  },
};
