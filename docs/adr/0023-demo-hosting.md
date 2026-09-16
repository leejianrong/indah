# ADR-0023: Demo hosting - Colab one-click + Hugging Face Spaces

- Status: Accepted
- Date: 2026-09-16
- Deciders: Jian (owner)

## Context

The dogfooding demos (EPIC-217/218) are only half the showcase; a visitor from the
landing page has to be able to *try one in one click*, the way Streamlit's gallery
and Gradio's Spaces let you. indah has no hosting story yet. The `POSITIONING.md`
go-to-market section laid out the options; this ADR records the choice.

Constraints that matter: indah is a **server** (single-port ASGI over SSE + POST), so
an in-browser WASM gallery (Shinylive/Panel-style) is out without a large rewrite.
The wheel is pure-Python with no Node, so any host just needs Python + `pip install`.

## Decision

Two tiers, both shipped.

1. **"Open in Colab" on every demo (the free, on-brand baseline).** Each demo gets a
   thin notebook (`examples/*_colab.ipynb`) that `pip install`s indah and the demo's
   own extra deps, then runs the example; an "Open in Colab" badge on the gallery and
   README opens it straight from GitHub. This *is* the pitch - indah spins up in a
   throwaway Colab and prints a URL - and it costs nothing to host. It ships
   regardless of the persistent host.

2. **A persistent hosted gallery on Hugging Face Spaces (Docker Space per demo).**
   For "already running, nothing to do", each demo is a Docker Space: a small
   Dockerfile on `python:3.12-slim` that `pip install`s indah + the demo deps and
   runs the example's ASGI `app` under uvicorn on the Space's port. This gives every
   demo a persistent URL the landing/gallery links to, on the free tier, and plants
   indah on the same turf as Gradio/Streamlit demos. HF Spaces support a plain Docker
   app (not only Gradio/Streamlit SDKs), so indah's ASGI app runs directly.

The Space Dockerfile and a deploy script live in the repo (`deploy/spaces/`); the
actual push to Hugging Face needs the owner's HF account/token and is a manual/owner
step (no secrets in the repo, ADR/AGENTS rule).

## Alternatives considered

| Option | Why not |
|--------|---------|
| Self-hosted gallery (Fly.io / a VPS / Runpod) | One indah "gallery app" behind one domain would dogfood per-session state nicely, but it carries ongoing cost + ops we don't need yet; revisit if HF Spaces' limits (sleep on idle, resource caps) become a problem |
| Colab-only, no persistent host | Loses the "click and it's already running" experience the landing page needs to compete with Streamlit/Gradio galleries |
| In-browser WASM (Shinylive/Panel-style) | indah is a server (SSE + POST); running fully client-side is a large rewrite with no near-term payoff. Parked |
| Streamlit Community Cloud / Gradio Spaces SDK | Those SDKs host *their* frameworks; indah rides HF Spaces as a generic **Docker** app instead |

## Consequences

- Every demo is tryable two ways: one-click into the visitor's own Colab (free,
  on-brand) and a persistent HF Space (always-on, no install).
- The repo gains per-demo Colab notebooks and a `deploy/spaces/` Docker recipe +
  deploy script; the final HF push is an owner step (needs HF credentials).
- HF Spaces free tier sleeps on idle (cold start on first hit) and caps resources -
  fine for demos; the self-hosted option stays open if we outgrow it.
- The landing page and gallery (EPIC-220) link to both the Colab badge and the Space
  URL for each demo.
