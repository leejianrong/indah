# ADR-0020: Image overlay and annotation (boxes, masks, keypoints)

- Status: Proposed
- Date: 2026-09-16
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
