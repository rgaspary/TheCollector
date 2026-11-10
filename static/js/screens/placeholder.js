// Stand-in for screens not built yet: only the Apple Music file import (postponed).
import { back, go } from "../router.js";
import { esc } from "../ui.js";

const PLACEHOLDERS = {
  library:     { title: "Your music library", next: "source", task: 19 },
  source:      { title: "Choose a music service", next: "link", task: 19 },
  credentials: { title: "Set up the service", next: "link", task: 20 },
  link:        { title: "Paste the playlist link", next: "review", task: 21 },
  import:      { title: "Import the playlist file", next: "review", task: "later" },
  review:      { title: "Review matches", next: "export", task: 21 },
  export:      { title: "Export the playlist", next: "missing", task: 22 },
  missing:     { title: "Missing songs", next: "done", task: 22 },
  done:        { title: "Done", next: null, task: 22 },
};

export function placeholder(name) {
  const p = PLACEHOLDERS[name];
  return {
    render(el) {
      el.innerHTML = `
        <div class="card">
          <h2>${esc(p.title)}</h2>
          <p class="muted">This screen is still being built (plan Task ${esc(p.task)}).</p>
          <div class="nav">
            ${name === "library" || name === "source" ? "" : '<button type="button" data-back>Back</button>'}
            ${p.next ? '<button type="button" class="primary" data-next>Continue</button>'
                     : '<button type="button" class="primary" data-restart>Start over</button>'}
          </div>
        </div>`;
      el.querySelector("[data-back]")?.addEventListener("click", () => back());
      el.querySelector("[data-next]")?.addEventListener("click", () => go(p.next));
      el.querySelector("[data-restart]")?.addEventListener("click", () => go("source", { direction: "back" }));
    },
  };
}
