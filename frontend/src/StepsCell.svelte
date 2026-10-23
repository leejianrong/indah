<script>
  // Steps as a render-spec component (IND-163; ADR-0016 amendment): in a List item or a table cell
  // it is horizontal and compact unless `orientation` or `size` are bound to fields too.
  import Steps from "./Steps.svelte";
  let { items = [], orientation, size } = $props();
</script>

<Steps {items} orientation={orientation ?? "horizontal"} size={size ?? "compact"} />
