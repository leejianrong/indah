# ADR-0020: Image overlay and annotation (boxes, masks, keypoints)

- Status: Accepted (steps 1 and 2 built)
- Date: 2026-09-16 (accepted + step-1 built same day, KAN-1464)
- Deciders: Jian (owner)

## Context

The vision demos in the Phase 2 catalogue — object detection, segmentation, video
detection stepped frame-by-frame — all need to draw over an image: bounding boxes
with labels, mask polygons/alpha overlays, keypoints. Today `Image` renders a bare
`<img>`; a demo can only bake overlays into the pixels server-side (a fresh PNG per
frame), which is heavy and non-interactive. This is the cluster-E gap
("annotation / canvas") from `PLAN.md`, split into two capabilities of different cost.

## Decision

Add overlays in **two steps**, so the common case ships cheaply and the interactive
case is a clean follow-up.

1. **Read-only overlay (build first).** An `Image` (or a new `ImageOverlay`) that
   takes, as reactive props, a list of shapes to draw over the image: boxes
   `{x, y, w, h, label?, color?}` (normalised coords), masks (RLE / polygon / an
   overlay `data:` PNG with alpha), and keypoints. The shell draws them on a canvas
   layered over the image. Shapes ride ordinary props, so streaming detections is a
   prop update over the existing `patch` op — **no `protocol_version` bump**. This
   unblocks detection, segmentation, and video frame-stepping (the model produces the
   boxes; the shell just draws them).
2. **Interactive annotation (second step).** Let the user *draw* boxes / click points
   on the image and round-trip them to Python as an event (drag → `annotate` event
   with the new shape). This needs a pointer→event path but still no new patch op.
   Gated behind step 1 and demand from an annotation demo.

Both are Tier 0 (SSE + POST): shapes are small JSON on props/events, not continuous
binary, so this is unrelated to the Tier 1 live-video boundary (ADR-0017).

## Alternatives considered

| Option | Why not |
|--------|---------|
| Bake overlays into a server PNG per frame | Heavy (a full image each update), non-interactive, and loses crisp vector labels; the same weight argument as ADR-0018 |
| Express overlays via the custom-component render spec (ADR-0012) | The spec is deliberately loop/condition-free and cannot draw a variable list of shapes on a canvas; overlays are a first-class shell component, like charts |
| Jump straight to full interactive annotation | Most demos only need to *display* model output; the read-only overlay covers detection/segmentation/video at a fraction of the work |

## Consequences

- Detection/segmentation/video demos become practical without a PNG-per-frame; boxes
  and masks stream as prop updates (composes with the KAN-1395 coalescing).
- The shell gains a canvas overlay renderer; the Python package stays pure-Python.
- A new overlay component type + prop schema (shape shapes, coord convention) are
  documented in `docs/protocol.md`, additive within `protocol_version` 1.
- Step 2 (interactive annotation) is recorded as the follow-on that finally closes the
  cluster-E "interactive canvas annotation" boundary, when a demo needs authoring.

## As built (step 1, KAN-1464, 2026-09-16)

- **`ImageOverlay`** (`components.py`): a base image `source` (like `Image`) plus
  reactive `boxes` / `points` / `masks`, coordinates as fractions in `[0, 1]`.
  Streaming a model's per-frame output replaces the `boxes` prop over the existing
  `patch` op - no `protocol_version` bump.
- **Renderer** (`Node.svelte`): a `position: relative` wrapper over the `<img>` with
  boxes/points as absolutely-positioned HTML elements at percent offsets, and masks as
  overlay images with opacity. Percent positioning (not a canvas) keeps labels crisp
  and scales with the responsive image, no aspect-ratio math.
- **Step 2 (interactive annotation) remains deferred** - this is the read-only display
  path that unblocks the detection / segmentation / video demos.
- `imageoverlay` in `BUILTIN_TYPES`; documented in `docs/protocol.md`; guarded by unit
  tests + a browser e2e (boxes render at fractional positions, a streamed detection
  appears live).

## As built (step 2, IND-71)

- **`ImageOverlay(draw=, on_draw=)`**: `draw` is `"box"`, `"point"` or `None` (a value or a Signal) and
  needs `size`, because a drawn shape is in raster pixels like `shapes` (ADR-0052). A drag sends a
  `draw` event `{kind: "box", box}`, a click `{kind: "point", point}`; Python clamps into the picture,
  orders the corners, drops a drag under 2 px and ignores an event that does not match the current
  mode, then calls `on_draw(shape)`.
- **No list in indah.** The app keeps what was drawn and shows it back through `shapes` (a new
  `point` shape draws a dot), so undo, delete, relabel and export are plain Python. A drawn shape never
  appears by itself.
- **No new op, no version bump**: one new event name on an existing component and one new shape key.
- Pointer only: a drag has no keyboard form, so an app that needs one offers number inputs beside it.
