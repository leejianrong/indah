<script>
  import { onMount } from "svelte";
  import { apiUrl, PROTOCOL_VERSION } from "./api.js";
  import { structure, nodeProps, status, toast } from "./stores.js";
  import Node from "./Node.svelte";

  let toastTimer;

  // Split an init tree into a skeleton (structure) plus a flat id->props map.
  function splitTree(node, map) {
    map.set(node.id, node.props || {});
    return {
      id: node.id,
      type: node.type,
      children: (node.children || []).map((child) => splitTree(child, map)),
    };
  }

  function showToast(message) {
    toast.set(message);
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.set(null), 6000);
  }

  function applyMessage(msg) {
    if (!msg || msg.v !== PROTOCOL_VERSION) {
      status.set({ live: false, text: "protocol mismatch, reload" });
      return;
    }
    if (msg.type === "init") {
      const map = new Map();
      structure.set(splitTree(msg.root, map));
      nodeProps.set(map);
    } else if (msg.type === "patch") {
      nodeProps.update((map) => {
        for (const change of msg.changes || []) {
          const cur = map.get(change.target) || {};
          if (change.append) {
            // Concatenate a streamed delta onto the existing prop value.
            const next = { ...cur };
            for (const [key, delta] of Object.entries(change.append)) {
              next[key] = (next[key] ?? "") + delta;
            }
            map.set(change.target, next);
          } else {
            map.set(change.target, { ...cur, ...(change.props || {}) });
          }
        }
        return new Map(map);
      });
    } else if (msg.type === "error") {
      showToast(msg.message || "Something went wrong");
    }
  }

  onMount(() => {
    // EventSource resends Last-Event-Id on reconnect natively; the server replays
    // the missed messages, so a dropped stream resumes without extra client code.
    const source = new EventSource(apiUrl("api/stream"));
    source.onopen = () => status.set({ live: true, text: "live" });
    source.onmessage = (event) => {
      status.set({ live: true, text: "live" });
      try {
        applyMessage(JSON.parse(event.data));
      } catch (err) {
        /* ignore malformed frame */
      }
    };
    source.onerror = () => status.update((s) => ({ ...s, live: false, text: "reconnecting…" }));
    return () => {
      clearTimeout(toastTimer);
      source.close();
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
    <svg class="mark" viewBox="0 0 32 32" aria-label="indah" role="img">
      <path d="M16 16C11.7 12.4 11.7 6 16 3.6C20.3 6 20.3 12.4 16 16Z" fill="var(--primary)" />
      <path d="M16 16C20.3 19.6 20.3 26 16 28.4C11.7 26 11.7 19.6 16 16Z" fill="var(--primary)" />
      <path d="M16 16C12.4 20.3 6 20.3 3.6 16C6 11.7 12.4 11.7 16 16Z" fill="var(--secondary)" />
      <path d="M16 16C19.6 20.3 26 20.3 28.4 16C26 11.7 19.6 11.7 16 16Z" fill="var(--secondary)" />
    </svg>
    <span class="wordmark">indah</span>
    <span class="spacer"></span>
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
  {#if $structure}
    <Node node={$structure} />
  {/if}
  <div class="status">
    <span class="dot" class:live={$status.live}></span>
    <span>{$status.text}</span>
  </div>
</div>

{#if $toast}
  <button type="button" class="toast" onclick={() => toast.set(null)}>{$toast}</button>
{/if}
