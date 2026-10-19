<script>
  // Rich table (ADR-0027): keyed rows, typed cells, sticky header, client sort/page and
  // key-based select. Rows are objects; a Stream-bound table grows through `append`
  // patches and the shell keeps the newest N (`trim`), so the DOM stays bounded.
  import { onMount, untrack } from "svelte";
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

  // Remote mode (IND-101): the server owns search, sort and the window. Every change is
  // debounced into one `query` event tagged with a rising seq; only an answer at least as
  // new as the last query sent is shown, so a slow old one never overwrites a newer one.
  let isRemote = $derived(!!props.remote);
  const QUERY_DEBOUNCE_MS = 150;
  let sentSeq = 0;
  let askTimer = null;
  let shown = $state(null); // the accepted window: {rows, total, offset, seq}
  let reqWin = null; // virtual mode: the {offset, limit} the next query asks for
  function sendQuery() {
    askTimer = null;
    sentSeq += 1;
    postEvent(nodeId, "query", {
      search: query.trim(),
      filters: {},
      sort: sortField === null ? null : [sortField, sortDir === 1 ? "asc" : "desc"],
      offset: reqWin ? reqWin.offset : page * (props.pageSize || 50),
      limit: reqWin ? reqWin.limit : props.pageSize || 50,
      seq: sentSeq,
    });
  }
  function ask(immediate = false) {
    if (!isRemote) return;
    clearTimeout(askTimer);
    if (immediate) sendQuery();
    else askTimer = setTimeout(sendQuery, QUERY_DEBOUNCE_MS);
  }
  onMount(() => {
    rowH = parseFloat(getComputedStyle(scroller).getPropertyValue("--row-h")) || 36;
    if (props.remote) {
      if (props.virtual) reqWin = { offset: 0, limit: INITIAL_WINDOW };
      ask(true); // first window, as soon as the table mounts
    }
    return () => clearTimeout(askTimer);
  });
  let lastWin = null;
  let lastAcceptedSeq = -1;
  $effect(() => {
    const w = props.window;
    if (!isRemote || !w || w === lastWin || w.seq < sentSeq) return;
    lastWin = w;
    shown = w;
    if (isVirtual) untrack(() => cacheWindow(w));
    else page = Math.floor(w.offset / (props.pageSize || 50)); // the server may have clamped it
  });

  // Virtual scroll (IND-102): render only the rows in view plus a little overscan, with
  // spacer rows standing in for the rest, so the DOM stays small at any row count. Rows
  // have one fixed height (--row-h). In remote mode the rows come from a small cache of
  // recent windows; a row not fetched yet shows as a placeholder until its window lands.
  const OVERSCAN = 8;
  const MAX_WINDOWS = 8;
  const INITIAL_WINDOW = 100;
  let isVirtual = $derived(!!props.virtual);
  let scrollTop = $state(0);
  let viewH = $state(0);
  let rowH = $state(36);
  let windows = $state([]); // [{offset, rows}], oldest first
  let pendingKey = null;
  function cacheWindow(w) {
    // The same query answered again (a reload): older windows may be stale, start over.
    const keep = w.seq === lastAcceptedSeq ? [] : windows.filter((c) => c.offset !== w.offset);
    lastAcceptedSeq = w.seq;
    pendingKey = null;
    windows = [...keep, { offset: w.offset, rows: w.rows }].slice(-MAX_WINDOWS);
  }
  // Search or sort changed: cached rows belong to the old query, and any answer still in
  // flight must not land in the fresh cache.
  function resetWindows() {
    windows = [];
    sentSeq += 1;
    pendingKey = null;
    reqWin = { offset: 0, limit: INITIAL_WINDOW };
    if (scroller) scroller.scrollTop = 0;
    scrollTop = 0;
  }
  function cachedRow(i) {
    for (let n = windows.length - 1; n >= 0; n--) {
      const c = windows[n];
      const r = i >= c.offset && i < c.offset + c.rows.length ? c.rows[i - c.offset] : null;
      if (r) return { r, i, k: rowKey ? r[rowKey] : i };
    }
    return null;
  }
  let vTotal = $derived(isRemote ? (shown?.total ?? 0) : sorted.length);
  let vStart = $derived(Math.max(0, Math.floor(scrollTop / rowH) - OVERSCAN));
  let vEnd = $derived(Math.min(vTotal, Math.ceil((scrollTop + viewH) / rowH) + OVERSCAN));
  let vRows = $derived.by(() => {
    if (!isVirtual) return [];
    const out = [];
    for (let i = vStart; i < vEnd; i++) {
      out.push((isRemote ? cachedRow(i) : sorted[i]) ?? { ph: true, k: `ph-${i}`, i });
    }
    return out;
  });
  // Remote + virtual: when rows near the viewport are not cached, ask for the block of
  // rows around it (aligned, so neighbouring scroll positions share a request).
  $effect(() => {
    if (!isVirtual || !isRemote || !shown) return;
    const first = vStart;
    const last = vEnd;
    void windows; // re-check as windows land
    untrack(() => {
      let missing = false;
      for (let i = first; i < last && !missing; i++) missing = cachedRow(i) === null;
      if (!missing) return;
      const step = Math.min(160, Math.max(20, last - first));
      const base = Math.floor(first / step) * step;
      const win = { offset: Math.max(0, base - step), limit: Math.min(500, step * 3) };
      const key = `${win.offset}:${win.limit}`;
      if (key === pendingKey) return;
      pendingKey = key;
      reqWin = win;
      ask();
    });
  });

  let allCols = $derived(props.columns ?? []);
  let colSpan = $derived(
    cols.length + (props.checkable ? 1 : 0) + (props.actions?.length ? 1 : 0) || 1,
  );
  let cols = $derived(allCols.filter((c) => !hidden.has(c.field)));
  let rows = $derived(isRemote ? (shown?.rows ?? []) : (props.rows ?? []));
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
    if (!q || isRemote) return indexed; // remote: the server already filtered
    return indexed.filter((row) =>
      allCols.some((c) => String(row.r[c.field] ?? "").toLowerCase().includes(q)),
    );
  });
  let sorted = $derived.by(() => {
    if (sortField === null || isRemote) return filtered; // remote: the server sorted
    return [...filtered].sort((x, y) => cmp(x.r[sortField], y.r[sortField]) * sortDir);
  });

  let pageSize = $derived(props.pageSize ?? 0);
  let pageCount = $derived(
    isRemote
      ? Math.max(1, Math.ceil((shown?.total ?? 0) / (pageSize || 50)))
      : pageSize > 0
        ? Math.max(1, Math.ceil(sorted.length / pageSize))
        : 1,
  );
  $effect(() => {
    if (!isRemote && page >= pageCount) page = pageCount - 1;
  });
  let view = $derived(
    isRemote ? sorted : pageSize > 0 ? sorted.slice(page * pageSize, (page + 1) * pageSize) : sorted,
  );
  function goToPage(next) {
    page = Math.max(0, Math.min(pageCount - 1, next));
    ask();
  }

  // Follow the tail: keep the newest row in view while rows arrive, unless the viewer
  // scrolled up (or a sort has reordered the rows, so "newest" is no longer the last).
  $effect(() => {
    view.length;
    if (props.follow && following && sortField === null && scroller) {
      scroller.scrollTop = scroller.scrollHeight;
    }
  });
  function onScroll() {
    if (isVirtual && scroller) scrollTop = scroller.scrollTop;
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
    if (isVirtual) resetWindows();
    ask();
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

{#snippet rowTpl(row)}
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
{/snippet}

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
          oninput={() => {
            page = 0;
            if (isVirtual && isRemote) resetWindows();
            ask();
          }}
        />
        {#if isRemote}
          <span class="table-count">{shown?.total ?? 0} rows</span>
        {:else if query.trim()}<span class="table-count">{sorted.length} of {rows.length}</span>{/if}
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
    class:virtual={isVirtual}
    data-density={props.density ?? null}
    style:max-height={props.height ?? null}
    style:height={isVirtual ? props.height : null}
    bind:this={scroller}
    bind:clientHeight={viewH}
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
        {#if isVirtual}
          <tr class="vspacer" aria-hidden="true" style:height="{vStart * rowH}px"
            ><td colspan={colSpan}></td></tr
          >
          {#each vRows as row (row.k)}
            {#if row.ph}
              <tr class="ph" aria-hidden="true"><td colspan={colSpan}>…</td></tr>
            {:else}
              {@render rowTpl(row)}
            {/if}
          {/each}
          <tr class="vspacer" aria-hidden="true" style:height="{Math.max(0, vTotal - vEnd) * rowH}px"
            ><td colspan={colSpan}></td></tr
          >
        {:else}
          {#each view as row (row.k)}
            {@render rowTpl(row)}
          {/each}
        {/if}
      </tbody>
    </table>
  </div>
  {#if (isRemote || pageSize > 0) && pageCount > 1}
    <div class="table-pager">
      <button type="button" onclick={() => goToPage(page - 1)} disabled={page === 0}
        >Prev</button
      >
      <span>Page {page + 1} / {pageCount}</span>
      <button
        type="button"
        onclick={() => goToPage(page + 1)}
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
