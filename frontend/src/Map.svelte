<script>
  // Client-side interactive map (Leaflet, G5). Leaflet is bundled into the shell at
  // build time (a devDependency of frontend/, inlined by the singlefile build) --
  // it is NOT a Python runtime dep and adds no Node at install or runtime. Tiles
  // load live from the configured tile server, in the *viewer's* browser (not
  // indah's server) -- the same as any Leaflet map on any website.
  //
  // Markers/polygons/polylines are Leaflet vector layers (circleMarker/polygon/
  // polyline), not the classic pin icon, which needs image assets Leaflet ships as
  // separate files -- incompatible with the no-external-requests singlefile build
  // (ADR-0004). polylines is an *open* path (not auto-closed, not filled) -- the
  // right shape for a real route/track, where polygons' auto-closing segment back
  // to the start point would visibly cut across the map.
  import L from "leaflet";
  import "leaflet/dist/leaflet.css";
  import { untrack } from "svelte";

  let { props } = $props();
  let el = $state();
  let map = null;
  let layers = null; // a LayerGroup holding the current markers/polygons

  function drawLayers() {
    if (!layers) return;
    layers.clearLayers();
    for (const m of props.markers ?? []) {
      const marker = L.circleMarker([m.lat, m.lon], {
        radius: m.radius ?? 8,
        color: m.color ?? "#b5296b",
        weight: 2,
        fillColor: m.color ?? "#b5296b",
        fillOpacity: 0.85,
      });
      if (m.label) marker.bindTooltip(String(m.label));
      marker.addTo(layers);
    }
    for (const p of props.polygons ?? []) {
      const poly = L.polygon(p.points ?? [], {
        color: p.color ?? "#2e6d62",
        weight: 2,
        fillOpacity: p.fillOpacity ?? 0.25,
      });
      if (p.label) poly.bindTooltip(String(p.label));
      poly.addTo(layers);
    }
    for (const l of props.polylines ?? []) {
      const line = L.polyline(l.points ?? [], {
        color: l.color ?? "#2e6d62",
        weight: l.weight ?? 3,
      });
      if (l.label) line.bindTooltip(String(l.label));
      line.addTo(layers);
    }
  }

  function build() {
    destroy();
    if (!el) return;
    map = L.map(el);
    map.setView(props.center ?? [0, 0], props.zoom ?? 2);
    L.tileLayer(props.tileUrl, { attribution: props.attribution, maxZoom: 19 }).addTo(map);
    layers = L.layerGroup().addTo(map);
    el.__map = map; // debugging / e2e introspection
    drawLayers();
  }

  function destroy() {
    if (map) {
      map.remove();
      map = null;
      layers = null;
    }
    if (el) el.__map = null;
  }

  // Rebuild only on the tile source / height (structural); everything else updates
  // the existing map instance so the user's own pan/zoom is never reset by an
  // unrelated data update.
  $effect(() => {
    void props.tileUrl;
    void props.attribution;
    void props.height;
    void el;
    untrack(build);
    return destroy;
  });

  // Python explicitly recentring/re-zooming (e.g. "fly to" a new place) flies the
  // existing map there, rather than resetting the user's own pan/zoom on every
  // unrelated prop update -- this effect only reruns when center/zoom actually change.
  $effect(() => {
    const center = props.center;
    const zoom = props.zoom;
    if (map) untrack(() => map.setView(center ?? map.getCenter(), zoom ?? map.getZoom()));
  });

  $effect(() => {
    void props.markers;
    void props.polygons;
    void props.polylines;
    if (map) untrack(drawLayers);
  });

  $effect(() => {
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => {
      if (map) map.invalidateSize();
    });
    ro.observe(el);
    return () => ro.disconnect();
  });
</script>

<div class="map" bind:this={el} style="height: {props.height ?? 320}px"></div>
