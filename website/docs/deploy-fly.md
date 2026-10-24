# Run on Fly

One indah app on one Fly machine, with the settings that matter already in place. The files are in
`deploy/recipes/fly/` in the repository; this page says why each setting is there, and what was
checked.

## Deploy

```bash
fly auth login
INDAH_DOCTOR_TOKEN="$(openssl rand -hex 24)" deploy/recipes/fly/deploy.sh my-indah-app sin
```

`deploy.sh` creates the app if needed, stores the doctor token as a Fly secret (so it is never in the
file), and deploys **one** machine. To deploy your own app, copy `deploy/recipes/app/`, put your code
in `app.py`, and keep the Dockerfile.

## The settings

```toml
kill_signal = "SIGTERM"        # Fly's default is SIGINT, which indah does not drain on
kill_timeout = 15              # more than INDAH_DRAIN_SECONDS

[env]
  INDAH_TRUSTED_PROXIES = "fly"   # the private range plus this app's public IPs
  INDAH_NODE_HEADER = "1"         # X-Indah-Node: which machine answered
  INDAH_DRAIN_SECONDS = "10"

[http_service]
  auto_stop_machines = "off"      # a stopped machine drops every open tab
  min_machines_running = 1

  [[http_service.checks]]
    path = "/ready"
```

- **`trusted_proxies = fly`.** On Fly the peer is a private address and the visitor arrives in
  `X-Forwarded-For` as `<client>, <your app's public IP>`. Trusting only the private range resolves
  every visitor to your app's own address, so everybody shares one rate-limit bucket. The `fly`
  preset trusts the private range plus the app's public IPs, which it looks up from
  `<app>.fly.dev` when the app starts. Restart the app after you add an IP.
- **Check `/ready`, not `/health`.** `/ready` turns 503 while the app drains, so Fly stops sending it
  new tabs.
- **One machine.** A tab's state lives in one process, and Fly Proxy routes every request on its own
  with no cookie affinity. With two machines a click can land on a machine that does not hold the tab:
  indah answers it with a 409 (seen on Kubernetes; not re-measured on Fly) and the tab reconnects, but the click is lost. Read
  [Sticky sessions](hosting.md#sessions-and-tokens) before you scale out.

## Rolling out

`fly deploy` stops the old machine with the configured signal. indah drains: it stops taking new tabs,
tells open ones to reconnect, and exits when the last stream is gone or after `INDAH_DRAIN_SECONDS`. If
you restart a machine by hand, pass the signal, because `fly machine restart` defaults to SIGINT:

```bash
fly machine restart <machine-id> --signal SIGTERM
```

## The deploy doctor

With `INDAH_DOCTOR_TOKEN` set, `https://my-indah-app.fly.dev/_indah/doctor` shows what indah sees:
the resolved client, the socket peer, the forwarded headers, the node and the drain state.

```bash
curl -H "Authorization: Bearer $INDAH_DOCTOR_TOKEN" "https://my-indah-app.fly.dev/_indah/doctor?format=json"
```

Without the token it answers 404.

## What was checked

On a throwaway Fly app on 2026-10-24 (one machine, region `sin`, indah built from the repository
checkout, since the settings above are newer than the 0.7.0 release):

| Check | Result |
|-------|--------|
| `fly.toml` accepted, `/ready` check passes | yes |
| `/ready` and `/health` | 200 and 200 |
| `X-Indah-Node` | the machine id |
| Doctor without the token | 404 |
| `fly` preset | `172.16.0.0/12` plus the app's IPv4 and IPv6 ingress addresses |
| Client address resolved by indah | the real public address (checked against `curl api.ipify.org`) |
| `fly machine restart` (default signal) | SIGINT: no drain, the tab got `reconnect` only after the 15 s kill timeout |
| `fly machine restart --signal SIGTERM` | the tab got `reconnect` about 2 s later |
| `fly deploy` (the configured SIGTERM) | the tab got `reconnect` as the old machine was stopped |

Not checked: two machines (see [Sticky sessions](hosting.md#sessions-and-tokens) and the measurements
in `docs/spikes/proxy-and-sticky.md`), IPv6 visitors, and a Cloudflare Worker in front of the app.
