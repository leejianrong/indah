<script>
  // Interactive table (ADR-0021): client-side sort + paging, and row select that
  // round-trips to Python (binds a Signal, so a selection drives the rest of the
  // app). Data rides one reactive prop, like DataFrame - no protocol change.
  import { postEvent } from "./api.js";

  let { props, nodeId } = $props();

  let sortCol = $state(-1);
  let sortDir = $state(1); // 1 asc, -1 desc
  let page = $state(0);

  let cols = $derived(props.data?.columns ?? []);
  let rows = $derived(props.data?.rows ?? []);
  // Keep each row's original index so a click/highlight refers to the source row,
  // not its position in the sorted/paged view.
  let indexed = $derived(rows.map((r, i) => ({ r, i })));

  function cmp(a, b) {
    if (a == null && b == null) return 0;
    if (a == null) return -1;
    if (b == null) return 1;
    if (typeof a === "number" && typeof b === "number") return a - b;
    return String(a).localeCompare(String(b));
  }

  let sorted = $derived.by(() => {
    if (sortCol < 0) return indexed;
    return [...indexed].sort((x, y) => cmp(x.r[sortCol], y.r[sortCol]) * sortDir);
  });

  let pageSize = $derived(props.pageSize ?? 0);
  let pageCount = $derived(pageSize > 0 ? Math.max(1, Math.ceil(sorted.length / pageSize)) : 1);
  // Clamp the page if the data shrank.
  $effect(() => {
    if (page >= pageCount) page = pageCount - 1;
  });
  let view = $derived(
    pageSize > 0 ? sorted.slice(page * pageSize, (page + 1) * pageSize) : sorted,
  );

  function sortBy(c) {
    if (sortCol === c) sortDir = -sortDir;
    else {
      sortCol = c;
      sortDir = 1;
    }
    page = 0;
  }

  function selectRow(originalIndex) {
    if (props.selectable) postEvent(nodeId, "select", { index: originalIndex });
  }
</script>

<div class="field">
  {#if props.label}<span class="stream-label">{props.label}</span>{/if}
  <div class="table-scroll">
    <table class="dataframe table" class:selectable={props.selectable}>
      {#if cols.length}
        <thead>
          <tr>
            {#each cols as col, c}
              <th
                aria-sort={sortCol === c ? (sortDir === 1 ? "ascending" : "descending") : "none"}
              >
                <button type="button" class="th-sort" onclick={() => sortBy(c)}>
                  <span>{col}</span>
                  <span class="sort-caret" aria-hidden="true"
                    >{sortCol === c ? (sortDir === 1 ? "▲" : "▼") : "↕"}</span
                  >
                </button>
              </th>
            {/each}
          </tr>
        </thead>
      {/if}
      <tbody>
        {#each view as row (row.i)}
          <tr
            class:selected={props.value === row.i}
            onclick={() => selectRow(row.i)}
          >
            {#each row.r as cell}<td>{cell}</td>{/each}
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
