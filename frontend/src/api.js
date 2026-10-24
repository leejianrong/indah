// Wire-protocol constants and helpers shared by the shell.

export const PROTOCOL_VERSION = 1;

// Resolve API URLs relative to the document's base so the shell works behind
// Colab/Runpod proxy base paths (ADR-0001). baseURI is the page URL, or the server's
// relative <base href> on a deep in-app path (spa=True), so api/* always reaches the
// app root.
export function apiUrl(path) {
  return new URL(path, appBase()).toString();
}

// The app root as a URL: the directory of the document base. "." resolves against the
// page URL when there is no <base> (a one-segment deep link like /ui/zzz, or the root),
// and against the relative <base href="../"> otherwise, so both land on the app root.
// Captured once at load: pushState (in-app navigation) changes the page URL, and a page
// with no <base> would otherwise resolve api/* against the new, deeper URL.
const APP_BASE = new URL(".", document.baseURI);
function appBase() {
  return APP_BASE;
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

// A secure app (ADR-0033) does not accept a browser-minted id: the shell first trades the
// caller's login for a signed session token with POST api/session, and that token is the
// session id from then on. The old token is sent as `resume`, so a reload keeps its session
// when it is still this user's. Resolves to the token, or rejects with the HTTP status.
const SECURE = !!(typeof window !== "undefined" && (window.__INDAH_CHROME__ || {}).secure);

export function isSecure() {
  return SECURE;
}

export async function ensureSession(fresh = false) {
  if (!SECURE) return sessionId();
  let resume = null;
  if (!fresh) {
    try {
      resume = sessionStorage.getItem("indah-sid");
    } catch (e) {
      resume = _sid || null;
    }
  }
  const resp = await fetch(apiUrl("api/session"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ resume }),
    credentials: "same-origin",
  });
  if (!resp.ok) throw Object.assign(new Error("session " + resp.status), { status: resp.status });
  const { token } = await resp.json();
  _sid = token;
  try {
    sessionStorage.setItem("indah-sid", token);
  } catch (e) {
    /* storage blocked: the in-memory token still works for this load */
  }
  return token;
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
  return (
    apiUrl("api/stream") +
    "?sid=" +
    encodeURIComponent(sessionId()) +
    "&path=" +
    encodeURIComponent(appPath())
  );
}

// -- In-app routing (ADR-0029). The app may be mounted under a prefix (/ui/), so an
// "in-app path" is the page's path relative to the document base: /ui/projects/auth is
// /projects/auth. The base is the app root whatever the depth of the current URL.
function baseDir() {
  return appBase().pathname;
}

export function appPath() {
  const base = baseDir();
  const here = location.pathname;
  if (!here.startsWith(base)) return "/";
  return ("/" + here.slice(base.length)).replace(/\/+$/, "") || "/";
}

// The real URL of an in-app path, for an <a href> and for history.pushState.
export function hrefFor(path) {
  return baseDir() + String(path).replace(/^\/+/, "");
}

export function pushPath(path, replace = false) {
  const href = hrefFor(path);
  if (location.pathname === href) return;
  if (replace) history.replaceState({}, "", href);
  else history.pushState({}, "", href);
}

// The server answers 409 `unknown_session` when this process does not hold the tab's session:
// it restarted, evicted it, or (with several processes and no affinity) another one has it
// (IND-199). The app registers one handler that re-opens the stream and tells the user.
let onSessionLost = null;

export function setSessionLostHandler(fn) {
  onSessionLost = fn;
}

async function lostSession(resp) {
  if (resp.status !== 409) return false;
  try {
    const body = await resp.clone().json();
    if (!body || body.error !== "unknown_session") return false;
  } catch (e) {
    return false;
  }
  if (onSessionLost) onSessionLost();
  return true;
}

export function postEvent(id, event, payload) {
  fetch(apiUrl("api/event"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sid: sessionId(), component: id, event, payload: payload || {} }),
  })
    .then(lostSession)
    .catch(() => {});
}

// Upload one or more files as multipart/form-data (ADR-0017), on its own route so
// binary never rides the JSON event path. The result flows back over SSE, so this
// only needs to report whether the POST itself was accepted. Returns a promise.
export function postUpload(id, files) {
  const form = new FormData();
  form.append("sid", sessionId());
  form.append("component", id);
  for (const file of files) form.append("file", file);
  return fetch(apiUrl("api/upload"), { method: "POST", body: form })
    .then(async (resp) => {
      if (!resp.ok) await lostSession(resp);
      return resp.ok;
    })
    .catch(() => false);
}
