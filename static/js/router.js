// One screen at a time, sliding left/right with a fade. Calls made during a transition wait their turn.

const screens = new Map();   // name → {render(el, state), onEnter?(el, state)}
const history = [];
let current = null;
let queue = Promise.resolve();
let lastTarget = null;  // the screen the newest queued call goes to
let stateRef = null;
let onChange = () => {};

export const SCREENS = ["library", "source", "credentials", "link", "import", "review", "export", "missing", "done"];

export function init(state, { changed } = {}) {
  stateRef = state;
  if (changed) onChange = changed;
}

export function register(name, screen) {
  screens.set(name, screen);
}

export function currentScreen() {
  return current;
}

function element(name) {
  return document.querySelector(`.screen[data-screen="${name}"]`);
}

function duration() {
  const raw = getComputedStyle(document.documentElement).getPropertyValue("--t-dur").trim();
  return raw.endsWith("ms") ? parseFloat(raw) : parseFloat(raw) * 1000 || 0;
}

function waitForTransition(el) {
  return new Promise((resolve) => {
    let done = false;
    const finish = () => { if (!done) { done = true; resolve(); } };
    el.addEventListener("transitionend", finish, { once: true });
    setTimeout(finish, duration() + 80);  // in case transitionend never fires
  });
}

async function swap(name, direction, record) {
  const screen = screens.get(name);
  if (!screen) throw new Error(`No screen called "${name}"`);
  const next = element(name);
  const prev = current ? element(current) : null;
  if (record && current && current !== name) history.push(current);

  await screen.render(next, stateRef);
  if (name === current) return;  // re-render in place

  const forward = direction !== "back";
  if (!forward) {
    const at = history.lastIndexOf(name);
    if (at >= 0) history.length = at;  // going back past screens drops them from the history
  }
  next.hidden = false;
  next.inert = false;
  next.removeAttribute("aria-hidden");
  next.className = `screen ${forward ? "enter-from-right" : "enter-from-left"}`;
  void next.offsetWidth;  // start from the "enter" position
  next.className = "screen active";

  const waits = [waitForTransition(next)];
  if (prev) {
    prev.inert = true;
    prev.setAttribute("aria-hidden", "true");
    prev.className = `screen ${forward ? "exit-to-left" : "exit-to-right"}`;
    waits.push(waitForTransition(prev));
  }
  current = name;
  onChange(name);
  await Promise.all(waits);
  if (prev && current !== prev.dataset.screen) {
    prev.hidden = true;
    prev.className = "screen";
  }
  const heading = next.querySelector("h2");
  if (heading) {
    heading.tabIndex = -1;
    heading.focus({ preventScroll: true });
  }
  window.scrollTo({ top: 0 });
  if (screen.onEnter) screen.onEnter(next, stateRef);
}

function enqueue(job) {
  queue = queue.then(job, job);
  return queue;
}

export function go(name, { direction = "forward" } = {}) {
  if (name === lastTarget && name !== current) return queue;  // a double-click: already on its way
  lastTarget = name;
  return enqueue(() => swap(name, direction, direction !== "back"));
}

let backPending = false;

export function back() {
  if (backPending) return queue;  // a double-click on Back goes back once
  backPending = true;
  return enqueue(async () => {
    try {
      const previous = history.pop();
      if (!previous) return;
      lastTarget = previous;
      await swap(previous, "back", false);
    } finally {
      backPending = false;
    }
  });
}

export function canGoBack() {
  return history.length > 0;
}
