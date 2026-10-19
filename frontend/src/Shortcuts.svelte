<script>
  // An invisible shortcut map (ADR-0030). Active while mounted, so a map inside a tab
  // is scoped to it. Bare keys and sequences are ignored while typing or under a
  // dialog; mod+/alt+ combos fire anywhere outside a dialog.
  import { postEvent } from "./api.js";
  import { shortcutRegistry, helpOpen } from "./stores.js";

  let { node, props } = $props();

  const SEQUENCE_MS = 1000;
  let buffer = [];
  let timer = null;

  $effect(() => {
    const entries = props.keys ?? [];
    shortcutRegistry.update((m) => new Map(m).set(node.id, entries));
    return () =>
      shortcutRegistry.update((m) => {
        const next = new Map(m);
        next.delete(node.id);
        return next;
      });
  });

  function token(e) {
    let key = e.key === " " ? "space" : e.key.toLowerCase();
    const mod = e.ctrlKey || e.metaKey;
    const shift = e.shiftKey && (key.length > 1 || /[a-z]/.test(key));
    return [mod && "mod", e.altKey && "alt", shift && "shift", key].filter(Boolean).join("+");
  }

  function typing(e, tok) {
    const t = e.target;
    if (!t) return false;
    if (["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName) || t.isContentEditable) return true;
    // Enter/Space activate a focused button or link: that is the control's key, not ours.
    return (tok === "enter" || tok === "space") && !!t.closest?.("button, a[href], summary, [role=switch]");
  }

  function reset() {
    buffer = [];
    clearTimeout(timer);
    timer = null;
  }

  function onkeydown(e) {
    if (["shift", "control", "alt", "meta"].includes(e.key.toLowerCase())) return;
    if (e.defaultPrevented || document.querySelector('[role="dialog"]')) return;
    const tok = token(e);
    const combo = tok.startsWith("mod+") || tok.startsWith("alt+");
    if (typing(e, tok) && !combo) return;

    const keys = (props.keys ?? []).map((k) => k.keys);
    let candidate = [...buffer, tok];
    for (let attempt = 0; attempt < 2; attempt++) {
      const joined = candidate.join(" ");
      if (keys.includes(joined)) {
        e.preventDefault();
        reset();
        postEvent(node.id, "press", { keys: joined });
        return;
      }
      if (keys.some((k) => k.startsWith(joined + " "))) {
        e.preventDefault();
        buffer = candidate;
        clearTimeout(timer);
        timer = setTimeout(reset, SEQUENCE_MS);
        return;
      }
      if (buffer.length === 0) break;
      reset();
      candidate = [tok]; // a broken sequence: retry this key as a fresh start
    }
    if (tok === "?") {
      e.preventDefault();
      helpOpen.set(true);
    }
  }
</script>

<svelte:window {onkeydown} />
