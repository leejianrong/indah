// Wire-protocol constants and helpers shared by the shell.

export const PROTOCOL_VERSION = 1;

// Resolve API URLs relative to the current document so the shell works behind
// Colab/Runpod proxy base paths (ADR-0001).
export function apiUrl(path) {
  let base = location.href.split("#")[0].split("?")[0];
  if (!base.endsWith("/")) base += "/";
  return new URL(path, base).toString();
}

export function postEvent(id, event, payload) {
  fetch(apiUrl("api/event"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ component: id, event, payload: payload || {} }),
  }).catch(() => {});
}
