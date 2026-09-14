<script>
  import { nodeProps } from "./stores.js";
  import { postEvent } from "./api.js";
  import Self from "./Node.svelte";

  let { node } = $props();
  let props = $derived($nodeProps.get(node.id) || {});
</script>

{#if node.type === "column"}
  <div class="column">
    {#each node.children as child (child.id)}
      <Self node={child} />
    {/each}
  </div>
{:else if node.type === "text"}
  <div class="text">{props.text ?? ""}</div>
{:else if node.type === "button"}
  <button onclick={() => postEvent(node.id, "click")}>{props.label ?? ""}</button>
{:else if node.type === "slider"}
  <div class="field">
    <label for={`${node.id}-input`}>{props.label ?? ""}</label>
    <input
      id={`${node.id}-input`}
      type="range"
      min={props.min}
      max={props.max}
      step={props.step}
      value={props.value}
      oninput={(e) => postEvent(node.id, "input", { value: Number(e.currentTarget.value) })}
    />
  </div>
{:else}
  <div>[unknown: {node.type}]</div>
{/if}
