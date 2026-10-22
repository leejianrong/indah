<script>
  // Generic renderer for a registered custom component (ADR-0012). It interprets a
  // declarative render spec that arrived on the wire as the `_spec` prop, so a new
  // component type renders with no shell rebuild and no runtime Node.
  import { postEvent } from "./api.js";
  import Self from "./Custom.svelte";

  // `row` is {key, index} when the spec renders one row of a keyed List; it rides along
  // on every event so the server knows which row the event came from.
  let { spec, props, nodeId, row = null } = $props();

  // Static attrs + static class + props bound onto element attributes. `value` is not
  // spread: like the built-in inputs (ADR-0013), the element owns it while it has focus,
  // so a late server echo cannot overwrite what the user is typing.
  const ownsValue = ["input", "textarea", "select"].includes(spec.tag);
  let attrs = $derived.by(() => {
    const a = { ...(spec.attrs || {}) };
    if (spec.class) a.class = spec.class;
    for (const [attr, propName] of Object.entries(spec.bind || {})) {
      if (!(ownsValue && attr === "value")) a[attr] = props[propName];
    }
    return a;
  });

  let el = $state();
  let valueProp = $derived(ownsValue ? spec.bind?.value : undefined);
  let serverValue = $derived(valueProp ? (props[valueProp] ?? "") : undefined);
  $effect(() => {
    const v = serverValue;
    if (el && v !== undefined && document.activeElement !== el && el.value !== String(v)) {
      el.value = v;
    }
  });
  function syncOnBlur() {
    if (serverValue !== undefined && el && el.value !== String(serverValue)) el.value = serverValue;
  }

  let text = $derived(
    spec.literal != null ? spec.literal : spec.text != null ? (props[spec.text] ?? "") : null,
  );
  let children = $derived(spec.children || []);

  // Wire declared DOM events back as indah events, posting {value: element value}
  // so a bound signal round-trips (mirrors the built-in inputs).
  function events(el) {
    const handlers = Object.entries(spec.on || {}).map(([domEvent, ev]) => {
      const fn = (e) => postEvent(nodeId, ev.event, { value: e.currentTarget.value, ...(row || {}) });
      el.addEventListener(domEvent, fn);
      return [domEvent, fn];
    });
    el.addEventListener("blur", syncOnBlur);
    return {
      destroy() {
        for (const [d, fn] of handlers) el.removeEventListener(d, fn);
        el.removeEventListener("blur", syncOnBlur);
      },
    };
  }
</script>

{#if children.length || text !== null}
  <svelte:element this={spec.tag} bind:this={el} {...attrs} use:events>
    {#if text !== null}{text}{/if}
    {#each children as child}<Self spec={child} {props} {nodeId} {row} />{/each}
  </svelte:element>
{:else}
  <svelte:element this={spec.tag} bind:this={el} {...attrs} use:events />
{/if}
