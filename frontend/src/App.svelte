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
</script>

<main class="card">
  <h1>indah</h1>
  {#if $structure}
    <Node node={$structure} />
  {/if}
  <div class="status">
    <span class="dot" class:live={$status.live}></span>
    <span>{$status.text}</span>
  </div>
</main>

{#if $toast}
  <button type="button" class="toast" onclick={() => toast.set(null)}>{$toast}</button>
{/if}
