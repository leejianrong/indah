<script>
  // One node of a JsonTree (IND-108). Children are created only when the node is open,
  // and in chunks, so a big document costs nothing until you look inside it.
  import Self from "./JsonNode.svelte";

  let { value, name = null, path = [], id = "$", depth = 0, view } = $props();

  const CHUNK = 100;
  const isObj = $derived(value !== null && typeof value === "object");
  const isArr = $derived(Array.isArray(value));
  const keys = $derived(isObj ? Object.keys(value) : []);

  let userOpen = $state(null); // null = follow the default (depth / search), else the user's choice
  let seenEpoch = view.epoch;
  $effect(() => {
    if (view.epoch !== seenEpoch) {
      seenEpoch = view.epoch;
      userOpen = null; // "Collapse all"
    }
  });
  const open = $derived(isObj && (userOpen ?? (view.forced.has(id) || depth < view.expanded)));
  let shown = $state(CHUNK);
  // The children to render: the first `shown`, plus any further child that is a search hit
  // or on the path to one (so a hit deep in a long list is visible without rendering every
  // sibling before it).
  const visibleKeys = $derived.by(() => {
    if (!open) return [];
    const head = keys.slice(0, shown);
    if (view.forced.size === 0 && view.matches.size === 0) return head;
    for (let i = shown; i < keys.length; i++) {
      const cid = `${id}\u0000${keys[i]}`;
      if (view.forced.has(cid) || view.matches.has(cid)) head.push(keys[i]);
    }
    return head;
  });
  let copied = $state(false);

  const matched = $derived(view.matches.has(id));

  function jsonPath(p) {
    return (
      "$" +
      p
        .map((seg) =>
          typeof seg === "number"
            ? `[${seg}]`
            : /^[A-Za-z_$][\w$]*$/.test(seg)
              ? `.${seg}`
              : `[${JSON.stringify(seg)}]`,
        )
        .join("")
    );
  }

  async function copyPath() {
    const text = jsonPath(path);
    try {
      await navigator.clipboard.writeText(text);
    } catch (e) {
      const ta = document.createElement("textarea"); // clipboard API blocked (http, iframe)
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      try {
        document.execCommand("copy");
      } catch (err) {
        /* nothing more to try */
      }
      ta.remove();
    }
    copied = true;
    setTimeout(() => (copied = false), 1200);
  }

  function preview(v) {
    if (typeof v === "string") return JSON.stringify(v.length > 200 ? v.slice(0, 200) + "…" : v);
    return String(v);
  }
  const kind = $derived(v_kind(value));
  function v_kind(v) {
    if (v === null) return "null";
    return typeof v;
  }
</script>

<li role="treeitem" aria-expanded={isObj ? open : undefined} class="jt-item">
  <div class="jt-row" class:match={matched}>
    {#if isObj}
      <button
        type="button"
        class="jt-toggle"
        aria-label={open ? "Collapse" : "Expand"}
        onclick={() => (userOpen = !open)}>{open ? "▾" : "▸"}</button
      >
    {:else}
      <span class="jt-toggle spacer"></span>
    {/if}
    {#if name !== null}<span class="jt-key">{typeof name === "number" ? name : JSON.stringify(name)}</span
      ><span class="jt-colon">: </span>{/if}
    {#if isObj}
      <span class="jt-summary"
        >{isArr ? "[" : "{"}{#if !open} … {keys.length} {isArr ? "items" : "keys"} {/if}{isArr
          ? "]"
          : "}"}</span
      >
    {:else}
      <span class="jt-val {kind}" title={typeof value === "string" ? value : null}>{preview(value)}</span>
    {/if}
    <button
      type="button"
      class="jt-copy"
      aria-label="Copy path {jsonPath(path)}"
      title="Copy path"
      onclick={copyPath}>{copied ? "copied" : "path"}</button
    >
  </div>
  {#if open}
    <ul role="group" class="jt-children">
      {#each visibleKeys as key (key)}
        <Self
          value={value[key]}
          name={isArr ? Number(key) : key}
          path={[...path, isArr ? Number(key) : key]}
          id={`${id}\u0000${key}`}
          depth={depth + 1}
          {view}
        />
      {/each}
      {#if keys.length > shown}
        <li class="jt-more">
          <button type="button" onclick={() => (shown += 2 * CHUNK)}
            >Show {Math.min(2 * CHUNK, keys.length - shown)} more ({keys.length - shown} left)</button
          >
        </li>
      {/if}
    </ul>
  {/if}
</li>

<style>
  .jt-item { list-style: none; }
  .jt-children { margin: 0; padding-left: 1.1rem; border-left: 1px solid var(--outline-soft); margin-left: 0.4rem; }
  .jt-row { display: flex; align-items: baseline; gap: 0.15rem; padding: 0.05rem 0.2rem; border-radius: 4px; font-family: var(--font-mono); font-size: 0.82rem; }
  .jt-row:hover { background: var(--surface-2); }
  .jt-row.match { background: color-mix(in srgb, var(--warn) 22%, transparent); }
  .jt-toggle { width: 1.1rem; padding: 0; background: none; border: none; color: var(--muted); cursor: pointer; font-size: 0.8rem; align-self: auto; border-radius: 3px; }
  .jt-toggle.spacer { cursor: default; }
  .jt-key { color: var(--primary); }
  .jt-colon, .jt-summary { color: var(--muted); }
  .jt-val { word-break: break-all; }
  .jt-val.string { color: var(--ok); }
  .jt-val.number { color: var(--warn); }
  .jt-val.boolean, .jt-val.null { color: var(--muted); font-style: italic; }
  .jt-copy { margin-left: auto; padding: 0 0.4rem; font-size: 0.7rem; background: none; border: 1px solid var(--outline); color: var(--muted); border-radius: var(--radius-pill); opacity: 0; align-self: auto; font-weight: 500; }
  .jt-row:hover .jt-copy, .jt-copy:focus-visible { opacity: 1; }
  .jt-more button { font-size: 0.78rem; padding: 0.1rem 0.6rem; align-self: auto; }
</style>
