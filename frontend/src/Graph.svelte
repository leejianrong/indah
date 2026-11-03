<script>
  // Interactive node-link graph (ADR-0048). The renderer is a separate same-origin module
  // (frontend/graph/graph.js, built to src/indah/static/graph.js and served at api/graph.js),
  // fetched the first time a graph renders so an app without a graph never downloads it
  // (ADR-0042). A devDependency-free, hand-rolled canvas: no Node at install or runtime.
  import { untrack } from "svelte";
  import { apiUrl } from "./api.js";

  let { props } = $props();
  let el = $state();
  let mod = $state.raw(null); // the lazily loaded module, once it has arrived
  let failed = $state(false);
  let ctl = null; // the mounted graph controller
  let legend = $state.raw([]);

  // The URL carries the module's content hash, so a new release is fetched at once and an old
  // one is cached for good.
  $effect(() => {
    if (mod || failed) return;
    import(/* @vite-ignore */ apiUrl(`api/graph.js?v=${__GRAPH_HASH__}`)).then(
      (m) => (mod = m),
      () => (failed = true),
    );
  });

  function load() {
    if (!ctl || !props.nodes) return;
    ctl.setData({ nodes: props.nodes, edges: props.edges });
    options();
    ctl.resize();
    legend = ctl.legend();
  }

  function options() {
    if (ctl) ctl.setOptions({ focusSize: props.focusSize ?? 300, highlight: props.highlight ?? null });
  }

  function destroy() {
    if (ctl) {
      ctl.destroy();
      ctl = null;
    }
  }

  // Mount once the module and the element exist; a new graph (nodes or edges changed) is handed to
  // the existing controller, so the viewer's own pan and zoom are not reset by unrelated updates.
  $effect(() => {
    void el;
    void mod;
    untrack(() => {
      destroy();
      if (!el || !mod) return;
      ctl = mod.createGraph(el);
      load();
    });
    return destroy;
  });

  $effect(() => {
    void props.nodes;
    void props.edges;
    void props.layout;
    untrack(load);
  });

  // The focus size and the highlight change without resending the graph.
  $effect(() => {
    void props.focusSize;
    void props.highlight;
    untrack(options);
  });

  $effect(() => {
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => ctl && ctl.resize());
    ro.observe(el);
    return () => ro.disconnect();
  });
</script>

<div class="graph" class:fill={props.height === "fill"}>
  <div
    class="graph-stage"
    style:height={props.height === "fill" ? undefined : `${props.height ?? 480}px`}
    role="img"
    aria-label={props.label || "Graph"}
    bind:this={el}
  ></div>
  {#if props.legend !== false && legend.length}
    <ul class="graph-legend">
      {#each legend as item (item.group)}
        <li><span class="graph-swatch" style:background={item.color}></span>{item.group}</li>
      {/each}
    </ul>
  {/if}
  {#if failed}<span class="graph-empty">The graph view could not load.</span>{/if}
</div>
