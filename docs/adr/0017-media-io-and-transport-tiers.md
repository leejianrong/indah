# ADR-0017: Media I/O and transport tiers

- Status: Proposed
- Date: 2026-09-15
- Deciders: Jian (owner)

## Context

The single most common Gradio/Streamlit ML-demo shape is "upload an image / audio /
file → run → show the result", and indah has no upload input at all, nor a way to
hand the user a file back. This is the highest-value gap for the Colab-researcher
north star (Slice D).

The transport is SSE (server→client) + small JSON POSTs (client→server), chosen
because Colab's proxy passes it and blocks WebSockets (ADR-0002). That is a poor fit
for binary/media: a file base64'd into a JSON event bloats the payload and blocks the
event path. And the owner wants a path, later, to **live video / real-time detection
for users outside Colab** — which SSE+POST cannot carry — without breaking the Colab
invariant.

## Decision

Two parts.

**Media I/O (built now).** Add a dedicated multipart upload endpoint, separate from
`POST /api/event`, and an `Upload` component (image / audio / file). Uploaded bytes
are handed to a plain handler the caller supplies (ADR-0009), and results flow back
over the existing SSE channel. Add download / file-out (a served blob URL). Upload is
a new HTTP route, not a change to the SSE message format, so it is additive to the
protocol — documented in `docs/protocol.md`, and likely **no `protocol_version`
bump** (confirm when built).

**Transport tiers (declared now, mostly built later).**

- **Tier 0 — SSE + POST.** The Colab-compatible floor; the only tier Colab's proxy
  supports. Everything indah ships runs here. Upload/record-*snapshot*
  (single frames, recorded audio) fits Tier 0.
- **Tier 1 — an optional streaming upgrade** (WebSocket, as ADR-0002 already
  envisioned, probed at connect). Carries continuous, high-frequency binary — live
  webcam, real-time detection — and is enabled **only where the environment supports
  it** (non-Colab deployments). Continuous live media is scoped to Tier 1 and is
  **not built now**; declaring the tier keeps the door open without weakening Tier 0.

So the boundary is explicit: **upload-and-process now on Tier 0; live video/real-time
later on Tier 1**, never at the cost of Colab compatibility.

## Alternatives considered

| Option | Why not |
|--------|---------|
| Base64 a file into `POST /api/event` | Bloats the JSON event, strains the reactive path, and caps file size; a multipart route is the right tool |
| Make WebSocket the primary transport | Breaks Colab (ADR-0002); the whole architecture rests on not doing this |
| Ship no media I/O | Fails the core ML-demo use case the north star is about |
| Build live video now | Needs Tier 1 (or client-side inference) and real hardware to prove; premature before upload even exists |

## Consequences

- Unblocks image/audio/file demos (classification, ASR, diffusion-in/out) — the
  classic Gradio app, now in indah.
- Needs per-session isolation (ADR-0010) so each viewer's upload is theirs, so this
  slice sequences **after** per-session state (Slice C).
- Records the real-time boundary as a decision, not a default: non-Colab live media
  has a home (Tier 1) that does not compromise the Colab floor.
- Upload size limits, allowed types, and temp-file lifecycle are defined when built;
  the dev-tool threat model (Q-sec) still applies — the app author owns what the
  handler does with the bytes.
