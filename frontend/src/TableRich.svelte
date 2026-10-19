<script>
  // Rich table (ADR-0027): keyed rows, typed cells, sticky header, client sort/page and
  // key-based select. Rows are objects; a Stream-bound table grows through `append`
  // patches and the shell keeps the newest N (`trim`), so the DOM stays bounded.
  import { postEvent } from "./api.js";
  import { now } from "./stores.js";
  import Overlay from "./Overlay.svelte";

  let { props, nodeId } = $props();

  let sortField = $state(null);
  let sortDir = $state(1); // 1 asc, -1 desc
  let page = $state(0);

  // Client-only view state (no round trip): the filter text, hidden columns (remembered
  // per page + table in localStorage) and whether the tail is being followed.
  let query = $state("");
  const storeKey = () => `indah-cols:${location.pathname}:${props.label || nodeId}`;
  function loadHidden() {
    try {
      return new Set(JSON.parse(localStorage.getItem(storeKey()) || "[]"));
    } catch (e) {
      return new Set();
    }
  }
  let hidden = $state(loadHidden());
  function toggleColumn(field) {
    const next = new Set(hidden);
    if (next.has(field)) next.delete(field);
    else next.add(field);
    hidden = next;
    try {
      localStorage.setItem(storeKey(), JSON.stringify([...next]));
    } catch (e) {
      /* storage blocked: the choice just is not remembered */
    }
  }
  let following = $state(true);
  let scroller = $state(null);

  let allCols = $derived(props.columns ?? []);
  let cols = $derived(allCols.filter((c) => !hidden.has(c.field)));
  let rows = $derived(props.rows ?? []);
  let rowKey = $derived(props.rowKey ?? null);

  function cmp(a, b) {
    if (a == null && b == null) return 0;
    if (a == null) return -1;
    if (b == null) return 1;
    if (typeof a === "number" && typeof b === "number") return a - b;
    return String(a).localeCompare(String(b));
  }

  // Keep each row's original index for selection when the table has no key.
  let indexed = $derived(rows.map((r, i) => ({ r, i, k: rowKey ? r[rowKey] : i })));
  // Case-insensitive match over every column, so streamed rows are filtered as they land.
  let filtered = $derived.by(() => {
    const q = query.trim().toLowerCase();
    if (!q) return indexed;
    return indexed.filter((row) =>
      allCols.some((c) => String(row.r[c.field] ?? "").toLowerCase().includes(q)),
    );
  });
  let sorted = $derived.by(() => {
    if (sortField === null) return filtered;
    return [...filtered].sort((x, y) => cmp(x.r[sortField], y.r[sortField]) * sortDir);
  });

  let pageSize = $derived(props.pageSize ?? 0);
  let pageCount = $derived(pageSize > 0 ? Math.max(1, Math.ceil(sorted.length / pageSize)) : 1);
  $effect(() => {
    if (page >= pageCount) page = pageCount - 1;
  });
  let view = $derived(
    pageSize > 0 ? sorted.slice(page * pageSize, (page + 1) * pageSize) : sorted,
  );

  // Follow the tail: keep the newest row in view while rows arrive, unless the viewer
  // scrolled up (or a sort has reordered the rows, so "newest" is no longer the last).
  $effect(() => {
    view.length;
    if (props.follow && following && sortField === null && scroller) {
      scroller.scrollTop = scroller.scrollHeight;
    }
  });
  function onScroll() {
    if (!props.follow || !scroller) return;
    following = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 24;
  }
  function resumeFollowing() {
    following = true;
    if (scroller) scroller.scrollTop = scroller.scrollHeight;
  }

  function sortBy(col) {
    if (!col.sortable) return;
    if (sortField === col.field) sortDir = -sortDir;
    else {
      sortField = col.field;
      sortDir = 1;
    }
    page = 0;
  }

  // Bulk check (a Signal[list] of keys on the server). The full new set is posted, so a
  // lost event can never leave the two sides adding up differently.
  let checkedKeys = $derived(new Set(props.checked ?? []));
  let allChecked = $derived(sorted.length > 0 && sorted.every((r) => checkedKeys.has(r.k)));
  function toggleCheck(row) {
    const next = new Set(checkedKeys);
    if (next.has(row.k)) next.delete(row.k);
    else next.add(row.k);
    postEvent(nodeId, "check", { keys: [...next] });
  }
  function toggleAll() {
    const next = new Set(checkedKeys);
    for (const r of sorted) {
      if (allChecked) next.delete(r.k);
      else next.add(r.k);
    }
    postEvent(nodeId, "check", { keys: [...next] });
  }

  // Row actions: one with `confirm` asks first, the rest post straight away.
  let pending = $state(null); // {action, key}
  function runAction(action, row) {
    if (action.confirm) pending = { action, key: row.k };
    else postEvent(nodeId, "action", { action: action.id, key: row.k });
  }

  function selectRow(row) {
    if (!props.selectable) return;
    postEvent(nodeId, "select", rowKey ? { key: row.k } : { index: row.i });
  }

  // "3s ago" for an ISO string or epoch (ms, or seconds when small). `now` ticks once a
  // second for the whole page, so every time cell stays live from one timer.
  function toMs(v) {
    if (typeof v === "number") return v < 1e11 ? v * 1000 : v;
    const t = Date.parse(v);
    return Number.isNaN(t) ? null : t;
  }
  function relTime(v, nowMs) {
    const ms = toMs(v);
    if (ms === null) return String(v ?? "");
    const s = Math.max(0, Math.round((nowMs - ms) / 1000));
    if (s < 5) return "just now";
    if (s < 60) return `${s}s ago`;
    if (s < 3600) return `${Math.floor(s / 60)}m ago`;
    if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
    return new Date(ms).toLocaleDateString();
  }
  function absTime(v) {
    const ms = toMs(v);
    return ms === null ? "" : new Date(ms).toISOString();
  }
  function tone(col, v) {
    return (col.tones && col.tones[String(v)]) || "neutral";
  }
  function fmtNumber(v) {
    return typeof v === "number" ? v.toLocaleString() : (v ?? "");
  }
