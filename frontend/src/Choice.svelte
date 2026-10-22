<script>
  // Chips and Segmented (IND-144): a row of options bound to one value (or, for multi chips, a
  // list). A single choice is a radio group with a roving tabindex: arrows move and select, as a
  // native radio group does. Multi chips are toggle buttons: arrows only move focus, Space or
  // Enter toggles. The server value is read straight from the props, so a late echo cannot fight
  // the click (the click posts, the patch confirms).
  import { postEvent } from "./api.js";

  let { node, props } = $props();

  let multi = $derived(node.type === "chips" && !!props.multi);
  let segmented = $derived(node.type === "segmented");
  let options = $derived(props.options ?? []);
  let chosen = $derived(multi ? (props.value ?? []) : [props.value]);
  // The tab stop of a single choice: the selected option, else the first.
  let stop = $derived(
    options.some((o) => o.value === props.value) ? props.value : options[0]?.value,
  );
  let group = $state();

  function isOn(o) {
    return chosen.includes(o.value);
  }

  function choose(o) {
    if (multi) {
      const next = options.map((x) => x.value).filter((v) => (v === o.value ? !isOn(o) : chosen.includes(v)));
      postEvent(node.id, "change", { value: next });
    } else if (props.value !== o.value) {
      postEvent(node.id, "change", { value: o.value });
    }
  }

  function onkey(e, i) {
    const last = options.length - 1;
    let to = null;
    if (e.key === "ArrowRight" || e.key === "ArrowDown") to = i === last ? 0 : i + 1;
    else if (e.key === "ArrowLeft" || e.key === "ArrowUp") to = i === 0 ? last : i - 1;
    else if (e.key === "Home") to = 0;
    else if (e.key === "End") to = last;
    if (to === null) return;
    e.preventDefault();
    group.querySelectorAll("button")[to]?.focus();
    if (!multi) choose(options[to]);
  }
</script>

<div class="field">
  {#if props.label}<span class="stream-label">{props.label}</span>{/if}
  <div
    class="choice {segmented ? 'segmented' : 'chips'}"
    role={multi ? "group" : "radiogroup"}
    aria-label={props.label || undefined}
    bind:this={group}
  >
    {#each options as o, i (o.value)}
      <button
        type="button"
        class="choice-opt tone-{o.tone ?? 'default'}"
        class:on={isOn(o)}
        role={multi ? undefined : "radio"}
        aria-checked={multi ? undefined : isOn(o)}
        aria-pressed={multi ? isOn(o) : undefined}
        tabindex={multi || o.value === stop ? 0 : -1}
        onclick={() => choose(o)}
        onkeydown={(e) => onkey(e, i)}
      >
        <span>{o.label}</span>
        {#if o.count != null}<span class="choice-count">{o.count}</span>{/if}
      </button>
    {/each}
  </div>
</div>
