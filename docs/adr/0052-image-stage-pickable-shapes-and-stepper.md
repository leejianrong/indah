# ADR-0052: Shapes in raster pixels, picking and a cropped view on ImageOverlay; a Steps stepper

- Status: **Accepted** 2026-11-16
- Date: 2026-11-16
- Deciders: Jian (owner)
- Builds on: ADR-0020 (`ImageOverlay`), IND-163 (`Steps`)
- Driven by: geo-pipeline's Inspector, which draws a tile grid over a large raster, lets the user pick
  a tile to see its raw detections, and shows a close-up of a tile seam.

## Decision

Additive, no `protocol_version` bump (ADR-0005). No new component: both changes extend one that exists.

1. **`ImageOverlay(size=(w, h), shapes=..., selected=..., view=..., on_pick=...)`.** `size` is the
   picture's pixel size. `shapes` are rectangles (`box`) and polygons (`points`) in those pixels, with
   `stroke`, `width`, `dash`, `fill`, `opacity`, a hover `label` and `pick`. They are drawn in one SVG
   whose `viewBox` is the raster, stretched over the image, so they line up at any size and zoom;
   strokes do not scale (`vector-effect`). A shape with `pick` is a keyboard-reachable button; clicking
   it sends `pick {id}` and `on_pick(id)` runs, but only for an id that is a current pickable shape.
   `selected` draws one shape thicker. `view=[x, y, w, h]` shows only that region at full width (zoom and
   pan are off while a view is set). Layers are the caller's: pass the list without the hidden ones.
2. **`Steps(on_select=fn)`** makes the timeline a stepper: each step is a button, left and right (or up
   and down) move to the next enabled step and choose it, an `off` step is disabled, and `fn(index)`
   runs for a valid index only. Without `on_select` nothing changes.
3. The existing fraction-based `boxes`, `points` and `masks` are unchanged.

## Not done

A tiled image source for rasters too big for one picture, wheel-zoom of shapes beyond the existing zoom
of the whole layer, and a magnifier inset (`view` on a second `ImageOverlay` does the same job).

## Cost

About 4.5 KB of Python source and 5 KB of shell; `python_source_bytes` is raised from 612,000 to
630,000 in `docs/size-budget.json`.
