<script>
  import { nodeProps } from "./stores.js";
  import { apiUrl, postEvent, postUpload, appPath, hrefFor, pushPath } from "./api.js";
  import Self from "./Node.svelte";
  import Custom from "./Custom.svelte";
  import Markdown from "./Markdown.svelte";
  import Chart from "./Chart.svelte";
  import Heatmap from "./Heatmap.svelte";
  import MapView from "./Map.svelte";
  import Table from "./Table.svelte";
  import ImageOverlay from "./ImageOverlay.svelte";
  import Overlay from "./Overlay.svelte";
  import Tip from "./Tip.svelte";
  import Shortcuts from "./Shortcuts.svelte";
  import SplitPane from "./SplitPane.svelte";
  import JsonTree from "./JsonTree.svelte";
  import Diff from "./Diff.svelte";

  let { node } = $props();
  let props = $derived($nodeProps.get(node.id) || {});

  // Value-bearing inputs (text box, slider) are two-way bound: a keystroke/drag is
  // POSTed and the server echoes the new value back as a patch. If we let that echo
  // re-set the DOM value *while the user is editing*, a stale echo (the round-trip
  // lags behind fast typing, especially through Colab's proxy) clobbers newer
  // keystrokes - the "missing letters" bug. So we sync the server value into the
  // element only when it does NOT have focus; while focused, the DOM owns it.
  let inputEl = $state();

  // Router: Back/Forward changes the address bar without a request, so tell the server which
  // in-app page the tab is on now. (Link clicks and ctx.navigate push history themselves.)
  $effect(() => {
    if (node.type !== "router") return;
    const onPop = () => postEvent(node.id, "navigate", { path: appPath() });
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  });
  function onLink(e) {
    // Let the browser handle anything that is not a plain left click (new tab, new window,
    // download), so a Link is a real link.
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    pushPath(props.to);
    postEvent(node.id, "navigate", { path: props.to });
  }

  // MasterDetail swaps the split for a drawer on a narrow viewport.
  let narrow = $state(false);
  $effect(() => {
    if (node.type !== "masterdetail") return;
    const mq = window.matchMedia("(max-width: 700px)");
    narrow = mq.matches;
    const on = (e) => (narrow = e.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  });

  // Button(confirm=...): the click is posted only after the user accepts the dialog.
  let confirming = $state(false);

  // Upload status shown under a file input while the multipart POST is in flight
  // and after it settles (the result itself arrives over SSE as ordinary patches).
  let uploadStatus = $state("");
  async function onUpload(e) {
    const files = e.currentTarget.files;
    if (!files || !files.length) return;
    const names = Array.from(files, (f) => f.name).join(", ");
    uploadStatus = `Uploading ${names}...`;
    const ok = await postUpload(node.id, files);
    uploadStatus = ok ? `Uploaded ${names}` : `Upload failed: ${names}`;
  }

  function syncFromServer() {
    if (!inputEl) return;
    // Compare/assign as a string: element .value is always a string, so coercing
    // keeps text/slider/number/date on the same focused-echo path.
    const next = props.value == null ? "" : String(props.value);
    if (inputEl.value !== next) inputEl.value = next;
  }
  // While the user is editing (element focused), the DOM owns the value so a laggy
  // server echo can't clobber fast typing. Otherwise, adopt the server value - and
  // on blur, adopt whatever the server settled on while we were editing.
  $effect(() => {
    void props.value; // track the server value
    if (inputEl && document.activeElement !== inputEl) syncFromServer();
  });

  // A text area batches keystrokes: one POST per pause (150 ms), not per character,
  // and a blur flushes at once so a click right after typing never reads stale text.
  let areaTimer = null;
  function flushArea() {
    if (areaTimer === null) return;
    clearTimeout(areaTimer);
    areaTimer = null;
    if (inputEl) postEvent(node.id, "input", { value: inputEl.value });
  }
  function onAreaInput() {
    if (areaTimer !== null) clearTimeout(areaTimer);
    areaTimer = setTimeout(flushArea, 150);
  }
  function onAreaBlur() {
    flushArea();
    syncFromServer();
  }

  // Keep a chat pinned to the newest message. The dependency array is re-created
  // whenever messages/pending change, so the action's update() runs and scrolls.
  function autoscroll(node) {
    const toBottom = () => {
      node.scrollTop = node.scrollHeight;
    };
    toBottom();
    return { update: toBottom };
  }
</script>

{#snippet body()}
{#if node.type === "column"}
  <div class="column">
    {#each node.children as child (child.id)}
      <Self node={child} />
    {/each}
  </div>
{:else if node.type === "card"}
  <section class="card">
    {#if props.title}<h3 class="card-title">{props.title}</h3>{/if}
    {#each node.children as child (child.id)}
      <Self node={child} />
    {/each}
  </section>
{:else if node.type === "row"}
  <div
    class="row"
    style="gap: {props.gap ?? '1rem'}; flex-wrap: {props.wrap === false
      ? 'nowrap'
      : 'wrap'}; align-items: {props.align ?? 'stretch'};"
  >
    {#each node.children as child (child.id)}
      <Self node={child} />
    {/each}
  </div>
{:else if node.type === "grid"}
  <div
    class="grid"
    style="gap: {props.gap ?? '1rem'}; grid-template-columns: repeat({props.columns ??
      2}, minmax(0, 1fr));"
  >
    {#each node.children as child (child.id)}
      <Self node={child} />
    {/each}
  </div>
{:else if node.type === "sidebar"}
  <div class="sidebar-layout">
    {#if node.children.length}
      <aside class="sidebar-aside"><Self node={node.children[0]} /></aside>
    {/if}
    <div class="sidebar-main">
      {#each node.children.slice(1) as child (child.id)}
        <Self node={child} />
      {/each}
    </div>
  </div>
{:else if node.type === "diff"}
  <Diff {props} />
{:else if node.type === "jsontree"}
  <JsonTree {props} />
{:else if node.type === "router"}
  {#each node.children as child, i (child.id)}
    {#if i === props.active}<Self node={child} />{/if}
  {/each}
{:else if node.type === "link"}
  <a
    class="link"
    class:active={props.active}
    href={hrefFor(props.to)}
    aria-current={props.active ? "page" : null}
    onclick={onLink}>{props.label}</a
  >
{:else if node.type === "splitpane"}
  <SplitPane
    id={node.id}
    direction={props.direction}
    initial={props.initial}
    min={props.min}
    storageKey={props.key}
    height={props.height}
  >
    {#snippet first()}<Self node={node.children[0]} />{/snippet}
    {#snippet second()}<Self node={node.children[1]} />{/snippet}
  </SplitPane>
{:else if node.type === "masterdetail"}
  {#if narrow}
    <Self node={node.children[0]} />
    {#if props.open}
      <Overlay kind="drawer" side="right" title={props.title} onclose={() => postEvent(node.id, "close")}>
        <Self node={node.children[1]} />
      </Overlay>
    {/if}
  {:else}
    <SplitPane id={node.id} initial={props.initial} min={props.min} storageKey={props.key}>
      {#snippet first()}<Self node={node.children[0]} />{/snippet}
      {#snippet second()}<Self node={node.children[1]} />{/snippet}
    </SplitPane>
  {/if}
{:else if node.type === "tabs"}
  <div class="tabs">
    <div class="tablist" role="tablist">
      {#each props.labels ?? [] as label, i}
        <button
          class="tab"
          class:active={(props.active ?? 0) === i}
          role="tab"
          aria-selected={(props.active ?? 0) === i}
          onclick={() => postEvent(node.id, "select", { index: i })}>{label}</button
        >
      {/each}
    </div>
    {#each node.children as child, i (child.id)}
      {#if (props.active ?? 0) === i}
        <div class="tabpanel" role="tabpanel"><Self node={child} /></div>
      {/if}
    {/each}
  </div>
{:else if node.type === "expander"}
  <div class="expander" class:open={props.open}>
    <button
      class="expander-summary"
      aria-expanded={props.open ? "true" : "false"}
      onclick={() => postEvent(node.id, "toggle")}
    >
      <span class="expander-caret" aria-hidden="true">▶</span>
      <span>{props.label ?? ""}</span>
    </button>
    {#if props.open}
      <div class="expander-body">
        {#each node.children as child (child.id)}
          <Self node={child} />
        {/each}
      </div>
    {/if}
  </div>
{:else if node.type === "modal" || node.type === "drawer"}
  {#if props.open}
    <Overlay
      kind={node.type}
      side={props.side}
      size={props.size}
      title={props.title}
      onclose={() => postEvent(node.id, "close")}
    >
      {#each node.children as child (child.id)}
        <Self node={child} />
      {/each}
    </Overlay>
  {/if}
{:else if node.type === "list"}
  <div class="list">
    {#if (props.items ?? []).length === 0}
      {#if props.empty}<div class="list-empty">{props.empty}</div>{/if}
    {:else}
      {#each props.items ?? [] as item, i (props.keyField ? item[props.keyField] : (item?.key ?? item?.id ?? i))}
        {#if props.template}
          <div class="list-item">
            <Custom
              spec={props.template}
              props={item}
              nodeId={node.id}
              row={props.keyField ? { key: item[props.keyField], index: i } : null}
            />
          </div>
        {:else}
          <div class="list-item">{item}</div>
        {/if}
      {/each}
    {/if}
  </div>
{:else if node.type === "chat"}
  <div class="field">
    {#if props.label}<span class="stream-label">{props.label}</span>{/if}
    <div class="chat" use:autoscroll={[props.messages, props.pending]}>
      {#each props.messages ?? [] as m, i (i)}
        <div class="bubble role-{m.role}">
          <span class="bubble-role">{m.role}</span>
          <div class="bubble-body">{m.content}</div>
        </div>
      {/each}
      {#if props.pending}
        <div class="bubble role-assistant pending">
          <span class="bubble-role">assistant</span>
          <div class="bubble-body">{props.pending}</div>
        </div>
      {/if}
    </div>
  </div>
{:else if node.type === "gallery"}
  <div class="field">
    {#if props.label}<span class="stream-label">{props.label}</span>{/if}
    {#if (props.images ?? []).length === 0}
      <div class="list-empty">No images yet.</div>
    {:else}
      <div
        class="gallery"
        style="grid-template-columns: repeat({props.columns ?? 3}, minmax(0, 1fr));"
      >
        {#each props.images ?? [] as img, i (img.src + i)}
          <figure class="gallery-item">
            <img src={img.src} alt={img.alt ?? ""} />
            {#if img.caption}<figcaption>{img.caption}</figcaption>{/if}
          </figure>
        {/each}
      </div>
    {/if}
  </div>
{:else if node.type === "text"}
  {#if props.markdown}
    <div class="markdown"><Markdown nodes={props.blocks ?? []} /></div>
  {:else}
    <div class="text">{props.text ?? ""}</div>
  {/if}
{:else if node.type === "progress"}
  <div class="field">
    {#if props.label}<span class="stream-label">{props.label}</span>{/if}
    {#if props.value == null}
      <progress class="progress"></progress>
    {:else}
      <progress class="progress" value={props.value} max={props.max ?? 1}></progress>
    {/if}
  </div>
{:else if node.type === "spinner"}
  {#if props.active ?? true}
    <div class="spinner-box" role="status">
      <span class="spinner" aria-hidden="true"></span>
      {#if props.label}<span class="spinner-label">{props.label}</span>{/if}
    </div>
  {/if}
{:else if node.type === "button"}
  <button
    class:tonal={props.variant === "tonal"}
    class:ghost={props.variant === "ghost"}
    onclick={() => (props.confirm ? (confirming = true) : postEvent(node.id, "click"))}
    >{props.label ?? ""}</button
  >
  {#if confirming}
    <Overlay kind="modal" size="sm" title={props.confirm} onclose={() => (confirming = false)} initialFocus=".confirm-no">
      <div class="confirm-actions">
        <button type="button" class="ghost confirm-no" onclick={() => (confirming = false)}>Cancel</button>
        <button
          type="button"
          class="confirm-yes"
          onclick={() => {
            confirming = false;
            postEvent(node.id, "click");
          }}>{props.label ?? "OK"}</button
        >
      </div>
    </Overlay>
  {/if}
{:else if node.type === "textinput"}
  <div class="field">
    {#if props.label}<label for={`${node.id}-input`}>{props.label}</label>{/if}
    <input
      bind:this={inputEl}
      id={`${node.id}-input`}
      type={props.password ? "password" : "text"}
      autocomplete={props.password ? "off" : null}
      placeholder={props.placeholder ?? ""}
      oninput={(e) => postEvent(node.id, "input", { value: e.currentTarget.value })}
      onkeydown={(e) => { if (e.key === "Enter") postEvent(node.id, "submit"); }}
      onblur={syncFromServer}
    />
  </div>
{:else if node.type === "textarea"}
  <div class="field">
    {#if props.label}<label for={`${node.id}-input`}>{props.label}</label>{/if}
    <textarea
      bind:this={inputEl}
      id={`${node.id}-input`}
      rows={props.rows ?? 4}
      placeholder={props.placeholder ?? ""}
      oninput={onAreaInput}
      onblur={onAreaBlur}
    ></textarea>
  </div>
{:else if node.type === "switch"}
  <div class="switch-row">
    <button
      type="button"
      class="switch"
      role="switch"
      aria-checked={props.checked ? "true" : "false"}
      aria-label={props.label || null}
      onclick={() => postEvent(node.id, "change", { value: !props.checked })}
    ><span class="switch-knob"></span></button>
    {#if props.label}<span class="switch-label">{props.label}</span>{/if}
  </div>
{:else if node.type === "shortcuts"}
  <Shortcuts {node} {props} />
{:else if node.type === "badge"}
  <span class="badge tone-{props.tone ?? 'neutral'}">{props.text ?? ""}</span>
{:else if node.type === "checkbox"}
  <label class="check">
    <input
      type="checkbox"
      checked={props.checked ?? false}
      onchange={(e) => postEvent(node.id, "change", { value: e.currentTarget.checked })}
    />
    {#if props.label}<span>{props.label}</span>{/if}
  </label>
{:else if node.type === "number"}
  <div class="field">
    {#if props.label}<label for={`${node.id}-input`}>{props.label}</label>{/if}
    <input
      bind:this={inputEl}
      id={`${node.id}-input`}
      type="number"
      min={props.min ?? undefined}
      max={props.max ?? undefined}
      step={props.step ?? undefined}
      oninput={(e) => postEvent(node.id, "input", { value: Number(e.currentTarget.value) })}
      onblur={syncFromServer}
    />
  </div>
{:else if node.type === "date"}
  <div class="field">
    {#if props.label}<label for={`${node.id}-input`}>{props.label}</label>{/if}
    <input
      bind:this={inputEl}
      id={`${node.id}-input`}
      type="date"
      oninput={(e) => postEvent(node.id, "input", { value: e.currentTarget.value })}
      onblur={syncFromServer}
    />
  </div>
{:else if node.type === "radio"}
  <div class="field">
    {#if props.label}<span class="stream-label">{props.label}</span>{/if}
    <div class="radio-group">
      {#each props.options ?? [] as option (option.value)}
        <label class="check">
          <input
            type="radio"
            name={node.id}
            value={option.value}
            checked={props.value === option.value}
            onchange={(e) => postEvent(node.id, "change", { value: e.currentTarget.value })}
          />
          <span>{option.label}</span>
        </label>
      {/each}
    </div>
  </div>
{:else if node.type === "multiselect"}
  <div class="field">
    {#if props.label}<label for={`${node.id}-input`}>{props.label}</label>{/if}
    <select
      id={`${node.id}-input`}
      multiple
      onchange={(e) =>
        postEvent(node.id, "change", {
          value: Array.from(e.currentTarget.selectedOptions).map((o) => o.value),
        })}
    >
      {#each props.options ?? [] as option (option.value)}
        <option value={option.value} selected={(props.value ?? []).includes(option.value)}
          >{option.label}</option
        >
      {/each}
    </select>
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
{:else if node.type === "upload"}
  <div class="field upload">
    {#if props.label}<label for={`${node.id}-input`}>{props.label}</label>{/if}
    <input
      id={`${node.id}-input`}
      type="file"
      accept={props.accept || undefined}
      multiple={props.multiple || undefined}
      onchange={onUpload}
    />
    {#if uploadStatus}<span class="upload-status">{uploadStatus}</span>{/if}
  </div>
{:else if node.type === "download"}
  {#if props.href}
    <a
      class="download"
      href={apiUrl(props.href)}
      download={props.filename || undefined}
      rel="noopener">{props.label ?? "Download"}</a
    >
  {:else}
    <span class="download disabled">{props.label ?? "Download"}</span>
  {/if}
{:else if node.type === "chart"}
  <div class="field">
    {#if props.label}<span class="stream-label">{props.label}</span>{/if}
    <Chart {props} />
  </div>
{:else if node.type === "heatmap"}
  <div class="field">
    {#if props.label}<span class="stream-label">{props.label}</span>{/if}
    <Heatmap {props} />
  </div>
{:else if node.type === "map"}
  <div class="field">
    {#if props.label}<span class="stream-label">{props.label}</span>{/if}
    <MapView {props} />
  </div>
{:else if node.type === "image"}
  <img class="image" src={props.src ?? ""} alt={props.alt ?? ""} />
{:else if node.type === "audio"}
  {#if props.src}
    <audio class="audio" controls src={props.src}></audio>
  {:else}
    <span class="audio audio-empty">No audio</span>
  {/if}
{:else if node.type === "imageoverlay"}
  <ImageOverlay {props} />
{:else if node.type === "table"}
  <Table {props} nodeId={node.id} />
{:else if node.type === "stat"}
  <div class="stat">
    {#if props.label}<span class="stat-label">{props.label}</span>{/if}
    <span class="stat-value">{props.value ?? ""}</span>
    {#if props.delta != null}
      <span class="stat-delta" class:down={String(props.delta).startsWith("-")}>{props.delta}</span>
    {/if}
    {#if props.help}<span class="stat-help">{props.help}</span>{/if}
  </div>
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
{/snippet}

{#if props.tooltip}
  <Tip text={props.tooltip}>{@render body()}</Tip>
{:else}
  {@render body()}
{/if}
