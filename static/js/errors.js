// Errors that send the user to another screen: a refused login goes to the Fix screen, a library
// problem goes to the library screen. Everything else is shown where it happened.
import { get } from "./api.js";
import { currentScreen, go } from "./router.js";
import { state } from "./state.js";
import { showError } from "./ui.js";

export async function handleApiError(err) {
  if (err.code === "credentials") {
    state.returnTo = currentScreen();
    state.source = err.data.source || state.source;
    try {
      const sources = await get("/api/sources");
      state.sourceInfo = sources.find((s) => s.id === state.source) || state.sourceInfo;
    } catch { /* the Fix screen loads them again */ }
    await go("credentials", { direction: "back" });
    return;
  }
  if (err.code === "library") {
    try {
      state.library = (await get("/api/status")).library;
    } catch { /* keep what we had */ }
    await go("library", { direction: "back" });
    showError(err.message);
    return;
  }
  showError(err.message);
}
