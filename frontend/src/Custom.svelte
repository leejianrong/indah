<script>
  // Generic renderer for a registered custom component (ADR-0012). It interprets a
  // declarative render spec that arrived on the wire as the `_spec` prop, so a new
  // component type renders with no shell rebuild and no runtime Node.
  import { postEvent } from "./api.js";
  import Self from "./Custom.svelte";

  let { spec, props, nodeId } = $props();

  // Static attrs + static class + props bound onto element attributes.
  let attrs = $derived.by(() => {
    const a = { ...(spec.attrs || {}) };
    if (spec.class) a.class = spec.class;
    for (const [attr, propName] of Object.entries(spec.bind || {})) {
      a[attr] = props[propName];
    }
    return a;
  });

  let text = $derived(spec.text != null ? (props[spec.text] ?? "") : null);
  let children = $derived(spec.children || []);

  // Wire declared DOM events back as indah events, posting {value: element value}
  // so a bound signal round-trips (mirrors the built-in inputs).
  function events(el) {
    const handlers = Object.entries(spec.on || {}).map(([domEvent, ev]) => {
      const fn = (e) => postEvent(nodeId, ev.event, { value: e.currentTarget.value });
      el.addEventListener(domEvent, fn);
      return [domEvent, fn];
    });
    return {
      destroy() {
        for (const [d, fn] of handlers) el.removeEventListener(d, fn);
      },
    };
  }
</script>

{#if children.length || text !== null}
  <svelte:element this={spec.tag} {...attrs} use:events>
    {#if text !== null}{text}{/if}
    {#each children as child}<Self spec={child} {props} {nodeId} />{/each}
  </svelte:element>
{:else}
  <svelte:element this={spec.tag} {...attrs} use:events />
{/if}
