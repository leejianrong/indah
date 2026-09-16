# Hosting the indah demos on Fly.io

The persistent "try-it-now" gallery (ADR-0023, the self-hosted path). We host on
**Fly.io** rather than Hugging Face Spaces because HF now requires a **PRO**
subscription to run Docker Spaces on free CPU (static Spaces are the only free tier,
and indah is a server) - deploying to HF returns `402 Payment Required`. Fly runs the
exact same Docker image, one app per demo, with machines that **auto-stop when idle**
(so idle demos cost ~nothing).

The Colab one-click badges (the other tier) remain the free, zero-host baseline.

## What's here

- `deploy_fly.sh` - deploys each demo to a Fly app, reusing the Docker build folders
  from `../spaces/build/<slug>/` (the same `Dockerfile` that would have gone to HF).
  It writes a `fly.toml` into each build folder and `fly deploy`s it.

## Deploy (owner step - needs a Fly account)

```bash
# 1) Install flyctl and sign in (once):
curl -L https://fly.io/install.sh | sh      # or: brew install flyctl
fly auth login                               # or: fly auth signup

# 2) Build the Docker folders, then deploy:
cd deploy/spaces && ./build_space.sh
cd ../fly && ./deploy_fly.sh                  # all demos
./deploy_fly.sh poster                        # ...or one, by slug
```

Each demo goes live at `https://indah-demo-<slug>.fly.dev`. Fly app names are
**global**, so if one is taken set a different prefix: `FLY_PREFIX=indah-jian ./deploy_fly.sh`
(pick your own region with `FLY_REGION=...`, default `sin`).

Then add each URL to the gallery (`website/docs/gallery.md`) next to the demo's
"Open in Colab" badge.

## Notes

- Machines are configured `auto_stop_machines = "stop"` + `min_machines_running = 0`,
  so an idle demo scales to zero; the first hit after idle pays a short cold start
  (fine for demos).
- The image installs indah from `git+https://github.com/leejianrong/indah@main`; pin
  it to a release once indah is on PyPI (edit `INDAH_REQ` in `../spaces/build_space.sh`).
- `deploy/spaces/deploy_hf.py` (the HF path) is kept for anyone with HF PRO; Fly is
  the default free-tier host.
