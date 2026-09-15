<script>
  // Renders the safe block tree produced by the Python Markdown parser
  // (src/indah/markdown.py). A node is either a string (a text leaf, which Svelte
  // escapes) or {tag, children, href?}. We only ever create allowlisted elements
  // and never set innerHTML, so there is no path from source text to injected
  // markup -- the same safe-by-construction model as Custom.svelte.
  import Self from "./Markdown.svelte";

  let { nodes = [] } = $props();

  const ALLOWED = new Set([
    "p", "h1", "h2", "h3", "h4", "h5", "h6", "pre", "code",
    "blockquote", "ul", "ol", "li", "strong", "em", "span",
  ]);
  const tagOf = (node) => (ALLOWED.has(node.tag) ? node.tag : "span");
</script>

{#each nodes as node}
  {#if typeof node === "string"}{node}{:else if node.tag === "br"}<br />{:else if node.tag === "hr"}<hr
    />{:else if node.tag === "a"}<a
      href={node.href}
      target="_blank"
      rel="noopener noreferrer nofollow"><Self nodes={node.children ?? []} /></a
    >{:else}<svelte:element this={tagOf(node)}><Self nodes={node.children ?? []} /></svelte:element
    >{/if}
{/each}
