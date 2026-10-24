<script>
  import { onMount } from "svelte";
  import {
    apiUrl,
    streamUrl,
    ensureSession,
    pushPath,
    appPath,
    postEvent,
    setSessionLostHandler,
    PROTOCOL_VERSION,
  } from "./api.js";
  import {
    structure,
    nodeProps,
    status,
    toasts,
    shortcutRegistry,
    helpOpen,
    showToast,
    dismissToast,
  } from "./stores.js";
  import Node from "./Node.svelte";
  import Overlay from "./Overlay.svelte";


  // Optional page chrome injected by the server into the served shell (create_app
  // args; the demo gallery sets them per demo): a clickable logo back to the
  // gallery (home_url), a view-source link (source_url), and a distinct tab title.
  const chrome = (typeof window !== "undefined" && window.__INDAH_CHROME__) || {};

  // Split an init tree into a skeleton (structure) plus a flat id->props map.
  function splitTree(node, map) {
    map.set(node.id, node.props || {});
    return {
      id: node.id,
      type: node.type,
      children: (node.children || []).map((child) => splitTree(child, map)),
    };
  }

  function runToastAction(t) {
    dismissToast(t.id);
    postEvent("__toast__", "action", { id: t.action.id });
  }

  function findRouter(node) {
    if (node.type === "router") return node;
    for (const child of node.children || []) {
      const hit = findRouter(child);
      if (hit) return hit;
    }
    return null;
  }

  // Set when the login ended (a signed_out message, a refused handshake). The tree is dropped,
  // so nothing the user saw stays in memory or on screen, and the stream is not reopened.
  let signedOut = $state(false);
  function endSession(text) {
    signedOut = true;
    structure.set(null);
    nodeProps.set(new Map());
    status.set({ live: false, text });
  }

  // The tab's own title and icon, as the page loaded, so ctx.title / ctx.favicon can be undone
  // (a null puts them back). Only a favicon this app registered is ever applied (IND-152).
  const ownTitle = document.title;
  const iconLink = document.querySelector('link[rel~="icon"]');
  const ownIcon = iconLink ? iconLink.getAttribute("href") : null;
  function applyChrome(chrome) {
    const title = chrome && typeof chrome.title === "string" ? chrome.title : null;
    document.title = title ?? ownTitle;
    if (!iconLink) return;
    const icon = chrome && typeof chrome.favicon === "string" ? chrome.favicon : null;
    const registered = icon && icon.startsWith("api/brand/favicon/");
    const href = registered ? icon : ownIcon;
    if (href !== null) iconLink.setAttribute("href", href);
    // Pages with an SVG-only default carry a `type`; a registered PNG would be ignored under it.
    if (registered) iconLink.removeAttribute("type");
  }

  let inits = 0;
  function applyMessage(msg) {
    if (!msg || msg.v !== PROTOCOL_VERSION) {
      status.set({ live: false, text: "protocol mismatch, reload" });
      return;
    }
    if (msg.type === "init") {
      applyChrome(msg.chrome); // a fresh init restores the session's title and icon, or the app's
      const map = new Map();
      structure.set(splitTree(msg.root, map));
      nodeProps.set(map);
      // A re-init (the server restarted, or the buffer had a gap) was built for the path in
      // the stream URL from the first connect, which may be a page the tab has left. Tell the
      // server which page the address bar is on now; the reply is an ordinary patch.
      const router = inits++ > 0 ? findRouter(msg.root) : null;
      if (router) postEvent(router.id, "navigate", { path: appPath() });
    } else if (msg.type === "patch") {
      nodeProps.update((map) => {
        for (const change of msg.changes || []) {
          const cur = map.get(change.target) || {};
          if (change.append) {
            // Concatenate a streamed delta onto the existing prop value: strings
            // grow token-by-token (StreamText), arrays grow point-by-point (Chart).
            const next = { ...cur };
            for (const [key, delta] of Object.entries(change.append)) {
              const base = next[key];
              if (Array.isArray(base) || Array.isArray(delta)) {
                next[key] = (base ?? []).concat(delta);
              } else {
                next[key] = (base ?? "") + delta;
              }
            }
            // `trim` caps a grown array to its newest N entries (a bounded live log).
            for (const [key, keep] of Object.entries(change.trim || {})) {
              if (Array.isArray(next[key]) && next[key].length > keep) {
                next[key] = next[key].slice(-keep);
              }
            }
            map.set(change.target, next);
          } else {
            map.set(change.target, { ...cur, ...(change.props || {}) });
          }
        }
        return new Map(map);
      });
    } else if (msg.type === "error") {
      showToast(msg.message || "Something went wrong", "error", 6);
    } else if (msg.type === "navigate") {
      pushPath(msg.path || "/", !!msg.replace); // ctx.navigate from server code
    } else if (msg.type === "chrome") {
      applyChrome(msg);
    } else if (msg.type === "signed_out") {
      applyChrome(null);
      endSession("signed out");
    } else if (msg.type === "toast") {
      const a = msg.action && msg.action.id && msg.action.label ? msg.action : null;
      showToast(msg.message || "", msg.kind || "info", msg.ttl ?? 4, a);
    }
  }

  onMount(() => {
    // EventSource resends Last-Event-Id on reconnect natively; the server replays
    // the missed messages, so a dropped stream resumes without extra client code.
    let source = null;
    let closed = false;
    let restarts = 0;
    // A draining server (a rollout) sent `reconnect` (IND-201): this tab leaves its stream and
    // keeps trying until some process takes it. Refused with 503 while the old one still
    // listens, refused outright while nothing does, so it retries with a growing delay.
    let leaving = false;
    let attempts = 0;
    let timer = null;

    function retryIn(ms) {
      clearTimeout(timer);
      timer = setTimeout(
        () => {
          if (!closed && !signedOut) start();
        },
        ms + Math.random() * 500,
      );
    }

    function leave(afterMs) {
      leaving = true;
      attempts = 0;
      if (source) source.close();
      status.update((s) => ({ ...s, live: false, text: "reconnecting…" }));
      retryIn(Math.max(0, Number(afterMs) || 0));
    }

    function connect() {
      source = new EventSource(streamUrl());
      source.onopen = () => {
        leaving = false;
        attempts = 0;
        status.set({ live: true, text: "live" });
      };
      source.onmessage = (event) => {
        if (signedOut) return;
        try {
          const msg = JSON.parse(event.data);
          if (msg && msg.type === "reconnect") {
            leave(msg.after_ms);
            return;
          }
          status.set({ live: true, text: "live" });
          applyMessage(msg);
          if (msg && msg.type === "signed_out") source.close(); // no reconnect after sign-out
        } catch (err) {
          /* ignore malformed frame */
        }
      };
      source.onerror = () => {
        if (signedOut) return;
        status.update((s) => ({ ...s, live: false, text: "reconnecting…" }));
        if (leaving) {
          // CLOSED: refused (503 from a draining server). Otherwise EventSource retries by itself.
          if (source.readyState === EventSource.CLOSED) {
            source.close();
            attempts++;
            if (attempts === 3) showToast("Still reconnecting…", "warn", 4);
            if (attempts <= 15) retryIn(Math.min(1000 * attempts, 5000));
          }
          return;
        }
        // CLOSED means the server refused the stream (401/403), not a dropped connection
        // (which EventSource retries itself): get a session again, once or twice, then give up.
        if (source.readyState === EventSource.CLOSED && restarts++ < 2) start();
      };
    }

    // A secure app hands out the session id (a signed token) first; a plain app connects at once.
    function start() {
      if (source) source.close();
      ensureSession()
        .then(() => {
          if (!closed) connect();
        })
        .catch((err) =>
          err && err.status === 401
            ? endSession("signed out")
            : status.set({ live: false, text: "could not start a session" }),
        );
    }
    start();

    // The server no longer holds this tab's session (it restarted, evicted it, or another process
    // has it): an event came back 409 unknown_session (IND-199). Open the stream again for a fresh
    // init, and say so once, instead of letting the click vanish. At most one recovery every few
    // seconds, so two processes without affinity cannot make this a loop.
    let lastRecover = 0;
    let lastToast = 0;
    setSessionLostHandler(() => {
      const now = Date.now();
      if (closed || signedOut || now - lastRecover < 3000) return;
      lastRecover = now;
      if (now - lastToast > 15000) {
        lastToast = now;
        showToast("Reconnected. Your last action was not applied, please try it again.", "info", 6);
      }
      restarts = 0;
      start();
    });
    return () => {
      closed = true;
      clearTimeout(timer);
      setSessionLostHandler(null);
      if (source) source.close();
    };
  });

  // Theme: "system" | "light" | "dark", persisted in localStorage. A <head>
  // script already resolved the saved choice into data-theme before first paint;
  // here we manage the toggle and keep "system" in sync with OS changes.
  let theme = $state("system");

  function applyTheme(choice) {
    const dark =
      choice === "dark" ||
      (choice === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
    document.documentElement.dataset.theme = dark ? "dark" : "light";
  }

  function setTheme(choice) {
    theme = choice;
    try {
      localStorage.setItem("indah-theme", choice);
    } catch (e) {
      /* storage may be blocked; the in-memory choice still applies */
    }
    applyTheme(choice);
  }

  onMount(() => {
    try {
      theme = localStorage.getItem("indah-theme") || "system";
    } catch (e) {
      /* ignore */
    }
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onSystemChange = () => {
      if (theme === "system") applyTheme("system");
    };
    mq.addEventListener("change", onSystemChange);
    return () => mq.removeEventListener("change", onSystemChange);
  });
</script>

<div class="shell">
  <header class="brand">
    <svelte:element
      this={chrome.homeUrl ? "a" : "div"}
      class="brand-id"
      href={chrome.homeUrl}
      title={chrome.homeUrl ? "Back to the gallery" : null}
      aria-label={chrome.homeUrl ? "Back to the gallery" : null}
    >
      {#if chrome.logoUrl}
        <img
          class="mark"
          class:mark-light={chrome.logoDarkUrl}
          src={apiUrl(chrome.logoUrl)}
          alt={chrome.brandName || "logo"}
        />
        {#if chrome.logoDarkUrl}
          <img class="mark mark-dark" src={apiUrl(chrome.logoDarkUrl)} alt="" />
        {/if}
      {:else}
        <svg class="mark" viewBox="0 0 32 32" aria-label="indah" role="img">
          <path d="M16 16C11.7 12.4 11.7 6 16 3.6C20.3 6 20.3 12.4 16 16Z" fill="var(--brand-a)" />
          <path d="M16 16C20.3 19.6 20.3 26 16 28.4C11.7 26 11.7 19.6 16 16Z" fill="var(--brand-a)" />
          <path d="M16 16C12.4 20.3 6 20.3 3.6 16C6 11.7 12.4 11.7 16 16Z" fill="var(--brand-b)" />
          <path d="M16 16C19.6 20.3 26 20.3 28.4 16C26 11.7 19.6 11.7 16 16Z" fill="var(--brand-b)" />
        </svg>
      {/if}
      <span class="wordmark">{chrome.brandName || "indah"}</span>
    </svelte:element>
    <span class="spacer"></span>
    {#if chrome.sourceUrl}
      <a
        class="source-link"
        href={chrome.sourceUrl}
        target="_blank"
        rel="noopener noreferrer"
        title="View source on GitHub"
      >
        <svg viewBox="0 0 24 24" width="15" height="15" fill="currentColor" aria-hidden="true">
          <path
            d="M12 .5C5.7.5.5 5.7.5 12c0 5.1 3.3 9.4 7.9 10.9.6.1.8-.3.8-.6v-2c-3.2.7-3.9-1.4-3.9-1.4-.5-1.3-1.3-1.7-1.3-1.7-1.1-.7.1-.7.1-.7 1.2.1 1.8 1.2 1.8 1.2 1 1.8 2.8 1.3 3.5 1 .1-.8.4-1.3.7-1.6-2.6-.3-5.3-1.3-5.3-5.8 0-1.3.5-2.3 1.2-3.1-.1-.3-.5-1.5.1-3.1 0 0 1-.3 3.3 1.2a11.5 11.5 0 0 1 6 0C17 4.4 18 4.7 18 4.7c.6 1.6.2 2.8.1 3.1.8.8 1.2 1.8 1.2 3.1 0 4.5-2.7 5.5-5.3 5.8.4.4.8 1.1.8 2.2v3.3c0 .3.2.7.8.6 4.6-1.5 7.9-5.8 7.9-10.9C23.5 5.7 18.3.5 12 .5z"
          />
        </svg>
        <span>Source</span>
      </a>
    {/if}
    <div class="theme-toggle" role="group" aria-label="Theme">
      <button
        type="button"
        title="Follow system theme"
        aria-label="System theme"
        aria-pressed={theme === "system"}
        onclick={() => setTheme("system")}
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <rect x="3" y="4" width="18" height="13" rx="2" />
          <path d="M8 20h8M12 17v3" />
        </svg>
      </button>
      <button
        type="button"
        title="Light theme"
        aria-label="Light theme"
        aria-pressed={theme === "light"}
        onclick={() => setTheme("light")}
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="4" />
          <path
            d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"
          />
        </svg>
      </button>
      <button
        type="button"
        title="Dark theme"
        aria-label="Dark theme"
        aria-pressed={theme === "dark"}
        onclick={() => setTheme("dark")}
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />
        </svg>
      </button>
    </div>
  </header>
  {#if signedOut}
    <div class="signed-out" role="alert">
      <h2>You are signed out</h2>
      <p>Your session has ended. Sign in again to continue.</p>
      <button type="button" onclick={() => location.reload()}>Sign in again</button>
    </div>
  {:else if $structure}
    <Node node={$structure} />
  {/if}
  <div class="status">
    <span class="dot" class:live={$status.live}></span>
    <span>{$status.text}</span>
  </div>
</div>

{#if $helpOpen}
  <Overlay kind="modal" size="sm" title="Keyboard shortcuts" onclose={() => helpOpen.set(false)}>
    <table class="shortcut-help">
      <tbody>
        {#each [...$shortcutRegistry.values()].flat() as entry}
          <tr>
            <td>{#each entry.keys.split(" ") as step, i}{#if i > 0}<span class="then"> then </span>{/if}<kbd>{step}</kbd>{/each}</td>
            <td>{entry.label}</td>
          </tr>
        {/each}
        <tr><td><kbd>?</kbd></td><td>This help</td></tr>
        <tr><td><kbd>escape</kbd></td><td>Close dialogs</td></tr>
      </tbody>
    </table>
  </Overlay>
{/if}

{#if $toasts.length}
  <div class="toasts" role="status" aria-live="polite">
    {#each $toasts as t (t.id)}
      {#if t.action}
        <div class="toast has-action {t.kind}">
          <span class="toast-text">{t.message}</span>
          <button type="button" class="toast-action" onclick={() => runToastAction(t)}>{t.action.label}</button>
          <button type="button" class="toast-close" aria-label="Dismiss" onclick={() => dismissToast(t.id)}>&times;</button>
        </div>
      {:else}
        <button type="button" class="toast {t.kind}" onclick={() => dismissToast(t.id)}>{t.message}</button>
      {/if}
    {/each}
  </div>
{/if}
