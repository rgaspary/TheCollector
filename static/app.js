const $ = (s) => document.querySelector(s);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const time = (s) => (s ? `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}` : "");
const MISSING = "missing";
let analysis = null;
const decisions = {};

function showError(msg) {
  const el = $("#error");
  el.textContent = msg || "";
  el.hidden = !msg;
}

async function post(url, body) {
  const res = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const data = await res.json().catch(() => ({ error: `Server error (${res.status})` }));
  if (!res.ok) throw new Error(data.error || `Server error (${res.status})`);
  return data;
}

async function loadStatus() {
  const s = await (await fetch("/api/status")).json();
  const setup = $("#setup");
  if (!s.client_id_set) {
    setup.hidden = false;
    setup.innerHTML = `<h2>One-time setup</h2>
      <p>Open your app at <a href="https://developer.spotify.com/dashboard" target="_blank" rel="noopener">developer.spotify.com/dashboard</a>,
      add this Redirect URI in its settings: <code>${esc(s.redirect_uri)}</code></p>
      <p>Then paste the app's Client ID into <code>config.toml</code> (<code>[spotify] client_id</code>) — this page updates by itself once it's saved.</p>`;
    setTimeout(loadStatus, 2000);
    return;
  }
  if (!s.logged_in) {
    setup.hidden = false;
    setup.innerHTML = `<h2>Connect Spotify</h2><p>TheCollector only reads your playlists. Spotify's sign-in opens in your browser;
      come back here when it says you're connected.</p>
      <a class="btn primary" href="/login" target="_blank" rel="noopener">Connect Spotify</a>`;
    // Wait for the login to finish in the browser, then switch to the main screen.
    setTimeout(loadStatus, 2000);
    return;
  }
  setup.hidden = true;
  $("#analyze").hidden = false;
  $("#account").innerHTML = `Spotify connected · <button class="link" id="logout">Disconnect</button>`;
  $("#logout").onclick = async () => { await post("/api/logout", {}); location.reload(); };
}

