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

## Front the gallery with Cloudflare (optional, owner step - ADR-0024)

The gallery is public and unauthenticated, so it's worth putting a free edge layer in
front of it once there's a domain to do it with. `indah-demos.fly.dev` is a Fly-owned
subdomain, not ours to add to Cloudflare directly - this needs a domain the owner
controls in Cloudflare's DNS first. Once one exists:

1. Add the domain to Cloudflare and switch its nameservers to Cloudflare's.
2. Create a `CNAME` (or `A`) record pointing a subdomain (e.g. `demos.yourdomain.com`)
   at `indah-demos.fly.dev`, proxied (orange-cloud on) so traffic routes through
   Cloudflare's edge.
3. In the Cloudflare dashboard: turn on **Bot Fight Mode** (free), and add a
   **rate-limiting rule** on `/*/api/*` (a low per-IP request rate is plenty - the app
   itself also rate-limits, see ADR-0024).
4. Run `fly certs add demos.yourdomain.com` so Fly issues a TLS cert for the new
   hostname, then update the gallery/docs links (`website/docs/gallery.md`,
   `website/docs/index.md`) to the new domain.

**Caveat:** proxying through Cloudflare does not hide the origin by itself - Fly's
machine still has a directly reachable public IP, so `indah-demos.fly.dev` (or the
bare Fly IP) stays reachable even after the custom domain is proxied. Real origin
hiding needs either a Cloudflare Tunnel (`cloudflared`) fronting the app instead of a
plain proxied DNS record, or an app-level check that requests carry a shared
Cloudflare secret header. Neither is built yet (see ADR-0024's deferred list).

## Notes

- `auto_stop_machines = "stop"` + `min_machines_running = 0` scale the machine to
  zero when idle; the first hit after idle pays a short cold start (fine for demos).
- The image installs indah from `git+https://github.com/leejianrong/indah@main`; pin
  to a release once indah is on PyPI (edit `INDAH_REQ` in `build_gallery.sh`).
- The per-demo Hugging Face path (`deploy/spaces/`) is kept for anyone with HF PRO.
- `[http_service.concurrency]` in the generated `fly.toml` bounds simultaneous
  connections on the one machine; `deploy_fly.sh` deploys with `--ha=false` so Fly
  never provisions a second machine under load (ADR-0024).
