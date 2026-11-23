<script>
  // Svg (IND-275): a drawing that Python already sanitised into a tree [tag, attrs, ...children].
  // It is built with createElementNS and setAttribute, never parsed from markup, so nothing
  // active can arrive and no style attribute is needed under the strict CSP. Ids are prefixed
  // with the component's id so two drawings on a page cannot clash; local url(#id) follows.
  let { tree, label = "", decorative = false, nodeId = "svg" } = $props();
  let host = $state();

  const NS = "http://www.w3.org/2000/svg";
  const fix = (v) => v.replace(/url\(#([^)]+)\)/g, (_m, id) => `url(#${nodeId}-${id})`);

  function build(node) {
    const [tag, attrs, ...kids] = node;
    const el = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, k === "id" ? `${nodeId}-${v}` : fix(v));
    for (const kid of kids) el.append(typeof kid === "string" ? document.createTextNode(kid) : build(kid));
    return el;
  }

  $effect(() => {
    if (!host) return;
    host.replaceChildren();
    if (!tree) return;
    const svg = build(tree);
    svg.setAttribute("class", "svg-drawing");
    if (decorative) svg.setAttribute("aria-hidden", "true");
    else {
      svg.setAttribute("role", "img");
      svg.setAttribute("aria-label", label);
    }
    host.append(svg);
  });
</script>

<div class="svg-host" bind:this={host}></div>
