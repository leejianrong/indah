<script>
  import { nodeProps } from "./stores.js";
  import { postEvent } from "./api.js";
  import Self from "./Node.svelte";
  import Custom from "./Custom.svelte";

  let { node } = $props();
  let props = $derived($nodeProps.get(node.id) || {});

  // Value-bearing inputs (text box, slider) are two-way bound: a keystroke/drag is
  // POSTed and the server echoes the new value back as a patch. If we let that echo
  // re-set the DOM value *while the user is editing*, a stale echo (the round-trip
  // lags behind fast typing, especially through Colab's proxy) clobbers newer
  // keystrokes - the "missing letters" bug. So we sync the server value into the
  // element only when it does NOT have focus; while focused, the DOM owns it.
  let inputEl = $state();
  function syncFromServer() {
    if (!inputEl) return;
    const next = node.type === "slider" ? String(props.value ?? "") : (props.value ?? "");
    if (inputEl.value !== next) inputEl.value = next;
  }
  // While the user is editing (element focused), the DOM owns the value so a laggy
  // server echo can't clobber fast typing. Otherwise, adopt the server value - and
  // on blur, adopt whatever the server settled on while we were editing.
  $effect(() => {
    void props.value; // track the server value
    if (inputEl && document.activeElement !== inputEl) syncFromServer();
  });
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
      bind:this={inputEl}
      id={`${node.id}-input`}
      type="text"
      placeholder={props.placeholder ?? ""}
      oninput={(e) => postEvent(node.id, "input", { value: e.currentTarget.value })}
      onblur={syncFromServer}
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
      bind:this={inputEl}
      id={`${node.id}-input`}
      type="range"
      min={props.min}
      max={props.max}
      step={props.step}
      oninput={(e) => postEvent(node.id, "input", { value: Number(e.currentTarget.value) })}
      onblur={syncFromServer}
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
