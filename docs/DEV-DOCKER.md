# Running the demo in Docker (with Traefik)

This is a **dev convenience**, not how indah is meant to be used. indah itself is
`pip install indah` then `launch()` — no container, no Node. This page is for when
you want the demo to answer at a stable `http://indah.localhost/` instead of a
host port that shifts when other local apps are running.

## Quick standalone (no Traefik)

```bash
make demo-docker          # docker compose up --build
# -> http://localhost:8000  (set INDAH_HOST_PORT=8600 etc. if 8000 is taken)
```

`docker-compose.yml` works on its own and is what CI and a fresh clone get. It
publishes the container's port 8000 directly on the host.

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
cp docker-compose.override.yml.example docker-compose.override.yml   # gitignored
make demo-docker
# -> http://indah.localhost/     (in a browser)
```

The override adds the Traefik route on top; the direct host port stays published,
so both `http://indah.localhost/` and `http://localhost:8000` work at once.

### Notes

- **`*.localhost` in a browser** resolves to loopback automatically. From a shell
  it does not — use `curl --resolve indah.localhost:80:127.0.0.1 http://indah.localhost/`.
- **No HMR middleware needed.** indah streams updates over Server-Sent Events
  (plain HTTP), not a websocket with a strict Host check, so the Vite-style
  Host-rewrite workaround does not apply here.
- This does not solve multiple *worktrees of indah* colliding on host ports; that
  is a separate concern (per-worktree port reassignment).