</script>

<div class="field">
  {#if props.label}<span class="stream-label">{props.label}</span>{/if}
  {#if props.search || props.columnToggle || props.follow}
    <div class="table-toolbar">
      {#if props.search}
        <input
          type="search"
          class="table-search"
          placeholder="Filter rows"
          aria-label="Filter rows"
          bind:value={query}
        />
        {#if query.trim()}<span class="table-count">{sorted.length} of {rows.length}</span>{/if}
      {/if}
      {#if props.columnToggle}
        <details class="col-toggle">
          <summary>Columns</summary>
          <div class="col-toggle-menu">
            {#each allCols as col (col.field)}
              <label>
                <input
                  type="checkbox"
                  checked={!hidden.has(col.field)}
                  onchange={() => toggleColumn(col.field)}
                />
                {col.title}
              </label>
            {/each}
          </div>
        </details>
      {/if}
      {#if props.follow && !following && sortField === null}
        <button type="button" class="follow-resume" onclick={resumeFollowing}
          >Resume following</button
        >
      {/if}
    </div>
  {/if}
  <div
    class="table-scroll rich"
    style:max-height={props.height ?? null}
    bind:this={scroller}
    onscroll={onScroll}
  >
    <table class="dataframe table rich" class:selectable={props.selectable}>
      <thead>
        <tr>
          {#if props.checkable}
            <th class="check-col">
              <input
                type="checkbox"
                aria-label="Select all rows"
                checked={allChecked}
                onchange={toggleAll}
              />
            </th>
          {/if}
          {#each cols as col (col.field)}
            <th
              style:width={col.width ?? null}
              class:num={col.kind === "number"}
              aria-sort={sortField === col.field
                ? sortDir === 1
                  ? "ascending"
                  : "descending"
                : "none"}
            >
              <button
                type="button"
                class="th-sort"
                disabled={!col.sortable}
                onclick={() => sortBy(col)}
              >
                <span>{col.title}</span>
                {#if col.sortable}
                  <span class="sort-caret" aria-hidden="true"
                    >{sortField === col.field ? (sortDir === 1 ? "▲" : "▼") : "↕"}</span
                  >
                {/if}
              </button>
            </th>
          {/each}
          {#if props.actions?.length}<th class="actions-col"><span class="sr-only">Actions</span></th>{/if}
        </tr>
      </thead>
      <tbody>
        {#each view as row (row.k)}
          <tr class:selected={props.value === row.k} onclick={() => selectRow(row)}>
            {#if props.checkable}
              <td class="check-col" onclick={(e) => e.stopPropagation()}>
                <input
                  type="checkbox"
                  aria-label="Select row"
                  checked={checkedKeys.has(row.k)}
                  onchange={() => toggleCheck(row)}
                />
              </td>
            {/if}
            {#each cols as col (col.field)}
              {@const v = row.r[col.field]}
              {#if col.kind === "badge"}
                <td><span class="cell-badge tone-{tone(col, v)}">{v ?? ""}</span></td>
              {:else if col.kind === "mono"}
                <td style:max-width={col.width ?? null}
                  ><code class="cell-mono" title={v}>{v ?? ""}</code></td
                >
              {:else if col.kind === "time"}
                <td title={absTime(v)}>{relTime(v, $now)}</td>
              {:else if col.kind === "number"}
                <td class="num">{fmtNumber(v)}</td>
              {:else}
                <td>{v ?? ""}</td>
              {/if}
            {/each}
            {#if props.actions?.length}
              <td class="actions-col" onclick={(e) => e.stopPropagation()}>
                {#each props.actions as action (action.id)}
                  <button
                    type="button"
                    class="row-action {action.variant ?? 'ghost'}"
                    onclick={() => runAction(action, row)}>{action.label}</button
                  >
                {/each}
              </td>
            {/if}
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
  {#if pageSize > 0 && pageCount > 1}
    <div class="table-pager">
      <button type="button" onclick={() => (page = Math.max(0, page - 1))} disabled={page === 0}
        >Prev</button
      >
      <span>Page {page + 1} / {pageCount}</span>
      <button
        type="button"
        onclick={() => (page = Math.min(pageCount - 1, page + 1))}
        disabled={page >= pageCount - 1}>Next</button
      >
    </div>
  {/if}
</div>

{#if pending}
  <Overlay
    kind="modal"
    size="sm"
    title={pending.action.confirm}
    onclose={() => (pending = null)}
    initialFocus=".confirm-no"
  >
    <div class="confirm-actions">
      <button type="button" class="ghost confirm-no" onclick={() => (pending = null)}>Cancel</button>
      <button
        type="button"
        class="confirm-yes"
        onclick={() => {
          postEvent(nodeId, "action", { action: pending.action.id, key: pending.key });
          pending = null;
        }}>{pending.action.label}</button
      >
    </div>
  </Overlay>
{/if}
