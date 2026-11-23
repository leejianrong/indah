<script>
  // Interactive node-link graph (ADR-0048). The renderer is a separate same-origin module
  // (frontend/graph/graph.js, built to src/indah/static/graph.js and served at api/graph.js),
  // fetched the first time a graph renders so an app without a graph never downloads it
  // (ADR-0042). A devDependency-free, hand-rolled canvas: no Node at install or runtime.
  import { untrack } from "svelte";
  import { apiUrl, postEvent } from "./api.js";
  import { frameLinks } from "./stores.js";

  let { props, nodeId } = $props();
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

  // Hand the graph to the controller, but only when the data itself is new: a change to another
  // prop (the highlight, the selection) must not restart the layout or reset the viewer's pan.
  let loadedNodes;
  let loadedEdges;
  function load(force = false) {
    if (!ctl || !props.nodes) return;
    if (!force && props.nodes === loadedNodes && props.edges === loadedEdges) return;
    loadedNodes = props.nodes;
    loadedEdges = props.edges;
    ctl.setData({ nodes: props.nodes, edges: props.edges, layout: props.layout, update: props.update, transitionMs: props.transitionMs });
    options();
    ctl.resize();
    legend = ctl.legend();
  }

  function options() {
    if (!ctl) return;
    ctl.setOptions({
      focusSize: props.focusSize ?? 300,
      highlight: props.highlight ?? null,
      selected: props.selectable ? (props.selected ?? null) : undefined,
      focus: props.focus ?? null,
    });
  }

  // Hover (IND-249): posted only when the id changed since the last post and has settled for
  // HOVER_MS (a trailing debounce), so a sweep over many nodes is one event. It shares the
  // /api/event rate bucket with clicks, so nothing is ever sent when no `hovered` signal is bound;
  // postEvent drops a failed or rate-limited (429) post without a message.
  const HOVER_MS = 250;
  let hoverTimer = 0;
  let hoverWant = null;
  let hoverSent = null;
  function onHover(id) {
    hoverWant = id;
    clearTimeout(hoverTimer);
    hoverTimer = setTimeout(() => {
      hoverTimer = 0;
      if (!props.hoverable || hoverWant === hoverSent) return;
      hoverSent = hoverWant;
      postEvent(nodeId, "hover", { id: hoverWant });
    }, HOVER_MS);
  }

  function destroy() {
    clearTimeout(hoverTimer);
    hoverTimer = 0;
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
      ctl = mod.createGraph(el, {
        // The viewer's own click: tell Python (only when a `selected` signal is bound).
        onSelect: (id) => props.selectable && postEvent(nodeId, "select", { id }),
        onHover: props.hoverable ? onHover : undefined,
      });
      load(true);
      frames();
      // A linked Timeline sets frames here; the index goes to Python only when `report` is set
      // (a pause, the end, a manual step) and a `frame` signal is bound.
      const link = {
        set: (i, report) => {
          ctl?.setFrame(i);
          if (report && props.frame !== undefined && i !== props.frame) postEvent(nodeId, "frame", { index: i });
        },
      };
      frameLinks.update((m) => new Map(m).set(nodeId, link));
    });
    return () => {
      frameLinks.update((m) => (m.delete(nodeId), new Map(m)));
      destroy();
    };
  });

  $effect(() => {
    void props.nodes;
    void props.edges;
    void props.layout;
    untrack(load);
  });

  function frames() {
    if (ctl && props.frames) ctl.setFrames(props.frames, props.frame ?? 0);
  }
  $effect(() => {
    void props.frames;
    void props.frame;
    untrack(frames);
  });

  // The focus size and the highlight change without resending the graph.
  $effect(() => {
    void props.focusSize;
    void props.highlight;
    void props.selected;
    void props.focus;
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
    role="group"
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
