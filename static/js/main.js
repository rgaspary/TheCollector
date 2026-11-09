// Start-up: load the status, set up the header and step bar, and open the first screen.
import { get } from "./api.js";
import { SCREENS, go, init, register } from "./router.js";
import { renderLibraryBadge } from "./header.js";
import { credentialsScreen } from "./screens/credentials.js";
import { doneScreen } from "./screens/done.js";
import { exportScreen } from "./screens/export.js";
import { libraryScreen } from "./screens/library.js";
import { linkScreen } from "./screens/link.js";
import { missingScreen } from "./screens/missing.js";
import { placeholder } from "./screens/placeholder.js";
import { reviewScreen } from "./screens/review.js";
import { sourceScreen } from "./screens/source.js";
import { state } from "./state.js";
import { $, showError, showNotice } from "./ui.js";

const BUILT = {
  library: libraryScreen, source: sourceScreen, credentials: credentialsScreen, link: linkScreen, review: reviewScreen,
  export: exportScreen, missing: missingScreen, done: doneScreen,
};

// Which step of the bar each screen belongs to.
const STEP_OF = { library: 0, source: 1, credentials: 1, link: 2, import: 2, review: 3, export: 4, missing: 5, done: 6 };

function markStep(screen) {
  const step = STEP_OF[screen] ?? 0;
  document.querySelectorAll(".steps li").forEach((li, i) => {
    li.classList.toggle("done", i < step);
    if (i === step) li.setAttribute("aria-current", "step");
    else li.removeAttribute("aria-current");
  });
  showError("");
}

function messagesFromUrl() {
  const params = new URLSearchParams(location.search);
  if (params.get("error")) showError(params.get("error"));
  if (params.get("connected")) showNotice("Spotify is connected. If this opened in a new tab, you can close it.");
  if (params.toString()) history.replaceState(null, "", "/");
}

async function start() {
  for (const name of SCREENS) {
    const section = document.createElement("section");
    section.className = "screen";
    section.dataset.screen = name;
    section.hidden = true;
    $(".stage").append(section);
    register(name, BUILT[name] || placeholder(name));
  }
  init(state, { changed: markStep });
  messagesFromUrl();
  try {
    state.status = await get("/api/status");
  } catch (err) {
    showError(err.message);
    return;
  }
  state.library = state.status.library;
  $("#version").textContent = `v${state.status.version}`;
  renderLibraryBadge();
  await go(state.library.configured ? "source" : "library");
}

start();
