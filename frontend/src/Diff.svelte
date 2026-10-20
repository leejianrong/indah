<script>
  // Read-only diff (IND-109). The server computes the rows (ADR-0028); this only draws them,
  // side by side or unified, with the changed characters of a changed line marked.
  let { props } = $props();

  const d = $derived(props.diff ?? { rows: [], stats: { add: 0, del: 0, chg: 0 }, same: true });
  const labels = $derived(props.labels ?? ["incoming", "candidate"]);
  let mode = $state(null);
  const current = $derived(mode ?? props.mode ?? "split");

  const CHUNK = 500;
  let shown = $state(CHUNK);

  // Split text into [{text, hl}] runs from a list of [start, end) spans.
  function segments(text, spans) {
    if (!spans || spans.length === 0) return [{ text, hl: false }];
    const out = [];
    let at = 0;
    for (const [s, e] of spans) {
      if (s > at) out.push({ text: text.slice(at, s), hl: false });
      out.push({ text: text.slice(s, e), hl: true });
      at = e;
    }
    if (at < text.length) out.push({ text: text.slice(at), hl: false });
    return out;
  }

  // Unified mode shows a changed line as a removal followed by an addition.
  const unified = $derived.by(() => {
    if (current !== "unified") return [];
    const out = [];
    for (const r of d.rows.slice(0, shown)) {
      if (r.t === "chg") {
        out.push({ t: "del", a: r.a, text: r.at, spans: r.ai });
        out.push({ t: "add", b: r.b, text: r.bt, spans: r.bi });
      } else {
        out.push(r);
      }
    }
    return out;
  });
  const sign = { eq: " ", del: "−", add: "+", chg: "~" };
</script>

