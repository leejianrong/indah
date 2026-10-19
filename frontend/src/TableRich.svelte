<script>
  // Rich table (ADR-0027): keyed rows, typed cells, sticky header, client sort/page and
  // key-based select. Rows are objects; a Stream-bound table grows through `append`
  // patches and the shell keeps the newest N (`trim`), so the DOM stays bounded.
  import { postEvent } from "./api.js";
  import { now } from "./stores.js";

  let { props, nodeId } = $props();

  let sortField = $state(null);
  let sortDir = $state(1); // 1 asc, -1 desc
  let page = $state(0);

  let cols = $derived(props.columns ?? []);
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
  let sorted = $derived.by(() => {
    if (sortField === null) return indexed;
    return [...indexed].sort((x, y) => cmp(x.r[sortField], y.r[sortField]) * sortDir);
  });

  let pageSize = $derived(props.pageSize ?? 0);
  let pageCount = $derived(pageSize > 0 ? Math.max(1, Math.ceil(sorted.length / pageSize)) : 1);
  $effect(() => {
    if (page >= pageCount) page = pageCount - 1;
  });
  let view = $derived(
    pageSize > 0 ? sorted.slice(page * pageSize, (page + 1) * pageSize) : sorted,
  );

  function sortBy(col) {
    if (!col.sortable) return;
    if (sortField === col.field) sortDir = -sortDir;
    else {
      sortField = col.field;
      sortDir = 1;
    }
    page = 0;
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
  <div class="table-scroll rich" style:max-height={props.height ?? null}>
    <table class="dataframe table rich" class:selectable={props.selectable}>
      <thead>
        <tr>
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
        </tr>
      </thead>
      <tbody>
        {#each view as row (row.k)}
          <tr class:selected={props.value === row.k} onclick={() => selectRow(row)}>
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
