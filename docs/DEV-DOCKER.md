# Running the demo in Docker (with Traefik)

This is a **dev convenience**, not how indah is meant to be used. indah itself is
`pip install indah` then `launch()` — no container, no Node. This page is for when
you want the demo to answer at a stable `http://indah.localhost/` instead of a
host port that shifts when other local apps are running.

## Quick standalone (no Traefik)

```bash
make demo-docker          # prints the URL it picked, e.g. http://localhost:54961/
```

`make demo-docker` picks a **free host port automatically** (so it never collides
with another local app already on 8000) and runs the base `docker-compose.yml`
only, so it needs no Traefik. `docker-compose.yml` is also what CI and a fresh
clone get; run it directly with `INDAH_HOST_PORT=<port> docker compose up --build`
to choose the port yourself.

## Stable hostname via a machine-wide Traefik proxy

One Traefik instance serves every local project on the machine; a project opts in
with labels in its own compose file. Set the proxy up once:

```bash
mkdir -p ~/dev-proxy && cd ~/dev-proxy
# copy the dev-proxy compose (see below), then:
docker compose up -d
```

`~/dev-proxy/docker-compose.yml` (uses `traefik:v3.7` — do not pin an older minor;
Docker Engine 29.x rejects Traefik v3.5's version negotiation):

```yaml
services:
  traefik:
    image: traefik:v3.7
    restart: unless-stopped
    command:
      - --providers.docker=true
      - --providers.docker.exposedbydefault=false
      - --providers.docker.network=proxy
      - --entrypoints.web.address=:80
    ports:
      - "80:80"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    networks:
      - proxy
networks:
  proxy:
    name: proxy
```

Then, in this repo, opt the demo in:

```bash
make demo-traefik
# -> http://indah.localhost/     (in a browser)
```

`make demo-traefik` checks the `proxy` network exists, copies
`docker-compose.override.yml.example` to `docker-compose.override.yml` (gitignored)
if you haven't, picks a free host port for the direct publish, and brings the
stack up. Both `http://indah.localhost/` (via Traefik) and the printed
`http://localhost:<port>/` work at once.

### Notes

- **`*.localhost` in a browser** resolves to loopback automatically. From a shell
  it does not — use `curl --resolve indah.localhost:80:127.0.0.1 http://indah.localhost/`.
- **No HMR middleware needed.** indah streams updates over Server-Sent Events
  (plain HTTP), not a websocket with a strict Host check, so the Vite-style
  Host-rewrite workaround does not apply here.
- This does not solve multiple *worktrees of indah* colliding on host ports; that
  is a separate concern (per-worktree port reassignment).