<div class="field diffview">
  <div class="diff-head">
    <span class="diff-label del">{labels[0]}</span>
    <span class="diff-label add">{labels[1]}</span>
    <span class="diff-stats" aria-label="Changes"
      >+{d.stats.add} −{d.stats.del} ~{d.stats.chg}</span
    >
    <span class="diff-mode" role="group" aria-label="Diff layout">
      <button type="button" class="ghost" aria-pressed={current === "split"} onclick={() => (mode = "split")}>Split</button>
      <button type="button" class="ghost" aria-pressed={current === "unified"} onclick={() => (mode = "unified")}>Unified</button>
    </span>
  </div>
  {#if d.truncated}
    <div class="diff-note" role="status">Only the first 5,000 lines of each side were compared.</div>
  {/if}
  {#if d.approximate}
    <div class="diff-note" role="status">Very large input: this diff is approximate.</div>
  {/if}
  {#if d.same}
    <div class="diff-same">No differences.</div>
  {:else}
    <div class="diff-scroll">
      <table class="diff {current}" aria-label="Differences between {labels[0]} and {labels[1]}">
        <tbody>
          {#if current === "split"}
            {#each d.rows.slice(0, shown) as r}
              {#if r.t === "skip"}
                <tr class="skip"><td colspan="6">⋯ {r.n} unchanged lines</td></tr>
              {:else}
                <tr class={r.t}>
                  <td class="ln">{r.a ?? ""}</td>
                  <td class="gut" aria-hidden="true">{r.t === "del" || r.t === "chg" ? "−" : ""}</td>
                  <td class="code a">
                    {#if r.t === "chg"}{#each segments(r.at, r.ai) as seg}{#if seg.hl}<mark>{seg.text}</mark>{:else}{seg.text}{/if}{/each}{:else if r.t !== "add"}{r.text}{/if}
                  </td>
                  <td class="ln">{r.b ?? ""}</td>
                  <td class="gut" aria-hidden="true">{r.t === "add" || r.t === "chg" ? "+" : ""}</td>
                  <td class="code b">
                    {#if r.t === "chg"}{#each segments(r.bt, r.bi) as seg}{#if seg.hl}<mark>{seg.text}</mark>{:else}{seg.text}{/if}{/each}{:else if r.t !== "del"}{r.text}{/if}
                  </td>
                </tr>
              {/if}
            {/each}
          {:else}
            {#each unified as r}
              {#if r.t === "skip"}
                <tr class="skip"><td colspan="4">⋯ {r.n} unchanged lines</td></tr>
              {:else}
                <tr class={r.t}>
                  <td class="ln">{r.a ?? ""}</td>
                  <td class="ln">{r.b ?? ""}</td>
                  <td class="gut" aria-hidden="true">{sign[r.t]}</td>
                  <td class="code">
                    {#if r.spans}{#each segments(r.text, r.spans) as seg}{#if seg.hl}<mark>{seg.text}</mark>{:else}{seg.text}{/if}{/each}{:else}{r.text}{/if}
                  </td>
                </tr>
              {/if}
            {/each}
          {/if}
        </tbody>
      </table>
    </div>
    {#if d.rows.length > shown}
      <button type="button" class="ghost diff-more" onclick={() => (shown += 2 * CHUNK)}
        >Show more ({d.rows.length - shown} rows left)</button
      >
    {/if}
  {/if}
</div>

<style>
  .diff-head { display: flex; gap: 0.8rem; align-items: center; margin-bottom: 0.4rem; flex-wrap: wrap; }
  .diff-label { font-size: 0.78rem; font-weight: 600; padding: 0.05rem 0.6rem; border-radius: var(--radius-pill); }
  .diff-label.del { background: color-mix(in srgb, var(--err) 16%, var(--surface)); color: var(--err); }
  .diff-label.add { background: color-mix(in srgb, var(--ok) 16%, var(--surface)); color: var(--ok); }
  .diff-stats { font-family: var(--font-mono); font-size: 0.8rem; color: var(--muted); }
  .diff-mode { margin-left: auto; display: inline-flex; gap: 0.2rem; }
  .diff-mode button { padding: 0.15rem 0.8rem; font-size: 0.78rem; align-self: auto; }
  .diff-mode button[aria-pressed="true"] { background: var(--primary-container); color: var(--text); }
  .diff-note { font-size: 0.8rem; color: var(--warn); margin-bottom: 0.3rem; }
  .diff-same { color: var(--muted); font-size: 0.9rem; }
  .diff-scroll { max-height: 32rem; overflow: auto; border: 1px solid var(--outline-soft); border-radius: var(--radius-sm); background: var(--surface); }
  table.diff { border-collapse: collapse; width: 100%; font-family: var(--font-mono); font-size: 0.8rem; table-layout: fixed; }
  table.diff.split td.code { width: 50%; }
  td.ln { width: 3.2rem; text-align: right; color: var(--muted); padding: 0 0.4rem; user-select: none; vertical-align: top; }
  td.gut { width: 1.1rem; text-align: center; color: var(--muted); user-select: none; vertical-align: top; }
  td.code { white-space: pre-wrap; word-break: break-all; padding: 0 0.4rem; vertical-align: top; }
  tr.del td.code.a, tr.chg td.code.a, tr.del td.code:not(.b):not(.a) { background: color-mix(in srgb, var(--err) 13%, transparent); }
  tr.add td.code.b, tr.chg td.code.b, tr.add td.code:not(.a):not(.b) { background: color-mix(in srgb, var(--ok) 13%, transparent); }
  tr.del td.ln, tr.del td.gut { background: color-mix(in srgb, var(--err) 13%, transparent); }
  tr.add td.ln, tr.add td.gut { background: color-mix(in srgb, var(--ok) 13%, transparent); }
  mark { color: inherit; background: color-mix(in srgb, var(--warn) 38%, transparent); border-radius: 2px; }
  tr.skip td { text-align: center; color: var(--muted); background: var(--surface-2); padding: 0.1rem; font-style: italic; }
  .diff-more { margin-top: 0.4rem; font-size: 0.8rem; padding: 0.2rem 0.8rem; }
</style>
