<script>
  // CommandPalette (IND-165): a keyboard palette. The shortcut (mod+k by default) opens a dialog
  // with a filter box over the loaded commands; arrows move, Enter runs, Escape closes and gives
  // focus back to where it was. The filter runs here, over the list the server sent, so typing
  // never touches the server; only running a command posts `run {command}`. Keys follow the
  // routing rule in ADR-0030: the shortcut is a window listener that skips a key someone
  // already handled, never opens over another dialog, ignores a bare key typed into a field
  // (a mod+ combo still opens it), and defaults the keys it handles. A confirm= command asks
  // first like Button.
  import { tick } from "svelte";
  import { postEvent } from "./api.js";
  import { shortcutRegistry } from "./stores.js";
  import Overlay from "./Overlay.svelte";

  let { node, props } = $props();

  const uid = `cp-${Math.random().toString(36).slice(2, 8)}`;
  let commands = $derived(props.commands ?? []);
  let open = $state(false);
  let query = $state("");
  let active = $state(0);
  let confirming = $state(null);
  let input = $state();
  let list = $state();
  let opener = null;

  // Show the shortcut in the `?` help overlay while the palette is mounted.
  $effect(() => {
    const entry = [{ keys: props.shortcut ?? "mod+k", label: props.label || "Open the command palette" }];
    shortcutRegistry.update((m) => new Map(m).set(node.id, entry));
    return () =>
      shortcutRegistry.update((m) => {
        const next = new Map(m);
        next.delete(node.id);
        return next;
      });
  });

  // Match order (documented in the Python docstring, and kept stable): the label starts with the
  // query, then a word of it does, then it contains the query, then the query is a subsequence of
  // it, then a keyword or the group contains it. Within a tier the order the app gave is kept.
  function subsequence(text, q) {
    let i = 0;
    for (const ch of text) if (ch === q[i] && ++i === q.length) return true;
    return q.length === 0;
  }
  function tier(cmd, q) {
    const label = cmd.label.toLowerCase();
    if (label.startsWith(q)) return 0;
    if (label.split(/[\s\-_/.:]+/).some((w) => w.startsWith(q))) return 1;
    if (label.includes(q)) return 2;
    if (subsequence(label, q.replace(/\s+/g, ""))) return 3;
    const extra = [...(cmd.keywords ?? []), cmd.group ?? ""].join(" ").toLowerCase();
    if (extra.includes(q)) return 4;
    return -1;
  }
  let results = $derived.by(() => {
    const q = query.trim().toLowerCase();
    if (!q) return commands.map((c, i) => ({ c, i }));
    return commands
      .map((c, i) => ({ c, i, t: tier(c, q) }))
      .filter((r) => r.t >= 0)
      .sort((a, b) => a.t - b.t || a.i - b.i);
  });
  $effect(() => {
    // A new list or a new query starts again at the top, and never points past the end.
    results;
    active = 0;
  });

  async function show() {
    if (open) return;
    opener = document.activeElement;
    query = "";
    active = 0;
    open = true;
    await tick();
    input?.focus();
  }

  function close(refocus = true) {
    if (!open) return;
    open = false;
    if (refocus && opener && opener.isConnected && typeof opener.focus === "function") opener.focus();
    opener = null;
  }

  function run(cmd) {
    if (!cmd) return;
    close();
    if (cmd.confirm) confirming = cmd;
    else postEvent(node.id, "run", { command: cmd.id });
  }

  function token(e) {
    const key = e.key === " " ? "space" : e.key.toLowerCase();
    const shift = e.shiftKey && (key.length > 1 || /[a-z]/.test(key));
    return [(e.ctrlKey || e.metaKey) && "mod", e.altKey && "alt", shift && "shift", key]
      .filter(Boolean)
      .join("+");
  }

  function typing(e) {
    const t = e.target;
    return !!t && (["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName) || t.isContentEditable);
  }

  function onwindowkey(e) {
    if (["shift", "control", "alt", "meta"].includes(e.key.toLowerCase())) return;
    if (token(e) !== (props.shortcut ?? "mod+k")) return;
    if (open) {
      e.preventDefault();
      close();
      return;
    }
    if (e.defaultPrevented || document.querySelector('[role="dialog"]')) return;
    const tok = token(e);
    const combo = tok.startsWith("mod+") || tok.startsWith("alt+");
    if (typing(e) && !combo) return;
    e.preventDefault();
    show();
  }

  function onkey(e) {
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      close();
    } else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (results.length) {
        active = (active + (e.key === "ArrowDown" ? 1 : -1) + results.length) % results.length;
        tick().then(() => list?.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: "nearest" }));
      }
    } else if (e.key === "Enter") {
      e.preventDefault();
      run(results[active]?.c);
    } else if (e.key === "Tab") {
      // A modal dialog keeps Tab inside; Escape is the way out (WCAG 2.1.2).
      e.preventDefault();
    }
  }
