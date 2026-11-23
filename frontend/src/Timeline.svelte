<script>
  // Timeline (IND-277, ADR-0053): step through an ordered list of moments (any number, any spacing).
  // The track is a native range input over the point index, so arrow keys, Home and End and
  // assistive technology work for free; density draws as small bars behind it. Play is a browser
  // timer that posts one `input` per step (at most 4 a second, so the shared event bucket survives).
  import { postEvent } from "./api.js";
  import { frameLinks } from "./stores.js";

  let { id, props } = $props();

  const labels = $derived(props.labels ?? []);
  const n = $derived(labels.length);
  const density = $derived(props.density ?? []);
  const unit = $derived(props.unit ?? "");
  const off = $derived(!!props.disabled);
  const STEPS = [0.5, 1, 2, 4]; // steps a second: the cap of 4 is the rate limit's, not a taste

  let cur = $state(0); // the point on show; follows the server, and runs ahead while playing
  let playing = $state(false);
  let speed = $state(1);

  // `props` is a new object on every patch, so each effect remembers what the server last said and
  // acts only on a change; while playing the browser is ahead of the server's echo, so it ignores it.
  let seenIndex, seenPlaying, seenSpeed;
  $effect(() => {
    const i = Math.min(Math.max(props.index ?? 0, 0), Math.max(n - 1, 0));
    if (i !== seenIndex) {
      seenIndex = i;
      if (!playing) cur = i;
    }
  });
  $effect(() => {
    const p = !!props.playing;
    if (p !== seenPlaying) {
      seenPlaying = p;
      playing = p && !off;
    }
  });
  $effect(() => {
    const s = STEPS.includes(props.speed) ? props.speed : 1;
    if (s !== seenSpeed) {
      seenSpeed = s;
      speed = s;
    }
  });

  const isEvent = (i) => (density[i] ?? 0) > 0;
  const peak = $derived(Math.max(1, ...density));

  // With `link` (a Graph id) the timeline steps that graph's frames here in the browser: while
  // playing nothing is posted, and the index goes to Python once on a manual step, a pause or the end.
  const link = $derived($frameLinks.get(props.link));
  $effect(() => link?.set(cur, false)); // a graph that mounts later, or a change from the server
  function show(next) {
    cur = next;
    link?.set(next, false);
  }
  function commit() {
    postEvent(id, "input", { index: cur });
    link?.set(cur, true);
  }
  function go(i) {
    if (off || n === 0) return;
    const next = Math.min(Math.max(i, 0), n - 1);
    if (next === cur) return;
    show(next);
    commit();
  }
  function jumpEvent(dir) {
    for (let i = cur + dir; i >= 0 && i < n; i += dir) {
      if (isEvent(i)) return go(i);
    }
  }
  function setPlaying(on) {
    if (off || n === 0) return;
    if (on && cur >= n - 1) go(0); // play from the end starts again from the start
    playing = on;
    postEvent(id, "play", { playing: on });
    if (!on && link) commit();
  }

  $effect(() => {
    if (!playing) return;
    const timer = setInterval(() => {
      if (cur >= n - 1) return setPlaying(false);
      if (link) show(cur + 1);
      else go(cur + 1);
      if (cur >= n - 1) setPlaying(false);
    }, 1000 / speed);
    return () => clearInterval(timer);
  });

  function onKey(e) {
    if (e.key === " ") {
      e.preventDefault();
      setPlaying(!playing);
    }
  }

  // A bar's height is set through the CSSOM, so no style attribute is needed under the strict CSP.
  function bar(el, h) {
    const set = (v) => (el.style.height = `${Math.round(v * 100)}%`);
    set(h);
    return { update: set };
  }
</script>

<div class="timeline" class:disabled={off} role="group" aria-label={props.label || "Timeline"}>
  <div class="timeline-top">
    <output class="timeline-now" for={`${id}-range`}>{labels[cur] ?? ""}</output>
    <span class="timeline-count">{n ? `${cur + 1} of ${n}` : ""}</span>
  </div>
  <div class="timeline-track">
    {#if density.length}
      <div class="timeline-density" aria-hidden="true">
        {#each density as d, i}
          <span class="timeline-bar" class:on={i === cur} use:bar={(d ?? 0) / peak}></span>
        {/each}
      </div>
    {/if}
    <input
      id={`${id}-range`}
      type="range"
      min="0"
      max={Math.max(n - 1, 0)}
      step="1"
      value={cur}
      disabled={off || null}
      aria-valuetext={n ? `${unit ? unit + " " : ""}${labels[cur]}, step ${cur + 1} of ${n}` : ""}
      oninput={(e) => go(Number(e.currentTarget.value))}
      onkeydown={onKey}
    />
  </div>
  <div class="timeline-controls">
    <button type="button" aria-label="Previous event" disabled={off || null} onclick={() => jumpEvent(-1)}>&#x23EE;</button>
    <button type="button" aria-label="Previous" disabled={off || null} onclick={() => go(cur - 1)}>&#x25C2;</button>
    <button
      type="button"
      class="timeline-play"
      aria-label={playing ? "Pause" : "Play"}
      aria-pressed={playing}
      disabled={off || null}
      onclick={() => setPlaying(!playing)}>{playing ? "⏸" : "▶"}</button
    >
    <button type="button" aria-label="Next" disabled={off || null} onclick={() => go(cur + 1)}>&#x25B8;</button>
    <button type="button" aria-label="Next event" disabled={off || null} onclick={() => jumpEvent(1)}>&#x23ED;</button>
    <label class="timeline-speed"
      ><span class="sr-only">Speed</span>
      <select value={speed} disabled={off || null} onchange={(e) => (speed = Number(e.currentTarget.value))}>
        {#each STEPS as s}<option value={s}>{s}x</option>{/each}
      </select></label
    >
  </div>
</div>
