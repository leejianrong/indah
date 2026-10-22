<script>
  // The app frame (IND-147): a rail that stays put while the page scrolls, beside the main
  // region, with an optional top bar. Under 760px the rail becomes a drawer behind a menu
  // button; Escape, the backdrop, or choosing a link or button in the rail closes it.
  import { onMount, tick } from "svelte";

  let { railWidth = "256px", hasTop = false, rail, main, top = null } = $props();

  const QUERY = "(max-width: 760px)";
  let narrow = $state(false);
  let open = $state(false);
  let railEl = $state();
  let menuEl = $state();

  onMount(() => {
    const mq = window.matchMedia(QUERY);
    const sync = () => {
      narrow = mq.matches;
      if (!narrow) open = false;
    };
    sync();
    mq.addEventListener("change", sync);
    return () => mq.removeEventListener("change", sync);
  });

  async function show() {
    open = true;
    await tick();
    railEl?.querySelector("a[href], button, input, select, textarea, [tabindex]")?.focus();
  }
  function hide(restoreFocus = true) {
    if (!open) return;
    open = false;
    if (restoreFocus) menuEl?.focus();
  }
  function onKey(e) {
    if (open && e.key === "Escape") {
      e.stopPropagation();
      hide();
    }
  }
  // Choosing something that navigates or acts closes the drawer; a select or text field inside
  // the rail (a project switcher) does not.
  function onRailClick(e) {
    if (narrow && e.target.closest("a[href], button")) hide(false);
  }
  // A closed drawer is off screen and must not be reachable by keyboard.
  let inert = $derived(narrow && !open);
</script>

<svelte:window onkeydown={onKey} />

<div class="appshell" class:narrow style="--rail-w: {railWidth}">
  {#if narrow && open}
    <div class="backdrop" onclick={() => hide()} aria-hidden="true"></div>
  {/if}
  <aside
    class="rail"
    class:open
    bind:this={railEl}
    {inert}
    aria-label="Navigation"
    onclick={onRailClick}
  >
    {@render rail()}
  </aside>
  <div class="column">
    {#if narrow || hasTop}
      <div class="bar">
        {#if narrow}
          <button
            type="button"
            class="menu"
            bind:this={menuEl}
            aria-label="Open the menu"
            aria-expanded={open}
            onclick={show}
          >
            <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
              <path d="M4 6h16M4 12h16M4 18h16" stroke="currentColor" stroke-width="2" stroke-linecap="round" fill="none" />
            </svg>
          </button>
        {/if}
        {#if hasTop}<div class="top">{@render top?.()}</div>{/if}
      </div>
    {/if}
    <div class="main">{@render main()}</div>
  </div>
</div>

<style>
  .appshell {
    display: flex;
    align-items: flex-start;
    gap: 1.5rem;
    /* The rail sits outside the page frame's width, so main keeps the app's max_width. */
    max-width: calc(var(--page-max, 1080px) + var(--rail-w) + 1.5rem);
    margin: 0 auto;
  }
  .rail {
    flex: 0 0 var(--rail-w);
    width: var(--rail-w);
    position: sticky;
    top: 1rem;
    max-height: calc(100vh - 2rem);
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 1rem;
  }
  .column {
    flex: 1 1 0;
    min-width: 0;
    max-width: var(--page-max, 1080px);
    display: flex;
    flex-direction: column;
    gap: 1rem;
  }
  .main { min-width: 0; }
  .bar {
    position: sticky;
    top: 0;
    z-index: 5;
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 0.5rem 0;
    background: var(--bg);
    border-bottom: 1px solid var(--outline-soft);
  }
  .top { flex: 1 1 0; min-width: 0; }
  .menu {
    flex: 0 0 auto;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 2.4rem;
    height: 2.4rem;
    padding: 0;
    color: var(--text);
    background: var(--surface);
    border: 1px solid var(--outline);
    border-radius: var(--radius-control, var(--radius-pill));
    cursor: pointer;
  }
  .menu:focus-visible { outline: 2px solid var(--primary); outline-offset: 2px; }

  .appshell.narrow { display: block; max-width: var(--page-max, 1080px); }
  .appshell.narrow .column { max-width: none; }
  .appshell.narrow .rail {
    position: fixed;
    inset: 0 auto 0 0;
    z-index: 30;
    width: min(var(--rail-w), 85vw);
    max-height: none;
    padding: 1rem;
    background: var(--surface);
    box-shadow: var(--shadow);
    transform: translateX(-105%);
    visibility: hidden;
    transition: transform 0.18s ease, visibility 0s linear 0.18s;
  }
  .appshell.narrow .rail.open {
    transform: translateX(0);
    visibility: visible;
    transition: transform 0.18s ease;
  }
  .backdrop {
    position: fixed;
    inset: 0;
    z-index: 20;
    background: color-mix(in srgb, var(--text) 35%, transparent);
  }
  @media (prefers-reduced-motion: reduce) {
    .appshell.narrow .rail, .appshell.narrow .rail.open { transition: none; }
  }
</style>
