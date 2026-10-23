<script>
  // Text with shaded spans (IND-157). `runs` come from the server (indah.marked_runs): each is
  // [text], [text, tone] or [text, tone, label], and the texts joined are the plain text. The
  // spans are real <mark> elements and add no characters, so selecting and copying gives back
  // exactly the plain text. A tone is shown by its underline as well as its colour.
  let { runs = [], label = "" } = $props();
</script>

<span class="marked" role={label ? "group" : undefined} aria-label={label || undefined}>{#each runs as run}{#if run[1]}<mark class={`mk tone-${run[1]}`} title={run[2] || undefined}>{run[0]}</mark>{:else}{run[0]}{/if}{/each}</span>
