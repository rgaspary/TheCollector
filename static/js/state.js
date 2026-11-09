// Everything the screens share. Going back keeps answers, so screens read from here when they render.

export const state = {
  status: null,         // GET /api/status
  library: null,        // status.library, updated when the library is saved
  source: null,         // chosen source id
  sourceInfo: null,     // that source from GET /api/sources
  link: "",             // the pasted playlist link
  importResult: null,   // file import (later, with Apple Music)
  analysis: null,       // POST /api/analyze result
  decisions: {},        // close-match index → chosen path or "missing"
  resolved: null,       // POST /api/resolve result: {matched, missing}
  exportResult: null,   // POST /api/export/playlist result
  missingResult: null,  // POST /api/export/missing result
  returnTo: null,       // screen to come back to after fixing credentials
};
