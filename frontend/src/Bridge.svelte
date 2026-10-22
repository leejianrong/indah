<script module>
  // A component backed by an ES module the app serves itself (ADR-0039). One import per
  // module URL per page; the shell, not the module, picks the custom-element name.
  import { apiUrl } from "./api.js";

  const loaded = new Map(); // module url -> Promise of the element class

  function load(mod) {
    let p = loaded.get(mod.url);
    if (!p) {
      p = import(/* @vite-ignore */ apiUrl(mod.url)).then((m) => {
        if (typeof m.default !== "function") {
          throw new Error(`${mod.tag}: the module has no default export class`);
        }
        if (!customElements.get(mod.tag)) customElements.define(mod.tag, m.default);
        return customElements.get(mod.tag);
      });
      loaded.set(mod.url, p);
    }
    return p;
  }

  // An exception inside a module's own callbacks (connectedCallback, ...) is reported on
  // window, not thrown to us. Route those that come from a module's file to its nodes.
  const watchers = new Map(); // absolute module url without the query -> Set of callbacks
  if (typeof window !== "undefined") {
    window.addEventListener("error", (e) => {
      if (!e.filename) return;
      for (const [url, set] of watchers) {
        if (e.filename.startsWith(url)) for (const fn of [...set]) fn(e.error || e.message);
      }
    });
  }

  function same(a, b) {
    return a === b || (a && b && typeof a === "object" && JSON.stringify(a) === JSON.stringify(b));
  }
</script>

<script>
  import { onMount } from "svelte";
  import { postEvent } from "./api.js";

  let { module: mod, props, nodeId } = $props();

  let host = $state();
  let failed = $state(false);
  let el = null;
  let latest = {};
  let applied = {};
  let frame = 0;
  const twoWay = new Set(mod.twoWay || []);

  // Prop values as plain data (a deep read, so an in-place patch of an array is seen).
  function snapshot() {
    const out = {};
    for (const k of Object.keys(props)) {
      if (k.startsWith("_") || k === "tooltip") continue;
      out[k] = $state.snapshot(props[k]);
    }
    return out;
  }

  function fail(err) {
    if (failed) return;
    failed = true;
    console.error(`indah: component ${mod.tag} failed:`, err);
  }

  // Set the changed props as element properties. A two-way prop the viewer is editing
  // (focus inside the element) is left alone and applied after blur (ADR-0013).
  function apply() {
    frame = 0;
    if (!el) return;
    const editing = el.matches(":focus-within");
    for (const [k, v] of Object.entries(latest)) {
      if (editing && twoWay.has(k)) continue;
      if (same(applied[k], v)) continue;
      try {
        el[k] = v;
      } catch (e) {
        fail(e);
        return;
      }
      applied[k] = v;
    }
  }

  // At most one pass per frame, so a burst of patches costs one set per property.
  function schedule() {
    if (!frame) frame = requestAnimationFrame(apply);
  }

  $effect(() => {
    latest = snapshot();
    if (el) schedule();
  });

  const fallbackText = $derived.by(() => {
    const v = mod.fallback ? props[mod.fallback] : null;
    if (v === null || v === undefined) return "";
    return typeof v === "object" ? JSON.stringify($state.snapshot(v)) : String(v);
  });

  onMount(() => {
    let dead = false;
    const moduleUrl = apiUrl(mod.url).split("?")[0];
    if (!watchers.has(moduleUrl)) watchers.set(moduleUrl, new Set());
    watchers.get(moduleUrl).add(fail);
    const cleanups = [];

    load(mod)
      .then((Cls) => {
        if (dead) return;
        const node = document.createElement(mod.tag);
        if (!(node instanceof Cls)) throw new Error(`${mod.tag}: the element could not be created`);
        node.cspNonce = document.querySelector("script[nonce]")?.nonce || "";
        el = node;
        latest = snapshot();
        apply(); // before it is attached, so connectedCallback sees the initial state
        for (const name of mod.events || []) {
          const fn = (e) => {
            let detail = null;
            try {
              detail = JSON.parse(JSON.stringify(e.detail ?? null));
            } catch (_) {
              return; // not JSON data: it cannot cross to the server
            }
            postEvent(nodeId, name, { detail });
          };
          node.addEventListener(name, fn);
          cleanups.push(() => node.removeEventListener(name, fn));
        }
        node.addEventListener("focusout", schedule);
        cleanups.push(() => node.removeEventListener("focusout", schedule));
        host.appendChild(node);
      })
      .catch(fail);

    return () => {
      dead = true;
      if (frame) cancelAnimationFrame(frame);
      watchers.get(moduleUrl)?.delete(fail);
      for (const c of cleanups) c();
      el?.remove();
      el = null;
    };
  });
</script>

{#if failed}
  <span class="bridge-fallback">{fallbackText}</span>
{:else}
  <div class="bridge" bind:this={host}></div>
{/if}

<style>
  .bridge {
    display: block;
    min-width: 0;
  }
</style>
