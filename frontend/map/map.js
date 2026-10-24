// The map is its own ES module (ADR-0042), fetched lazily by the shell on the first `map` render,
// so an app without a map does not download Leaflet. The Leaflet CSS stays in the shell (it is
// small, and a <style> element injected from here would need the CSP nonce). Output:
// dist-map/map.js (copied to src/indah/static/).
//
// Markers/polygons/polylines are Leaflet vector layers (circleMarker/polygon/polyline), not the
// classic pin icon, which needs image assets Leaflet ships as separate files. polylines is an
// *open* path (not auto-closed, not filled), the right shape for a real route or track.
import L from "leaflet";

/** Mount a Leaflet map in `el`. Returns a small controller; the shell owns the lifecycle. */
export function createMap(el, { center, zoom, tileUrl, attribution }) {
  const map = L.map(el);
  map.setView(center ?? [0, 0], zoom ?? 2);
  L.tileLayer(tileUrl, { attribution, maxZoom: 19 }).addTo(map);
  const layers = L.layerGroup().addTo(map);
  el.__map = map; // debugging / e2e introspection

  function draw({ markers, polygons, polylines }) {
    layers.clearLayers();
    for (const m of markers ?? []) {
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
    for (const p of polygons ?? []) {
      const poly = L.polygon(p.points ?? [], {
        color: p.color ?? "#2e6d62",
        weight: 2,
        fillOpacity: p.fillOpacity ?? 0.25,
      });
      if (p.label) poly.bindTooltip(String(p.label));
      poly.addTo(layers);
    }
    for (const l of polylines ?? []) {
      const line = L.polyline(l.points ?? [], {
        color: l.color ?? "#2e6d62",
        weight: l.weight ?? 3,
      });
      if (l.label) line.bindTooltip(String(l.label));
      line.addTo(layers);
    }
  }

  return {
    draw,
    // Python re-centring or re-zooming flies the existing map there; an unset half keeps the
    // user's own pan or zoom.
    setView(c, z) {
      map.setView(c ?? map.getCenter(), z ?? map.getZoom());
    },
    invalidateSize() {
      map.invalidateSize();
    },
    destroy() {
      map.remove();
      el.__map = null;
    },
  };
}
