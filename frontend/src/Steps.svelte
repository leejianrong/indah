<script>
  // Steps (IND-163): a timeline of steps, vertical or horizontal. Display only, so it is not a tab
  // stop. A state is never colour alone: each has its own drawing (a check, a ring with a dot, a
  // barred ring, a dashed ring, an empty ring), a skipped label is struck through, and every step
  // is spoken as "<label>, step 2 of 5, done" (with its detail). The current step is aria-current.
  // Items are [label, state, detail] from the server (indah.steps_items); a patch moves the
  // existing <li> elements (unkeyed each), it does not remount them.
  let { items = [], orientation = "vertical", size = "normal", label = "" } = $props();

  const KNOWN = ["done", "current", "skipped", "off", "pending"];
  const stateOf = (s) => (KNOWN.includes(s) ? s : "pending");
  const compact = $derived(size === "compact");
</script>

<ol
  class={`steps ${orientation === "horizontal" ? "steps-h" : "steps-v"}`}
  class:steps-compact={compact}
  aria-label={label || undefined}
>
  {#each items as item, i}
    {@const state = stateOf(item[1])}
    {@const detail = item[2] || ""}
    <li
      class={`step st-${state}`}
      aria-current={state === "current" ? "step" : undefined}
      title={compact && detail ? detail : undefined}
    >
      <svg class="step-glyph" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
        {#if state === "done"}
          <circle class="g-fill" cx="8" cy="8" r="7" />
          <path class="g-mark" d="M4.6 8.4l2.3 2.3 4.5-4.9" />
        {:else if state === "current"}
          <circle class="g-ring" cx="8" cy="8" r="6.2" />
          <circle class="g-fill" cx="8" cy="8" r="2.8" />
        {:else if state === "skipped"}
          <circle class="g-ring" cx="8" cy="8" r="6.2" />
          <path class="g-bar" d="M4.8 8h6.4" />
        {:else if state === "off"}
          <circle class="g-ring g-dash" cx="8" cy="8" r="6.2" />
        {:else}
          <circle class="g-ring" cx="8" cy="8" r="6.2" />
        {/if}
      </svg>
      <span class="step-body">
        <span class="step-label">{item[0]}</span>
        {#if detail && !compact}<span class="step-detail">{detail}</span>{/if}
        <span class="sr-only">, step {i + 1} of {items.length}, {state}{detail ? `. ${detail}` : ""}</span>
      </span>
    </li>
  {/each}
</ol>
