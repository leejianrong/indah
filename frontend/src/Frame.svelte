<script>
  // Frame (ADR-0046): a fixed design-size stage scaled to fit. Children are laid out once
  // inside a width x height box and the box is scaled uniformly, centred, so the layout is
  // identical at any window size.
  //   contain (default)  fit the width its parent gives and the height left in the window
  //                      below the frame's own top edge: a page that never scrolls
  //   shrink             as contain, but never scaled up
  //   width              fit the parent's width only; the height follows the aspect ratio
  // `kiosk` covers the whole window, above indah's own header, for screen recording.
  let { props, children } = $props();
  let host = $state();
  let scale = $state(1);
  let boxHeight = $state(0);

  const width = $derived(props.width ?? 1920);
  const height = $derived(props.height ?? 1080);

  function fit() {
    if (!host) return;
    const availW = props.kiosk ? window.innerWidth : host.clientWidth;
    if (!availW) return;
    if (props.fit === "width" && !props.kiosk) {
      scale = availW / width;
      boxHeight = Math.round(height * scale);
      return;
    }
    const top = props.kiosk ? 0 : host.getBoundingClientRect().top + window.scrollY;
    // Leave the page's own bottom padding, or the page scrolls by exactly that much.
    const below = parseFloat(getComputedStyle(document.body).paddingBottom) || 0;
    const availH = Math.max(120, window.innerHeight - top - below);
    const s = Math.min(availW / width, availH / height);
    scale = props.fit === "shrink" ? Math.min(s, 1) : s;
    boxHeight = Math.floor(availH);
  }

  $effect(() => {
    void width;
    void height;
    void props.kiosk;
    void props.fit;
    fit();
    window.addEventListener("resize", fit);
    const ro = typeof ResizeObserver !== "undefined" && host ? new ResizeObserver(fit) : null;
    if (ro && !props.kiosk) ro.observe(host);
    return () => {
      window.removeEventListener("resize", fit);
      ro?.disconnect();
    };
  });
</script>

<div
  class="frame-viewport"
  class:kiosk={props.kiosk}
  bind:this={host}
  style={props.kiosk ? undefined : `height: ${boxHeight}px`}
>
  <div
    class="frame-stage"
    style="width: {width}px; height: {height}px; transform: translate(-50%, -50%) scale({scale});
      grid-template-columns: {props.tracks ?? '1fr'};{props.rows
      ? ` grid-template-rows: ${props.rows};`
      : ''} gap: {props.gap ?? '1rem'}; padding: {props.padding ?? '1.25rem'};"
  >
    {@render children?.()}
  </div>
</div>
