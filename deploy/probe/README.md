# The proxy probe (IND-170, IND-171)

A throwaway Fly app, `indah-probe`, that shows what a gateway did to a request. It is not the
gallery and nothing in it touches `indah-demos`. Results are in
[`docs/spikes/proxy-and-sticky.md`](../../docs/spikes/proxy-and-sticky.md).

| File | What |
|------|------|
| `probe_app.py` | the app: `GET /` (a page with a "Send an event" button) and `GET /whoami` (flat JSON), both built on indah's deploy doctor (`indah.doctor`, IND-205); `INDAH_TRUSTED_PROXIES` sets `trusted_proxies` (`PROBE_TRUSTED_PROXIES` is kept as an alias); set `INDAH_DOCTOR_TOKEN` to also get the full doctor page at `/_indah/doctor` |
| `deploy.sh`, `set-trusted.sh`, `teardown.sh` | deploy a new app, change `trusted_proxies` without a rebuild, delete it |
| `sticky_check.py` | does a tab's stream and its events reach one machine? |
| `cloudflare-worker.js` | a pass-through Worker for the Cloudflare step below |

## What the owner does for IND-170 (the Cloudflare half)

Production reaches the gallery as browser, then Cloudflare, then the Worker `indah-proxy`, then
Fly. This check builds the same kind of path to the probe on a different hostname, so production is
never touched. **You do not need an API token, and you do not change `indah-proxy` or its route.**
All of it is clicks and one paste in the Cloudflare dashboard. About 10 minutes.

The Fly side is already deployed: `https://indah-probe.fly.dev/whoami` answers (check it first).

1. **DNS.** Cloudflare dashboard, the `abangai.dev` zone, DNS, Add record: type `CNAME`, name
   `probe`, target `indah-probe.fly.dev`, **Proxy status: Proxied** (orange cloud), Save. If it
   is grey, the Worker is bypassed and the check means nothing.
2. **The Worker.** Workers and Pages, Create, Create Worker, name it `indah-probe-proxy`, Deploy the
   Hello World template, then Edit code, replace everything with the contents of
   `deploy/probe/cloudflare-worker.js`, and Deploy.
3. **The route.** Open the Worker, Settings, Domains and Routes, Add, Route: `probe.abangai.dev/*`,
   zone `abangai.dev`, Save.
4. **Check it.** Open `https://probe.abangai.dev/whoami`. You should see JSON with
   `"machine"` and a `headers` object. It can take a minute for the DNS record to appear.
5. **From your phone, on mobile data (not your home Wi-Fi):** open
   `https://probe.abangai.dev/whoami` and send the agent the value of `fly-client-ip`, `cf-connecting-ip`
   and `x-forwarded-for`, and your phone's public address (any "what is my IP" page). The agent
   compares them with what indah resolved.
6. **Tell the agent "done".** It then runs the measurements through the Worker from this machine
   and writes the result.
7. **Afterwards, clean up:** delete the route, the Worker `indah-probe-proxy` and the `probe` DNS
   record in the dashboard, then run `deploy/probe/teardown.sh` (or tell the agent to).

The probe's `/whoami` and the doctor show only these request headers: `fly-client-ip`, `x-forwarded-*`, `forwarded`,
`via`, `cf-connecting-ip`, `cf-ray`, `cf-ipcountry`, `cf-visitor`, `true-client-ip`, `host` and
`user-agent`. It never shows cookies or credentials. Anyone who knows the address can open it, and
it shows them their own request.

## Notes

- `uvicorn` runs with `--no-proxy-headers` so only indah's own rules are under test.
- `deploy.sh` and `set-trusted.sh` use `fly secrets set` only as the quickest way to restart with
  an environment variable. The value is not a secret.
- `deploy.sh` builds a wheel of this checkout (needs `uv`) and the image installs it, because the doctor is newer than the last PyPI release. After the release that includes it you can pin the version instead.
