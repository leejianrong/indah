<script>
  // Read-only JSON viewer (IND-108): lazy tree, text search that opens the path to each
  // match (time-sliced, so a 1 MB document never blocks a frame) and copy-path buttons.
  import JsonNode from "./JsonNode.svelte";

  let { props } = $props();

  const doc = $derived(props.doc ?? { data: null, error: null });
  const MAX_MATCHES = 500;
  const SLICE_MS = 8;

  let query = $state("");
  let view = $state({ expanded: 1, forced: new Set(), matches: new Set(), epoch: 0 });
  let status = $state(""); // "", "searching", or the count line
  $effect(() => {
    view.expanded = props.expanded ?? 1;
  });

  let runId = 0;
  const wait = () => new Promise((resolve) => setTimeout(resolve, 0));

  async function search(q, data) {
    const id = ++runId;
    const needle = q.trim().toLowerCase();
    if (!needle || data === null) {
      view.forced = new Set();
      view.matches = new Set();
      status = "";
      return;
    }
    status = "searching…";
    const forced = new Set();
    const matches = new Set();
    // Iterative DFS, yielding to the event loop every SLICE_MS so typing stays smooth.
    // Parent links instead of copied ancestor lists keep each step O(1); a match walks up
    // once to open its path.
    const markPath = (node) => {
      for (let n = node.parent; n; n = n.parent) {
        if (forced.has(n.id)) break; // everything above is already open
        forced.add(n.id);
      }
    };
    const stack = [{ v: data, id: "$", parent: null }];
    let t0 = performance.now();
    let visited = 0;
    while (stack.length && matches.size < MAX_MATCHES) {
      const node = stack.pop();
      const v = node.v;
      if (v !== null && typeof v === "object") {
        for (const k of Object.keys(v)) {
          const child = { v: v[k], id: `${node.id}\u0000${k}`, parent: node };
          if (k.toLowerCase().includes(needle)) {
            matches.add(child.id);
            forced.add(node.id);
            markPath(node);
          }
          stack.push(child);
        }
      } else if (String(v).toLowerCase().includes(needle)) {
        matches.add(node.id);
        markPath(node);
      }
      if ((++visited & 255) === 0 && performance.now() - t0 > SLICE_MS) {
        await wait();
        if (id !== runId) return; // a newer query took over
        t0 = performance.now();
      }
    }
    if (id !== runId) return;
    view.forced = forced;
    view.matches = matches;
    status = matches.size >= MAX_MATCHES ? `${MAX_MATCHES}+ matches` : `${matches.size} matches`;
  }

  let timer = null;
  function onInput() {
    clearTimeout(timer);
    timer = setTimeout(() => search(query, doc.data), 200);
  }
  // A new document invalidates the old matches.
  $effect(() => {
    const data = doc.data;
    if (query.trim()) search(query, data);
  });
</script>

<div class="field jsontree">
  {#if props.label}<span class="stream-label">{props.label}</span>{/if}
  {#if doc.error}
    <div class="jt-error" role="alert">{doc.error}</div>
  {:else}
    <div class="jt-toolbar">
      {#if props.search}
        <input
          type="search"
          class="table-search"
          placeholder="Search keys and values"
          aria-label="Search JSON"
          bind:value={query}
          oninput={onInput}
        />
        {#if status}<span class="table-count" aria-live="polite">{status}</span>{/if}
      {/if}
      <button type="button" class="ghost jt-collapse" onclick={() => (view.epoch += 1)}>Collapse all</button>
    </div>
    <ul role="tree" class="jt-root">
      {#if doc.data === null}
        <li class="jt-empty">null</li>
      {:else}
        <JsonNode value={doc.data} {view} />
      {/if}
    </ul>
  {/if}
</div>

<style>
  .jt-root { margin: 0; padding: 0.3rem 0.4rem; max-height: 28rem; overflow: auto; background: var(--surface-2); border: 1px solid var(--outline-soft); border-radius: var(--radius-sm); }
  .jt-toolbar { display: flex; gap: 0.6rem; align-items: center; margin-bottom: 0.4rem; }
  .jt-collapse { padding: 0.2rem 0.8rem; font-size: 0.8rem; align-self: auto; margin-left: auto; }
  .jt-error { color: var(--err); font-family: var(--font-mono); font-size: 0.85rem; }
  .jt-empty { list-style: none; color: var(--muted); }
</style>
