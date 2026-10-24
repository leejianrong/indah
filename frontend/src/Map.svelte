<script>
  // Client-side interactive map (Leaflet, G5). Leaflet itself is a separate same-origin module
  // (frontend/map/map.js, built to src/indah/static/map.js and served at api/map.js), fetched
  // the first time a map renders, so an app without a map never downloads it (ADR-0042). It is a
  // devDependency of frontend/ only: not a Python runtime dep, and no Node at install or runtime.
  // Tiles load live from the configured tile server, in the *viewer's* browser (not indah's
  // server) -- the same as any Leaflet map on any website. Only the Leaflet CSS stays in the
  // shell: it is small, and a <style> element injected by the module would need the CSP nonce.
  //
  // Markers/polygons/polylines are Leaflet vector layers, not the classic pin icon (which needs
  // image assets Leaflet ships as separate files -- incompatible with the no-external-requests
  // singlefile build, ADR-0004); see map.js.
  import "leaflet/dist/leaflet.css";
  import { untrack } from "svelte";
  import { apiUrl } from "./api.js";

  let { props } = $props();
  let el = $state();
  let mod = $state.raw(null); // the lazily loaded module, once it has arrived
  let failed = $state(false);
  let ctl = null; // the mounted map controller

  // The URL carries the module's content hash, so a new release is fetched at once and an old
  // one is cached for good.
  $effect(() => {
    if (mod || failed) return;
    import(/* @vite-ignore */ apiUrl(`api/map.js?v=${__MAP_HASH__}`)).then(
      (m) => (mod = m),
      () => (failed = true),
    );
  });

  function build() {
    destroy();
    if (!el || !mod) return;
    ctl = mod.createMap(el, {
      center: props.center,
      zoom: props.zoom,
      tileUrl: props.tileUrl,
      attribution: props.attribution,
    });
    ctl.draw(props);
  }

  function destroy() {
    if (ctl) {
      ctl.destroy();
      ctl = null;
    }
  }

  // Rebuild only on the tile source / height (structural) or when the module arrives;
  // everything else updates the existing map instance so the user's own pan/zoom is never reset
  // by an unrelated data update.
  $effect(() => {
    void props.tileUrl;
    void props.attribution;
    void props.height;
    void el;
    void mod;
    untrack(build);
    return destroy;
  });

  // Python explicitly recentring/re-zooming (e.g. "fly to" a new place) flies the existing map
  // there, rather than resetting the user's own pan/zoom on every unrelated prop update -- this
  // effect only reruns when center/zoom actually change.
  $effect(() => {
    const center = props.center;
    const zoom = props.zoom;
    if (ctl) untrack(() => ctl.setView(center, zoom));
  });

  $effect(() => {
    void props.markers;
    void props.polygons;
    void props.polylines;
    if (ctl) untrack(() => ctl.draw(props));
  });

  $effect(() => {
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => {
      if (ctl) ctl.invalidateSize();
    });
    ro.observe(el);
    return () => ro.disconnect();
  });
</script>

<div class="map" bind:this={el} style="height: {props.height ?? 320}px">
  {#if failed}
    <p class="map-failed" role="status">The map could not be loaded.</p>
  {/if}
</div>

<style>
  .map-failed { margin: 0; padding: 0.75rem; color: var(--muted); font-size: 0.9rem; }
</style>