</script>

<svelte:window onkeydown={onwindowkey} />

{#if open}
  <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
  <div class="cp-backdrop" onclick={(e) => { if (e.target === e.currentTarget) close(); }}>
    <div class="cp-panel" role="dialog" aria-modal="true" aria-label={props.label || "Command palette"}>
      <input
        bind:this={input}
        bind:value={query}
        class="cp-input"
        type="text"
        role="combobox"
        aria-expanded="true"
        aria-controls="{uid}-list"
        aria-autocomplete="list"
        aria-activedescendant={results.length ? `${uid}-opt-${active}` : undefined}
        aria-label={props.placeholder || "Type a command"}
        placeholder={props.placeholder || "Type a command..."}
        autocomplete="off"
        spellcheck="false"
        onkeydown={onkey}
      />
      <ul bind:this={list} id="{uid}-list" class="cp-list" role="listbox" aria-label="Commands">
        {#each results as r, i (r.c.id)}
          {#if !query.trim() && r.c.group && (i === 0 || results[i - 1].c.group !== r.c.group)}
            <li class="cp-group" role="presentation">{r.c.group}</li>
          {/if}
          <!-- svelte-ignore a11y_click_events_have_key_events -->
          <li
            id="{uid}-opt-{i}"
            class="cp-option"
            class:active={i === active}
            role="option"
            aria-selected={i === active}
            onpointermove={() => (active = i)}
            onclick={() => run(r.c)}
          >
            <span class="cp-label">{r.c.label}</span>
            {#if query.trim() && r.c.group}<span class="cp-meta">{r.c.group}</span>{/if}
            {#if r.c.shortcut}<span class="cp-shortcut" aria-hidden="true">{r.c.shortcut}</span>{/if}
          </li>
        {/each}
      </ul>
      {#if !results.length}<div class="cp-empty">No matching commands</div>{/if}
      <div class="sr-only" role="status" aria-live="polite">
        {results.length ? `${results.length} ${results.length === 1 ? "command" : "commands"}` : "No matching commands"}
      </div>
    </div>
  </div>
{/if}

{#if confirming}
  <Overlay kind="modal" size="sm" title={confirming.confirm} onclose={() => (confirming = null)} initialFocus=".confirm-no">
    <div class="confirm-actions">
      <button type="button" class="ghost confirm-no" onclick={() => (confirming = null)}>Cancel</button>
      <button
        type="button"
        class="confirm-yes"
        onclick={() => {
          const cmd = confirming;
          confirming = null;
          postEvent(node.id, "run", { command: cmd.id });
        }}>{confirming.label}</button
      >
    </div>
  </Overlay>
{/if}

<style>
  .cp-backdrop {
    position: fixed;
    inset: 0;
    z-index: 55;
    display: flex;
    align-items: flex-start;
    justify-content: center;
    padding-top: 12vh;
    background: color-mix(in srgb, #000 45%, transparent);
  }
  .cp-panel {
    width: min(36rem, 92vw);
    max-height: 70vh;
    display: flex;
    flex-direction: column;
    background: var(--surface);
    color: var(--text);
    border: 1px solid var(--outline);
    border-radius: var(--radius);
    box-shadow: var(--shadow);
    overflow: hidden;
  }
  .cp-input {
    width: 100%;
    box-sizing: border-box;
    padding: 0.85rem 1rem;
    font: inherit;
    color: var(--text);
    background: transparent;
    border: 0;
    border-bottom: 1px solid var(--outline-soft);
    border-radius: 0;
    outline: none;
  }
  .cp-input:focus-visible { box-shadow: inset 0 -2px 0 var(--primary); }
  .cp-list { list-style: none; margin: 0; padding: 0.3rem; overflow: auto; }
  .cp-group {
    padding: 0.5rem 0.7rem 0.2rem;
    font-size: 0.75rem;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }
  .cp-option {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 0.5rem 0.7rem;
    border-radius: var(--radius-sm);
    cursor: pointer;
  }
  .cp-option.active { background: var(--surface-2); box-shadow: inset 2px 0 0 var(--primary); }
  .cp-label { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .cp-meta { font-size: 0.8rem; color: var(--muted); }
  .cp-shortcut { font-family: var(--font-mono); font-size: 0.78rem; color: var(--muted); }
  .cp-empty { padding: 1rem; color: var(--muted); text-align: center; }
  .sr-only {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip-path: inset(50%);
    white-space: nowrap;
  }
</style>
