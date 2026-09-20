# Fronting indah.abangai.dev with a Cloudflare Worker

`indah.abangai.dev` needs to serve two independent things from one hostname: the Fly
demo gallery (`deploy/fly/`) at `/`, and the separately-built Zensical docs
(`website/`, published to GitHub Pages) at `/docs`. DNS can only route a whole
hostname to one origin, so a small Worker sits in front and splits by path instead.
See ADR-0024's 2026-09-21 update for why this is a Worker rather than a plain proxied
CNAME.

## What's here

- `indah-proxy-worker.js` — the Worker script. `/docs` and `/docs/*` fetch from
  `leejianrong.github.io/indah/...` (indah's GitHub Pages URL — a project site, so it's
  served under an `/indah/` prefix); everything else fetches from
  `indah-demos.fly.dev`.

## Current live setup (owner's Cloudflare account)

- DNS: `indah.abangai.dev` is a **proxied** (orange-cloud) CNAME to
  `indah-demos.fly.dev`, in the `abangai.dev` zone. It must stay proxied — an
  unproxied ("DNS only") record would bypass the Worker entirely and hit Fly
  directly, serving only the gallery with no `/docs` route.
- Worker: deployed under the script name `indah-proxy`.
- Route: `indah.abangai.dev/*` → `indah-proxy`.
- TLS: Cloudflare's Universal SSL terminates for visitors — **no Fly custom-domain
  cert is used or needed here** (`fly certs add` was tried and removed; it can't
  validate against a proxied record, and it isn't necessary since the Worker's
  `fetch()` reaches Fly at its own already-valid `indah-demos.fly.dev` hostname).

## Redeploying the Worker after an edit

Requires a Cloudflare API token scoped to this zone (`Zone > DNS > Edit` isn't
needed here; `Account > Workers Scripts > Edit` is):

```bash
ACCOUNT_ID="b9afad40d36de93680355f0d66998a12"   # Leejianrong2@gmail.com's Account
SCRIPT_NAME="indah-proxy"

echo '{"main_module":"indah-proxy-worker.js","compatibility_date":"2024-09-23"}' > /tmp/worker-metadata.json
curl -X PUT "https://api.cloudflare.com/client/v4/accounts/$ACCOUNT_ID/workers/scripts/$SCRIPT_NAME" \
  -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
  -F "metadata=@/tmp/worker-metadata.json;type=application/json" \
  -F "indah-proxy-worker.js=@indah-proxy-worker.js;type=application/javascript+module"
```

The route (`indah.abangai.dev/*` → `indah-proxy`) only needs to be created once; it
doesn't change when the script is redeployed.

## Known gaps (see ADR-0024)

- **Origin-IP hiding.** `indah-demos.fly.dev` and the app's bare Fly IP are still
  directly reachable, bypassing this Worker and Cloudflare's edge entirely. Fixing
  this needs a Cloudflare Tunnel (`cloudflared`) in front of the Fly app instead of a
  plain proxied DNS record, or an app-level check that requests carry a shared
  Cloudflare secret header.
- **Bot Fight Mode and an edge rate-limiting rule** — recommended in
  `deploy/fly/README.md`, not yet turned on.
