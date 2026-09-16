# Hosting the indah demo gallery on Fly.io

The persistent "try-it-now" gallery (ADR-0023, self-hosted path) - **one Fly app**
that serves every demo behind a sub-path. We host on Fly rather than Hugging Face
Spaces because HF now requires a **PRO** subscription for Docker Spaces on free CPU
(deploying to HF returns `402`; only static Spaces are free, and indah is a server).

**One machine, one domain.** `gallery_app.py` mounts each demo's indah app under
`/<slug>` and serves a gallery index at `/`. This works because the indah shell uses
document-relative URLs, so it runs under a base path - the same property that carries
it through Colab's/Runpod's proxies (ADR-0001), pinned by
`tests/integration/test_gallery_mount.py`. The machine auto-stops when idle, so the
gallery costs ~nothing at rest.

The Colab one-click badges remain the free, zero-host baseline.

## What's here

- `gallery_app.py` - the single Starlette app (`build_gallery` mounts the demos;
  `create_gallery` imports the examples and is the uvicorn factory entrypoint).
- `build_gallery.sh` - assembles `build/`: `gallery_app.py` + the demo example files
  + the Dockerfile / requirements / fly.toml.
- `deploy_fly.sh` - builds then `fly deploy`s the one app.
- `build/` - generated output (git-ignored).

## Deploy (owner step - needs a Fly account)

```bash
# 1) Install flyctl and sign in (once):
curl -L https://fly.io/install.sh | sh      # or: brew install flyctl
fly auth login                               # or: fly auth signup

# 2) Deploy the gallery (builds build/ then fly deploy):
cd deploy/fly && ./deploy_fly.sh
```

It goes live at `https://indah-demos.fly.dev`, with the demos at `/chatbot`,
`/training-dashboard`, `/diffusion`, `/poster`, `/image-classify`, `/charts`. Fly app
names are **global**, so if `indah-demos` is taken set your own: `FLY_APP=indah-jian
./deploy_fly.sh` (region via `FLY_REGION=...`, default `sin`).

Then add the URLs to the gallery (`website/docs/gallery.md`) next to each demo's
"Open in Colab" badge.

## Notes

- `auto_stop_machines = "stop"` + `min_machines_running = 0` scale the machine to
  zero when idle; the first hit after idle pays a short cold start (fine for demos).
- The image installs indah from `git+https://github.com/leejianrong/indah@main`; pin
  to a release once indah is on PyPI (edit `INDAH_REQ` in `build_gallery.sh`).
- The per-demo Hugging Face path (`deploy/spaces/`) is kept for anyone with HF PRO.
