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

// The session id stays out of the stream URL (access logs, proxy logs, history; IND-238).
// EventSource cannot set request headers, but the browser sends cookies on it, and resends
// them on its native reconnects, so a resume lands on the same session. The URL names this
// page's cookie with a random key (`?k=`), so two tabs never share one.
// Kept in sessionStorage like the session id, so a reload overwrites the tab's cookie
// instead of leaving a second one.
function tabKey() {
  try {
    let key = sessionStorage.getItem("indah-tab");
    if (!key) {
      key = "t" + newId().replace(/[^A-Za-z0-9]/g, "").slice(0, 24);
      sessionStorage.setItem("indah-tab", key);
    }
    return key;
  } catch (e) {
    return "t" + newId().replace(/[^A-Za-z0-9]/g, "").slice(0, 24); // storage blocked: this load only
  }
}
const TAB_KEY = tabKey();
let _cookieTimer = 0;
let _urlSid = typeof window !== "undefined" && !!window.__INDAH_LIVE__; // in-browser docs: no server

// Where cookies are not honoured for the stream (a page framed by another site, as in a
// Colab or Jupyter output; third-party cookies blocked), the id goes in the URL as before.
export function useUrlSid() {
  _urlSid = true;
}

// Sets this tab's cookie. Framed by another site, a cookie must be SameSite=None (and Secure)
// to be sent at all; otherwise Strict. The cookie is scoped to the stream route, so the page
// cannot read it back to check: a stream refused before it opens makes the shell fall back.
function setSessionCookie() {
  const path = appBase().pathname + "api/stream";
  let framed = false;
  try {
    framed = window.top !== window;
  } catch (e) {
    framed = true; // a cross-origin top refuses the access
  }
  const secure = location.protocol === "https:" || framed ? "; secure" : "";
  const same = framed ? "none" : "strict";
  const name = "indah_sid_" + TAB_KEY;
  document.cookie =
    name + "=" + sessionId() + "; path=" + path + "; max-age=1800; samesite=" + same + secure;
}

export function streamUrl() {
  const tail = "&path=" + encodeURIComponent(appPath());
  if (!_urlSid) {
    setSessionCookie();
    if (!_cookieTimer) _cookieTimer = setInterval(setSessionCookie, 60000); // outlive a long stream
    return apiUrl("api/stream") + "?k=" + TAB_KEY + tail;
  }
  return apiUrl("api/stream") + "?sid=" + encodeURIComponent(sessionId()) + tail;
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

// The route hint (IND-197, ADR-0043). With several processes behind one address, an event must reach
// the process that holds this tab's stream. Its init says which: `route: {hint, node, transport}`.
// The shell keeps the latest one in memory and sends it on every event and upload as X-Indah-Route;
// on Fly (`transport: "fly"`) it also sends `fly-force-instance-id`, which Fly Proxy obeys. Every
// init replaces it, and an init without one (the hint is off, or an older server) clears it.
let route = null;

export function setRoute(next) {
  route =
    next && typeof next.hint === "string" && /^[A-Za-z0-9]{1,32}$/.test(next.hint)
      ? { hint: next.hint, transport: next.transport }
      : null;
}

function routeHeaders() {
  if (!route) return {};
  const headers = { "X-Indah-Route": route.hint };
  if (route.transport === "fly") headers["fly-force-instance-id"] = route.hint;
  return headers;
}

// The server answers 409 `unknown_session` when this process does not hold the tab's session:
// it restarted, evicted it, or (with several processes and no affinity) another one has it
// (IND-199). `owner_unreachable` is the same to the tab. With the Fly header on, a 400 that is not
// indah's own JSON is Fly saying the machine is gone. The app registers one handler that re-opens
// the stream and tells the user.
let onSessionLost = null;

export function setSessionLostHandler(fn) {
  onSessionLost = fn;
}

async function lostSession(resp) {
  let lost = false;
  if (resp.status === 409) {
    try {
      const body = await resp.clone().json();
      lost = !!body && (body.error === "unknown_session" || body.error === "owner_unreachable");
    } catch (e) {
      lost = false;
    }
  } else if (resp.status === 400 && route && route.transport === "fly") {
    try {
      const body = await resp.clone().json();
      lost = !body || typeof body !== "object" || !("ok" in body);
    } catch (e) {
      lost = true; // not indah's JSON: the proxy refused a machine that no longer exists
    }
  }
  if (!lost) return false;
  route = null; // the old machine is not coming back for this tab; the next init names a new one
  if (onSessionLost) onSessionLost();
  return true;
}

export function postEvent(id, event, payload) {
  fetch(apiUrl("api/event"), {
    method: "POST",
    headers: { "Content-Type": "application/json", ...routeHeaders() },
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
  return fetch(apiUrl("api/upload"), { method: "POST", headers: routeHeaders(), body: form })
    .then(async (resp) => {
      if (!resp.ok) await lostSession(resp);
      return resp.ok;
    })
    .catch(() => false);
}

// The live socket (ADR-0045). The shell learns from window.__INDAH_CHROME__.live whether the server
// serves one; the URL is the document-relative path as ws(s), with the route hint as ?r= when there
// is one (a WebSocket cannot set request headers).
export function liveConfig() {
  const live = typeof window !== "undefined" ? (window.__INDAH_CHROME__ || {}).live : null;
  return live && typeof live.path === "string" ? live : null;
}

export function liveUrl() {
  const live = liveConfig();
  if (!live) return null;
  const url = new URL(apiUrl(live.path));
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  if (route) url.searchParams.set("r", route.hint);
  return url.toString();
}
