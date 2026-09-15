// Wire-protocol constants and helpers shared by the shell.

export const PROTOCOL_VERSION = 1;

// Resolve API URLs relative to the current document so the shell works behind
// Colab/Runpod proxy base paths (ADR-0001).
export function apiUrl(path) {
  let base = location.href.split("#")[0].split("?")[0];
  if (!base.endsWith("/")) base += "/";
  return new URL(path, base).toString();
}

// A per-tab session id, so each browser tab drives its own isolated server-side
// session (ADR-0010). sessionStorage is scoped to one tab and survives a reload,
// so a reconnecting tab resumes the same session while a fresh tab gets a fresh
// one. Falls back to an in-memory id where crypto/storage is unavailable.
let _sid;

function newId() {
  try {
    if (globalThis.crypto && crypto.randomUUID) return crypto.randomUUID();
  } catch (e) {
    /* fall through */
  }
  return "sid-" + Math.random().toString(36).slice(2) + Date.now().toString(36);
}

export function sessionId() {
  if (_sid) return _sid;
  try {
    _sid = sessionStorage.getItem("indah-sid");
    if (!_sid) {
      _sid = newId();
      sessionStorage.setItem("indah-sid", _sid);
    }
  } catch (e) {
    _sid = newId(); // storage blocked: an in-memory id still isolates this tab
  }
  return _sid;
}

// The SSE stream URL carries the session id as a query param -- EventSource cannot
// set request headers, and it preserves the URL (and resends Last-Event-Id) across
// its native reconnects, so a resume lands on the same session.
export function streamUrl() {
  return apiUrl("api/stream") + "?sid=" + encodeURIComponent(sessionId());
}

export function postEvent(id, event, payload) {
  fetch(apiUrl("api/event"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sid: sessionId(), component: id, event, payload: payload || {} }),
  }).catch(() => {});
}
