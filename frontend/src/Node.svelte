<script>
  import { nodeProps } from "./stores.js";
  import { postEvent } from "./api.js";
  import Self from "./Node.svelte";
  import Custom from "./Custom.svelte";

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
{:else if node.type === "textinput"}
  <div class="field">
    {#if props.label}<label for={`${node.id}-input`}>{props.label}</label>{/if}
    <input
      id={`${node.id}-input`}
      type="text"
      placeholder={props.placeholder ?? ""}
      value={props.value ?? ""}
      oninput={(e) => postEvent(node.id, "input", { value: e.currentTarget.value })}
    />
  </div>
{:else if node.type === "streamtext"}
  <div class="field">
    {#if props.label}<span class="stream-label">{props.label}</span>{/if}
    <div class="streamtext">{props.text ?? ""}</div>
  </div>
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
{:else if node.type === "select"}
  <div class="field">
    {#if props.label}<label for={`${node.id}-input`}>{props.label}</label>{/if}
    <select
      id={`${node.id}-input`}
      value={props.value ?? ""}
      onchange={(e) => postEvent(node.id, "change", { value: e.currentTarget.value })}
    >
      {#each props.options ?? [] as option (option.value)}
        <option value={option.value}>{option.label}</option>
      {/each}
    </select>
  </div>
{:else if node.type === "image"}
  <img class="image" src={props.src ?? ""} alt={props.alt ?? ""} />
{:else if node.type === "dataframe"}
  <div class="field">
    {#if props.label}<span class="stream-label">{props.label}</span>{/if}
    <div class="table-scroll">
      <table class="dataframe">
        {#if props.data?.columns?.length}
          <thead>
            <tr>{#each props.data.columns as col}<th>{col}</th>{/each}</tr>
          </thead>
        {/if}
        <tbody>
          {#each props.data?.rows ?? [] as row}
            <tr>{#each row as cell}<td>{cell}</td>{/each}</tr>
          {/each}
        </tbody>
      </table>
    </div>
  </div>
{:else if props._spec}
  <Custom spec={props._spec} {props} nodeId={node.id} />
{:else}
  <div>[unknown: {node.type}]</div>
{/if}