$("#analyze").addEventListener("submit", async (e) => {
  e.preventDefault();
  showError("");
  $("#done").hidden = true;
  const btn = e.submitter || $("#analyze button");
  btn.disabled = true;
  btn.textContent = "Analyzing…";
  try {
    analysis = await post("/api/analyze", { url: $("#url").value });
    for (const k of Object.keys(decisions)) delete decisions[k];
    for (const t of analysis.tracks) if (t.status === "close" && t.remembered) decisions[t.index] = t.remembered;
    renderResults();
  } catch (err) {
    showError(err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "Analyze";
  }
});

function trackLine(sp) {
  return `<div class="track">${esc(sp.title)}</div>
    <div class="meta">${esc(sp.artist)}${sp.album ? " · " + esc(sp.album) : ""}${sp.duration ? " · " + time(sp.duration) : ""}</div>`;
}

function renderResults() {
  const a = analysis;
  const exact = a.tracks.filter((t) => t.status === "exact");
  const close = a.tracks.filter((t) => t.status === "close");
  const missing = a.tracks.filter((t) => t.status === "missing");

  const choices = close.map((t) => {
    const opts = t.candidates.map((c) => `
      <label class="opt"><input type="radio" name="c${t.index}" value="${esc(c.path)}" ${decisions[t.index] === c.path ? "checked" : ""}>
        <span><b>Use mine:</b> ${esc(c.title)} <span class="meta">— ${esc(c.artist)} · ${esc(c.album || "no album")}${c.duration ? " · " + time(c.duration) : ""}</span>
        ${t.remembered === c.path ? '<span class="tag">chosen last time</span>' : ""}
        <div class="reason">${esc(c.reason)}</div></span></label>`).join("");
    return `<div class="choice">${trackLine(t.spotify)}
      <div class="options">${opts}
        <label class="opt missing-opt"><input type="radio" name="c${t.index}" value="${MISSING}" ${decisions[t.index] === MISSING ? "checked" : ""}>
          <span><b>Add to missing tracks</b>${t.remembered === MISSING ? '<span class="tag">chosen last time</span>' : ""}
          <div class="reason">I want this exact version</div></span></label>
      </div></div>`;
  }).join("");

  const list = (items, empty) => items.length
    ? `<ol class="list">${items.map((t) => `<li>${esc(t.spotify.title)} <span class="meta">— ${esc(t.spotify.artist)}</span></li>`).join("")}</ol>`
    : `<p class="meta">${empty}</p>`;

  $("#results").hidden = false;
  $("#results").innerHTML = `
    <div class="card">
      <div class="playlist-title"><h2>${esc(a.playlist.name)}</h2>
        <a href="${esc(a.playlist.url)}" target="_blank" rel="noopener">Open in Spotify</a></div>
      <div class="summary">
        <span class="chip ok"><b>${exact.length}</b> in your library</span>
        <span class="chip ask"><b>${close.length}</b> close matches</span>
        <span class="chip miss"><b>${missing.length}</b> missing</span>
        <span class="chip">${a.library_count} tracks in library</span>
      </div>
      ${close.length ? `<h2>Close matches — pick one for each</h2>
        <div class="bulk"><button type="button" data-bulk="best">Use my best match for all</button>
        <button type="button" data-bulk="missing">Send all to missing</button></div>
        <div id="choices">${choices}</div>` : ""}
      <details><summary>In your library (${exact.length})</summary>${list(exact, "None.")}</details>
      <details ${missing.length ? "open" : ""}><summary>Missing (${missing.length})</summary>${list(missing, "Nothing missing.")}</details>
    </div>
    <div class="build"><span class="left" id="left"></span>
      <button class="primary" id="build">Build playlist</button></div>`;

  $("#results").querySelectorAll("input[type=radio]").forEach((r) =>
    r.addEventListener("change", () => { decisions[Number(r.name.slice(1))] = r.value; updateBuild(); }));
  $("#results").querySelectorAll("[data-bulk]").forEach((b) => b.addEventListener("click", () => {
    for (const t of close) decisions[t.index] = b.dataset.bulk === "best" ? t.candidates[0].path : MISSING;
    renderResults();
  }));
  $("#build").addEventListener("click", build);
  updateBuild();
}

function updateBuild() {
  const left = analysis.tracks.filter((t) => t.status === "close" && !decisions[t.index]).length;
  $("#left").textContent = left ? `${left} close match${left === 1 ? "" : "es"} left to decide` : "";
  $("#build").disabled = left > 0;
}

async function build() {
  showError("");
  const btn = $("#build");
  btn.disabled = true;
  btn.textContent = "Building…";
  try {
    const r = await post("/api/build", { analysis_id: analysis.analysis_id, decisions });
    const done = $("#done");
    done.hidden = false;
    let noteText;
    if (!r.note_path) noteText = "Nothing missing, so no to-do note was needed.";
    else if (r.note_added || r.note_ticked) {
      noteText = `To-do note updated: ${r.note_added} added${r.note_ticked ? `, ${r.note_ticked} ticked off (now in your library)` : ""}.`;
    } else noteText = "To-do note already lists every missing track.";
    done.innerHTML = `<h2>Done</h2>
      ${r.playlist_path ? `<p>Playlist with <b>${r.added}</b> tracks saved to <code>${esc(r.playlist_path)}</code>.
        In Strawberry: Playlist → Load playlist, or drag the file in.</p>` : "<p>None of these tracks are in your library, so no playlist file was written.</p>"}
      <p>${esc(noteText)}${r.note_path ? ` <code>${esc(r.note_path)}</code>` : ""}</p>
      ${r.obsidian_url ? `<div class="actions"><a class="btn" href="${esc(r.obsidian_url)}">Open note in Obsidian</a></div>` : ""}`;
    done.scrollIntoView({ behavior: "smooth" });
  } catch (err) {
    showError(err.message);
  } finally {
    btn.textContent = "Build playlist";
    updateBuild();
  }
}

const params = new URLSearchParams(location.search);
if (params.get("error")) { showError(params.get("error")); history.replaceState(null, "", "/"); }
if (params.get("connected")) {
  const n = document.createElement("div");
  n.className = "notice";
  n.textContent = "Spotify is connected. If you started from the TheCollector app, you can close this tab.";
  $("#error").before(n);
  history.replaceState(null, "", "/");
}
loadStatus().catch((e) => showError(e.message));
