<script>
  // TickStrip (IND-263): one small tick per run. Colour is not the only signal: a failed tick is
  // taller and a warning is half-height lower, and the label reads the counts aloud.
  let { states = [], label = "" } = $props();
  const count = (s) => states.filter((x) => x === s).length;
  const aria = $derived(
    `${label || "Recent runs"}: ${count("ok")} ok, ${count("warn")} warning, ${count("err")} failed${
      count("neutral") ? `, ${count("neutral")} unknown` : ""
    }`,
  );
</script>

<span class="ticks" role="img" aria-label={aria}>
  {#each states as s}<span class={`tick tick-${s}`}></span>{/each}
</span>
