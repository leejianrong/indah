<script>
  // JSON/YAML editor (ADR-0032). CodeMirror lives in a separate same-origin module that is
  // fetched on the first render of this component, so an app with no editor never loads it.
  // Like every input the focused editor is client-owned (ADR-0013): a server echo while it
  // has focus is ignored and re-synced on blur, and keystrokes are debounced and flushed on blur.
  import { onMount } from "svelte";
  import { apiUrl, postEvent } from "./api.js";

  let { props, nodeId } = $props();

  let host = $state();
  let editor = null;
  let failed = $state(false);
  let timer = null;
  let fallback = $state();

  const value = $derived(props.value ?? "");

  // Sends pending local edits; true when it did.
  function flush() {
    if (timer === null) return false;
    clearTimeout(timer);
    timer = null;
    const text = editor ? editor.getDoc() : (fallback?.value ?? "");
    postEvent(nodeId, "input", { value: text });
    return true;
  }
  function changed() {
    if (timer !== null) clearTimeout(timer);
    timer = setTimeout(flush, 150);
  }
  function save(text) {
    if (timer !== null) {
      clearTimeout(timer);
      timer = null;
    }
    postEvent(nodeId, "save", { value: text });
  }
  function format() {
    flush();
    postEvent(nodeId, "format", { value: editor ? editor.getDoc() : (fallback?.value ?? "") });
  }
  function blurred() {
    // Just sent local edits: the server is about to echo them, and `value` is still the old
    // text, so resyncing now would revert the viewer's typing. Otherwise (nothing sent) the
    // editor may have ignored a server change while focused, so catch up to it.
    if (flush()) return;
    if (editor) editor.setDoc(value);
    else if (fallback) fallback.value = value;
  }

  onMount(() => {
    let dead = false;
    import(/* @vite-ignore */ apiUrl("api/editor.js"))
      .then((mod) => {
        if (dead) return;
        editor = mod.createEditor(host, {
          doc: value,
          language: props.language,
          readOnly: props.readOnly,
          lint: props.lint,
          label: props.label,
          placeholder: props.placeholder,
          onChange: changed,
          onSave: props.save ? save : undefined,
        });
        host.addEventListener("focusout", (e) => {
          if (!host.contains(e.relatedTarget)) blurred();
        });
        version += 1;
      })
      .catch(() => {
        failed = true; // blocked or offline: a plain text area, same two-way binding
      });
    return () => {
      dead = true;
      if (timer !== null) flush();
      editor?.destroy();
      editor = null;
    };
  });

  // Reflect server-side changes (and prop changes) into the editor while it is not focused.
  let version = $state(0);
  $effect(() => {
    void version;
    const v = value;
    if (editor && !editor.hasFocus()) editor.setDoc(v);
  });
  $effect(() => {
    void version;
    editor?.configure({ language: props.language, readOnly: props.readOnly, lint: props.lint });
  });
</script>

<div class="field">
  {#if props.label || props.format}
    <div class="code-head">
      {#if props.label}<span class="stream-label" id={`${nodeId}-label`}>{props.label}</span>{/if}
      {#if props.format}
        <button type="button" class="ghost code-format" onclick={format}>Format</button>
      {/if}
    </div>
  {/if}
  {#if failed}
    <textarea
      bind:this={fallback}
      class="code-fallback"
      aria-labelledby={props.label ? `${nodeId}-label` : null}
      readonly={props.readOnly}
      {value}
      oninput={changed}
      onblur={blurred}
      style:height={props.height ?? "24rem"}
    ></textarea>
  {:else}
    <div
      bind:this={host}
      class="code-editor"
      data-language={props.language}
      style:height={props.height ?? "24rem"}
    ></div>
  {/if}
</div>

<style>
  .code-head { display: flex; align-items: center; justify-content: space-between; gap: 0.5rem; }
  .code-format { padding: 0.15rem 0.7rem; font-size: 0.8rem; }
  .code-editor { display: flex; flex-direction: column; min-height: 6rem; }
  .code-editor :global(.cm-editor) { height: 100%; }
  .code-fallback { font-family: var(--font-mono); font-size: 0.85rem; resize: vertical; }
</style>
