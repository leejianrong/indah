# Changelog

All notable changes to indah are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/) (indah is 0.x, so a minor release may change
behaviour; each such change is listed under "Changed"). The wire protocol has its own
version, `protocol_version`, and it is still **1**: every change below is additive.

Earlier releases (0.1.0 to 0.2.2) are described on the
[GitHub Releases page](https://github.com/leejianrong/indah/releases).

## [Unreleased]

### Fixed

- The Colab notebooks in `examples/colab/` had drifted from the demo sources (ten of fourteen embedded old
  code). They are regenerated, `make colab` rebuilds them, and a fast-layer test now fails whenever a
  committed notebook differs from what the generator produces, or the demo list and the gallery catalog
  disagree (IND-196).

### Changed

- The public gallery's cards now come from one catalog file, `deploy/fly/gallery.toml`, instead of
  `MANIFEST` and `BLURBS` in code. A `listed` entry shows a card that links to an app hosted elsewhere
  (opens with `rel="noopener noreferrer"`, never an iframe). A fast-layer test checks the file: unique
  slugs, https only, plain text, blurb length, and that each thumbnail exists and is small. The
  gallery looks as before (IND-191).

## [0.9.0] - 2026-10-25

The multi-replica release. indah can now run on more than one machine or pod: on Fly the shell tells the proxy
which machine owns the tab, a tab's small state survives a restart or a move through a state store (memory,
SQLite or Redis), and an opt-in `/metrics` endpoint feeds a scraper or an autoscaler. A three-replica test
runs in CI, and the route hint was checked on three real Fly machines. Nothing changes unless you turn it on.
`protocol_version` is still 1.

### Added

- A `/metrics` endpoint (IND-212): `create_app(metrics="a-long-token")` (or `INDAH_METRICS_TOKEN`) mounts
  `GET /metrics` in Prometheus text format, hand-written with no new dependency. Series: open sessions
  and streams, events, handler errors, drain state, forwards and forward failures, and a build-info label.
  It is off by default and gated like the deploy doctor (a bearer token, or `metrics=True` for a principal
  holding the `metrics` permission); everyone else gets a plain 404. `hosting.md` has a scrape example and
  an HPA on open streams. No new public name.
- Restorable sessions (IND-208, ADR-0043 Tier B). `ctx.persist(name, signal)` saves a signal's JSON value
  into a state store, keyed by user and session id, and restores it inside the session factory when the tab's
  session is built again (after a restart, a rollout, an idle session reaped or a move to another replica).
  Options: `version=`, `ttl=`, `max_bytes=`, `validate=`. Writes are coalesced and flushed when the session
  ends. New public names `StateStore`, `MemoryStateStore` (the default) and `SqliteStateStore` (standard
  library, one file), plus `create_app(state_store=, state_namespace=, persist_ttl=, persist_max_bytes=)` and
  `INDAH_STATE_STORE`, `INDAH_STATE_NAMESPACE`, `INDAH_PERSIST_TTL`, `INDAH_PERSIST_MAX_BYTES`. Values must be
  plain JSON; defaults are 16 KB per value, 128 KB per session and 24 hours; a signal shown in an ephemeral
  prop (`SecretReveal`) is never stored and anything stored for it is deleted; a value saved for another
  user is ignored. A store that fails never breaks a tab. A store method may be `async def`. No wire change,
  `protocol_version` stays 1. The deploy doctor shows the store kind. Not yet shared between replicas (a Redis
  store is IND-210) and a store shared over a network file system is not tested.
- A Redis state store (IND-210, ADR-0043). `INDAH_STATE_STORE=redis://host:6379/0` (or `rediss://` for TLS,
  or `redis` with the URL in the new `INDAH_REDIS_URL`) and `create_app(state_store="redis://...")` keep
  `ctx.persist` state in a Redis you provide, so a rebuilt session on another replica finds it. New extra
  `indah[redis]` (`redis>=5`), imported on use: the base install is unchanged, and a missing package says
  how to install it. New public name `indah.redis_store.RedisStateStore`. Expiry is Redis's own; timeouts
  are one second and a Redis that is down makes `ctx.persist` start from defaults and drop writes, with one
  log line a minute. The deploy doctor shows the store kind and, for Redis, `ok` or `unreachable`. The
  hosting guide has the ACL, a Kubernetes Redis and the Fly setup. Not included: a registry and pub/sub.
  `RedisStateStore` is importable from `indah.redis_store` and is not in `indah.__all__`, so it is not imported with `indah`. Previously `redis://` was refused with a message.
- The hosting guide says that `Topic` and `Stream` are per replica (IND-216): run the producer in every
  replica.
- The route hint for several Fly machines (IND-197, ADR-0043). With `INDAH_CLUSTER_SECRET` (or
  `create_app(cluster_secret=)`) set on Fly, `init` carries `route: {hint, node, transport}`; the shell sends
  the machine id as `fly-force-instance-id` and `X-Indah-Route` on every event and upload, and file URLs carry
  `?r=<machine id>`, which a machine that does not hold the session answers with `fly-replay`. A gone machine
  (Fly's `400`, or a `409`) re-opens the stream. `INDAH_ROUTE_HINT` / `route_hint=` is `auto`, `fly` or `off`;
  `auto` is on only on Fly with a cluster secret, and the secret is never taken from `secret=`. Off by default
  elsewhere, additive, `protocol_version` stays 1; an older shell ignores the field. The deploy doctor shows the
  setting, and `deploy/probe/sticky_check.py --follow-route` acts like the shell. Run on a real three-machine
  Fly app: 20 of 20 events and patches with the hint, 2 of 20 without (`docs/spikes/multi-replica-e2e.md`).

### Known limitations

- Live handler state (a running task, a stream in progress) is lost when the machine that owns a tab dies;
  the tab recovers its `ctx.persist` state and carries on (ADR-0043).
- Only Fly has a route hint. On Kubernetes, use cookie affinity on the ingress (verified with Traefik on k3d);
  the in-cluster forwarder (IND-209) is not built.
- `INDAH_CLUSTER_SECRET` only switches the hint on; nothing is signed with it yet, so a secret mismatch between
  replicas is not detected.
- `Topic` and `Stream` are per replica: run the producer in every replica. Rate limits are per process too.
- The Redis store, the Kubernetes and Fly snippets in the hosting guide and the `/metrics` HPA example were
  not run against a real Upstash, cluster or Prometheus. The browser rolling-deploy check was run against a
  simulated Fly, not on Fly.

## [0.8.0] - 2026-10-24

The deployment release, plus live docs. This release makes indah easier to run for real on Fly and on your
own Kubernetes (k3s): a readiness endpoint and a graceful drain, configuration from the environment,
`trusted_proxies` presets, a startup warning for the commonest proxy mistake, an opt-in deploy doctor page and
tested recipes for both. The shell is smaller (Leaflet is now a lazily loaded module, and the page and the
editor are served compressed), the docs gain a Playground and live examples that run in your browser, and
`InfoTip` joins the components. **Read "Upgrading" first:** an event for a session the server does not hold is
now a `409`, not a silent `200`. `protocol_version` is still 1.

### Added

- Deploy recipes (`deploy/recipes/`) and two guides, "Run on Fly" and "Run on Kubernetes". Fly: a
  `fly.toml` for one machine (`/ready` check, `kill_signal = "SIGTERM"`, `INDAH_TRUSTED_PROXIES=fly`) and a
  deploy script. Kubernetes: a kustomize base (readiness and liveness probes, `preStop`, grace period,
  ConfigMap, PodDisruptionBudget) with overlays for Traefik (k3s's default ingress), ingress-nginx and
  plain. They were run on k3s v1.35 with Traefik in k3d and on a throwaway Fly app; with two replicas the
  Traefik cookie kept 20 of 20 events on the tab's pod and without it only 10 of 20 took effect. The guides
  list what was and was not checked: ingress-nginx (retired upstream in March 2026), a Traefik
  `IngressRoute`, and the real visitor address on a real k3s were not tested.
- `deploy/probe/sticky_check.py` takes `--cookies` (act like a browser: send the cookies from the page load
  on the stream and every event) and `--machine-header` (read the answering process from any header).

- The deploy doctor (IND-205): `create_app(doctor="a-long-token")` (or `INDAH_DOCTOR_TOKEN`) mounts
  `GET /_indah/doctor`, a page and `?format=json`, showing what a gateway did to one request and what
  indah made of it: the resolved client next to the real socket peer, the scheme, host and prefix, the
  forwarded headers from a fixed allowlist of names (never cookies or credentials), `trusted_proxies`, the
  node, the process age and request count, the Fly region and machine or pod name, open sessions and
  streams, the drain state, the settings in force (never a secret) and plain-language findings (the default
  Fly mistake among them). `doctor=True` admits a logged-in principal holding the `doctor` permission
  instead. Anyone else gets a plain `404`; ten wrong tokens lock an address out for a minute; the page is
  never cached, sets its own strict Content-Security-Policy and never contains the token. Off by default;
  no wire change and `protocol_version` stays 1. `deploy/probe` now runs on it.
- `create_app(node_header=True)` (or `INDAH_NODE_HEADER=1`) adds `X-Indah-Node: <id>` to every response,
  the event stream's included, so you can see which replica answered (IND-203). The id is `INDAH_NODE`, else
  `FLY_MACHINE_ID`, else `HOSTNAME`, else a random per-process id, and it is opaque: an IP address or an odd
  value becomes a short hash, so the header never carries an internal address. `ctx.conn.node` and
  `app.state.node` hold the id with the header on or off. Off by default; nothing else changes and
  `protocol_version` stays 1.
- `trusted_proxies` presets (IND-204): `"fly"`, `"cloudflare"`, `"k8s"` and `"private"` expand to explicit
  lists before the proxy rules see them, compose with plain entries (`["cloudflare", "203.0.113.7"]`)
  and also work in `INDAH_TRUSTED_PROXIES`. `fly` is `172.16.0.0/12` plus the app's public ingress IPs,
  from `INDAH_FLY_IPS` or a DNS lookup of `<FLY_APP_NAME>.fly.dev` at start (it stops with what to run
  if it cannot find them); `cloudflare` is Cloudflare's published ranges, vendored and dated
  (`scripts/refresh_cloudflare_ips.py`, with a test that fails after a year); `k8s` and `private` are
  the private ranges. A preset trusts every address in it. `"auto"`, `"*"` and unknown names are
  refused, and `app.state.trusted_proxies_presets` names the presets in use. Nothing is on by default.
- On Fly, listing only the private range in `trusted_proxies` (so every visitor shares one address and
  one rate-limit bucket) now logs a warning at start naming the missing public IPs and `["fly"]`; the
  forwarded-header warning (IND-200) names the presets and, on Fly, the Fly fix (IND-198).
- Configuration from the environment (IND-202). `create_app` reads `INDAH_SECRET`/`INDAH_SECRETS`,
  `INDAH_TRUSTED_PROXIES`, `INDAH_ALLOWED_ORIGINS`, `INDAH_CSP` (`strict` or `off`), `INDAH_LIMITS`
  (`public` or `none`), `INDAH_DRAIN_SECONDS`, `INDAH_FACTORY_TIMEOUT`, `INDAH_COMPRESS` and
  `INDAH_WARN_UNTRUSTED_FORWARDING` when the matching argument is not passed, so a ConfigMap, a
  Kubernetes Secret or `fly secrets` can configure an app with no code change. An explicit argument always
  wins (even an empty list or `None`), a blank variable counts as unset, a bad value stops the app at start
  with a message that names the variable, `*` is refused for the proxy list, and secret values are never
  logged (one INFO line names the variables used). `app.state.trusted_proxies`, `allowed_origins` and
  `env_used` expose the result. With no variable set nothing changes, and `protocol_version` stays 1. The
  table is in the hosting guide.

- Readiness and a graceful drain for rollouts (IND-201). `GET /ready` answers `200` while the process
  takes new tabs and `503` once it drains (`GET /health` stays the liveness check). On SIGTERM, under
  `launch()` or `uvicorn app:app`, the process stops taking new streams and sessions (`503` with
  `Retry-After`), sends every open stream a `reconnect` message with a spread-out delay, keeps answering
  the sessions it holds, and exits when the last stream has gone or after
  `create_app(drain_seconds=10)`. The shell moves to the next process without an error, retrying while the
  old one still refuses it. `LaunchHandle.drain()` does the same from code, `drain_on_sigterm=False` leaves
  SIGTERM alone, and `await app.state.drain.run()` is the hook for gunicorn, a parent app or anything else.
  With no stream open the drain is over at once, so a quiet process exits as quickly as before. A new
  additive message type and route (`protocol_version` stays 1); an older shell ignores `reconnect` and
  reconnects as for any dropped stream. `hosting.md` has a readiness, `preStop` and Fly `kill_signal`
  recipe. The Fly and Kubernetes settings follow their documentation and have not been run on a real
  cluster; the drain is tested with real processes and a real browser.
- A startup warning for the commonest proxy mistake: when a request carries `X-Forwarded-For`,
  `Forwarded`, `X-Forwarded-Proto`, `Fly-Client-IP` or `CF-Connecting-IP` and `trusted_proxies` is
  empty, indah logs one warning per process naming the header and the socket peer (never a value) and
  sets `app.state.proxy_warning_issued`. `create_app(warn_untrusted_forwarding=False)` silences it for
  an app with no proxy in front, and `launch()` does so in Colab and Runpod. Nothing else changes:
  addresses are still believed only from `trusted_proxies`.

- Compression for what indah serves (ADR-0042, IND-189): the page, `api/editor.js` and the files of a
  module component go out gzipped when the client sends `Accept-Encoding: gzip`, with `Vary:
  Accept-Encoding` and a separate `ETag` per form (`304` still works). The page goes from 581,178 to
  243,716 bytes and `editor.js` from 633,404 to 177,815, so a client behind a proxy that does not
  compress sends a quarter to a third as much. The event stream and JSON routes are never compressed.
  The static pieces of the page are compressed once and the CSP nonce is added around them, so a page
  load costs about 1 ms more rather than 35. `create_app(compress=False)` turns it off. No wire change
  (`protocol_version` stays 1).

- Optional extras (ADR-0042): `pip install "indah[plot]"` (matplotlib), `"indah[data]"` (pandas,
  numpy), `"indah[all]"` (both) and `"indah[demos]"` (the libraries the gallery demos and examples
  use). indah duck-types these libraries, so none is required and the base install is unchanged
  (four direct dependencies); an extra documents a tested version floor. A `DataFrame` or `Table`
  given something it cannot read now says to use a pandas frame (`indah[data]`), a dict or a list
  of row dicts.
- A size budget in CI (ADR-0042): `docs/size-budget.json` limits the wheel, the shell, `editor.js`,
  the direct dependencies and the base install, and the build job fails when one goes over. `make size`
  runs it locally.

- The docs have a **Playground** (`playground.md`): edit an indah app and run it in your own browser with
  Pyodide, with no install and no server (ADR-0041). Write `def build()` returning a component, the same
  contract as the Studio's local playground, so snippets move between them. Nothing loads until you press
  Run (about 9 MB compressed the first time), a run starts in about 4 seconds once cached, your code is sent
  nowhere, an endless loop is stopped after 5 seconds (and Stop works at any time), and a syntax error or
  an exception is shown under the editor as a traceback from your own lines. It starts from the Studio
  playground's examples and the quickstart. With JavaScript off the editor and the examples still read. The
  page lists what cannot work without a server. The Studio's own playground still runs only on your
  machine. Docs only: `src/indah` does not change.

- `InfoTip(text, label=)`: a small focusable info icon that shows a short note (the design's "i" beside a
  label). It opens on hover and keyboard focus, a click or tap pins it open, and Escape, blur or a press
  outside closes it; Escape closes only the note, so a modal behind it stays open. It is one tab stop, a
  real button named by `label` and described by the note (`aria-describedby`, `role="tooltip"`), the note
  stays inside the screen at 390px, and `text` may be a `Signal`, `Computed` or function. A render spec can
  name it (`{"component": "infotip", "bind": {"text": ...}}`) for a `List` item or a table cell. A new
  component type and spec component, so `protocol_version` stays 1 and nothing existing changes.

### Changed

- The size budget (`docs/size-budget.json`) now sits about 15 percent above today's numbers instead of far
  above them, and also covers the sdist, `editor.js` and `map.js` raw size and the Python source size
  (`make size`, the CI `build` job summary). Raising a limit is still a reviewed change (IND-215).

- `editor.js` (the lazily loaded code editor) is minified like `map.js`: 633,404 to 409,775 bytes raw and
  177,816 to 134,243 gzip (-35% raw, -24% gzip). The editor behaves the same; the wheel is 17 KB smaller and the
  docs' Pyodide bundle carries the smaller file (IND-214).

- Leaflet moved out of the shell into a lazily loaded module (ADR-0042, IND-186). The shell shrinks from
  581,046 to 428,605 bytes (243,354 to 199,839 gzip, 18 percent), so every page without a map loads
  about 44 KB less compressed. A page with a `Map` makes one more request, `api/map.js?v=<hash>` (about
  43 KB compressed, cached for good because the URL carries the file's hash), the first time a map
  appears; on a throttled slow-4G profile that cost 0.2 s on a map page and saved 0.9 s on a page
  without one. A map looks and behaves as before (screenshots at desktop and phone width are identical
  in light and dark). If the module cannot load, the map area says so and the rest of the page
  works. No Python API and no wire change, so `protocol_version` stays 1.
- An event or an upload for a session the process does not hold is now `409` with
  `{"ok": false, "error": "unknown_session"}` and creates nothing (IND-199). It used to build a new,
  empty session and answer `200`, so after a restart, an eviction or a misrouted click (two
  processes, no affinity) the click silently did nothing. The shell opens its stream again for a
  fresh page and shows one toast, "Reconnected. Your last action was not applied, please try it
  again.", at most once every few seconds. Secure apps keep their `401` and `403` first, and an app
  built on one shared `Session` is unchanged. A new status on an existing route, so
  `protocol_version` stays 1. The stream is what makes a session: a script or a test that posts
  events directly must open `api/stream` with the same `sid` first (see Upgrading).
- The source distribution (sdist) no longer carries `examples/` or the gallery thumbnails: it drops from
  6.5 MB to 1.5 MB. The wheel (what `pip install` uses) is unchanged. Tests that read `examples/` are
  skipped when you run the suite from an sdist; clone the repository to run all of them.

- The docs show a live example next to each documented component: 73 `<indah-live>` embeds across the
  components, dashboard, quickstart, chatbot, custom components, design system and hosting pages. Nothing
  downloads until a reader presses **Run it**, and one example runs at a time; the 10 pages that need a
  server show their source and say why they cannot run. A new `unembedded_pages()` check (a warning in
  `tests/unit/test_docs_embeds.py`, or `scripts/export_studio_pages.py --unembedded`) names any runnable
  Studio page with a docs target that no docs page embeds. No library change.

- Hosting guide: what Fly sends to an app (measured, IND-170) and the `trusted_proxies` value that
  works there (the private range plus the app's own public IPs; the private range alone resolves every
  visitor to the app's address), and what sticky sessions need (IND-171: a stray event to the wrong
  process builds a new session and is silently lost; indah finds a session by `sid`, not a cookie or
  header, so gateway cookie affinity has nothing to key on). Docs only.

### Fixed

- Docs: the summary line of a live example now shows `code` spans as code instead of with literal
  backticks (the page's source and the rest of the summary stay escaped).

### Known limitations

- Run one indah process per app on Fly: a gateway that cannot set its own cookie cannot pin a tab to a machine,
  and indah does not yet route an event to the machine that holds the session (ADR-0043, proposed).
  Cookie affinity at a Traefik ingress was measured on k3d (20 of 20 events); ingress-nginx and a Traefik
  `IngressRoute` were not run.
- `trusted_proxies` is verified on the direct Fly path only. The Cloudflare Worker hop (IND-170), IPv6 clients
  and a real k3s cluster's visitor address are not yet measured.
- A `Topic` or `Stream` reaches only the tabs on the process that produced it (IND-216).
- `Marked` does not draw inside a `Diff` pane. A `Menu` and a module component cannot sit in a table cell.
- The live docs examples have been tried in Chromium only; Safari, Firefox and phones are not checked.

### Upgrading

- **Events need a stream first.** `POST api/event` and `POST api/upload` for a `sid` the server
  does not hold now answer `409` instead of creating a session. A browser always opens the stream
  first, so nothing changes there. A script or an in-process test that posts events directly must
  first open `GET api/stream?sid=<sid>` (and let go: the session stays) or create the session
  through the store; see `tests/integration/conftest.py` for a test fixture that does it.
- **Compression is on by default.** The page, `api/editor.js`, `api/map.js` and module files are gzipped for
  clients that ask. `create_app(compress=False)` (or `INDAH_COMPRESS=0`) turns it off. The event stream is
  never compressed.
- **SIGTERM now drains.** With open tabs, a SIGTERM keeps serving them for up to `drain_seconds` (10 by
  default) and tells them to reconnect, instead of dropping them at once. With no open stream the process
  still exits straight away. On Fly set `kill_signal = "SIGTERM"` (its default is SIGINT, which does not
  drain), and give Kubernetes a `terminationGracePeriodSeconds` longer than the drain.

## [0.7.0] - 2026-10-24

More building blocks, and the start of live docs. This release adds the last of the dashboard pieces as
built-ins (`CommandPalette`, `Marked`, `BarStrip`, `Steps`), and the machinery that lets the docs site run
Studio pages in the reader's browser with Pyodide. Everything is new API: nothing existing changes, and
`protocol_version` is still 1.

### Added

- The docs can run Studio pages in the reader's browser (ADR-0041): `<indah-live page="...">` shows a page's
  source and a **Run it** button that starts a Pyodide worker running the real indah `Session`, with no
  server. Nothing loads until the button is pressed. Built by `make docs`; see `docs/STUDIO.md`. No change
  to the library.
- `BarStrip(series, height=, tones=, names=, labels=, max=, label=)`: a small activity strip with one
  bar per interval (calls per minute, hits and misses stacked), for a dashboard header rather than a
  chart. `series` is a list, `Signal`, `Computed` or function; a bar is a number or a tuple of segment
  values. It updates in place (the bars are not remounted) and takes its tones from the theme. A tooltip
  names each bar and its segments ("12:03: 4 (hit 3, miss 1)"), the strip is one tab stop whose arrow keys,
  Home and End read each bar, and a live region says the same, so colour is not the only cue. It
  respects reduced motion and works under `csp="strict"`. A new component type (`barstrip`), so
  `protocol_version` stays 1 and nothing existing changes.
- `Steps(items, orientation=, size=)` and `steps_items(items)`: a timeline of steps (a pipeline, a checklist, the
  tiers a request went through), vertical or horizontal. A step is `done`, `current`, `skipped`, `off` or
  `pending`, each with its own drawing (a check, a ring with a dot, a barred ring, a dashed ring, an empty
  ring) as well as its theme colour, a skipped label is struck through, and a screen reader hears "step 2 of 5,
  done" with the step's `detail`. The current step is `aria-current="step"`. Display only, so not a tab stop.
  `size="compact"` is one tight line with the detail as hover text. `items` may be a `Signal`, `Computed` or
  function and updates in place. A render spec may name it, `{"component": "steps", "bind": {"items": "tiers"}}`,
  so a `List` item or a table cell (a `Stream`-fed table too) can draw it from a `steps_items` field; there it is
  compact and horizontal unless `orientation` or `size` are bound too (ADR-0016 amendment). A new component type
  and a new spec component (additive, `protocol_version` stays 1); nothing existing changes.
- `Marked(text, marks)` and `marked_runs(text, marks)`: text with shaded spans, for the part of a request
  that was ignored when matching or the words a check flagged. A mark is `(start, end, tone)` or
  `(start, end, tone, label)`; offsets are Unicode code points, a range is clamped, an empty one dropped,
  and an overlap is cut to begin where the earlier mark ends, so the same input always draws the same
  runs. The tones are the theme's (`ok`, `warn`, `err`, `info`, `neutral`), each with its own underline as
  well as its colour, and the label is hover text. The spans are real elements that add no characters, so
  copying gives back the plain text. A render spec may now name a built-in leaf component,
  `{"component": "marked", "bind": {"runs": "runs"}}`, so a `List` item or a table cell can show it from a
  `marked_runs` field (ADR-0016 amendment). A new component type and an optional spec field (additive,
  `protocol_version` stays 1); nothing existing changes.
- `CommandPalette(commands, shortcut="mod+k")` and `Command(label, on_run | to=, group=, shortcut=, keywords=,
  confirm=, key=)`: the dashboard driven like a terminal. Ctrl or Cmd+K opens a dialog; type to filter, arrows
  move, Enter runs, Escape closes and gives focus back. A command runs a function (sync or `async`) or jumps
  to an in-app page (`to=`, with `CommandPalette(..., ctx=ctx)`), and may ask to `confirm`. The filter runs in
  the browser in a fixed order: label prefix, then a word prefix, a substring, a subsequence (`gl` finds
  "Go to log"), then keywords and group, ties in the order given. `commands` may be a `Signal`, `Computed`
  or function, so a page adds its own commands while it shows. It follows the key-routing rule of ADR-0030:
  never opens over another dialog, ignores a bare key typed in a field, and the shortcut is listed in the `?`
  help. To omit a command for someone who may not use it, build the list with `ctx.only` and wrap the handler
  in `guard`. A new component type (`commandpalette`, event `run`), so `protocol_version` stays 1 and nothing
  existing changes.

### Known limitations

- `trusted_proxies` has still not been checked against the real Cloudflare and Fly path (IND-170), and
  sticky sessions are unverified (IND-171).
- `Marked` does not draw inside a `Diff` pane (the `Diff` draws its own changes); show it beside one.
- A `Menu` and a module component cannot sit in a table cell: a cell spec is display only.
- The live docs examples load Pyodide on demand (about 9 MB compressed) and have been tried in Chromium
  only, with a self-hosted runtime; the jsDelivr path, Safari, Firefox and phones are not yet checked.

## [0.6.0] - 2026-10-23

Tables, text and small controls. This release makes plain `Text` look like normal body text, adds
rich table cells and keyboard navigation, an async session factory with a `Skeleton`, a `Menu`, an
empty state, a copyable code block, toast actions, `ctx.every` and `ctx.spawn`, and a title and
favicon the server can change. **Read "Upgrading" first: plain `Text` now looks smaller in every app.**
`protocol_version` is still 1; every wire change is additive.

### Added

- `Menu(trigger, items)` and `MenuItem(label, on_click, danger=, shortcut=, confirm=, disabled=, key=)`: a menu
  button that follows the ARIA menu pattern. It opens on click, Enter, Space or the arrow keys; Up and Down
  move and wrap, Home and End jump, a letter jumps to the next item that starts with it, Escape closes and
  returns focus to the trigger, and Tab closes and moves on (no keyboard trap). `confirm=` asks first like
  `Button`, `danger` uses the theme's error tone, a `disabled` item is shown but cannot be chosen, and
  `shortcut=` is display text only. `items` may be a `Signal`, `Computed` or function, so the menu follows
  the data; a click is matched to the current items by id, so a stale one does nothing. To omit an item for
  someone who may not use it, build the list with `ctx.only` and wrap the handler in `guard`. A new component
  type (`menu`, event `select`), so `protocol_version` stays 1 and nothing existing changes.
- In an `AppShell` on a narrow screen, a button that only opens something (it has `aria-haspopup`, like a
  `Menu` trigger) no longer closes the drawer; choosing a link or an ordinary button still does.

- `ctx.title` and `ctx.favicon`: set the tab's title and icon from the server, with no reload, for an
  attention cue like "(2) semula" with a red dot. Icons are registered with
  `create_app(favicons={name: path-or-bytes})` (PNG, SVG, ICO, JPEG or WebP, up to 64 KB, at most 16) and
  served by the app (`GET api/brand/favicon/<name>`), so they work under `csp="strict"`. `None` puts the
  app's own back. A change reaches that session only; a reload or a reconnect keeps it, and a new session
  starts with the defaults. A new `chrome` message and an optional `chrome` key on `init` (additive,
  `protocol_version` stays 1); apps that do not use them are unchanged.
- `Empty(title, body, action=, children=)` and `Code(text, language=, copy=True)`. `Empty` is a centred
  empty state (the one command that fills a log, with a button); `Code` is a read-only monospace block
  that keeps newlines and indentation, with a Copy button that puts the plain text on the clipboard and
  shows a "Copied" toast in that tab (no server round trip). Where the browser blocks the clipboard the
  text is selected and the toast asks for Ctrl+C. Both are new component types (additive,
  `protocol_version` stays 1) and nothing existing changes.
- Table keyboard navigation: `Table(on_open=fn)` (or `keyboard=True`) makes a rich or remote table one
  tab stop (`role=grid`) that `j`/`k` and the arrows, `Home`/`End`, `PageUp`/`PageDown`, Space (ticks a
  `checked=` row) and Enter drive; Enter calls `fn(key)` (sync or `async`), or selects like a click
  when there is no `on_open`. The active row is held by key, so streamed rows, sorting and `follow=` do
  not move it, it scrolls into view under the sticky header (also in a 20,000-row `virtual` table), and
  an arrow past the end of a paged or remote table turns the page. A focused table takes its keys first
  and `Shortcuts` yields; modifier combos and typing in an input are never the table's; Tab and Escape
  leave. Off by default, so no existing table changes. New optional props `keyboard` and `openable`
  and an `open` event (additive, `protocol_version` stays 1). The key-routing rule is in ADR-0030.
- Async session factory (IND-153, ADR-0025 amendment): `session_factory` may be `async def`. It is awaited
  for up to `create_app(factory_timeout=1.0)` seconds, so its data is in the first snapshot (no dash,
  then the number). A slower factory lets the tab start on `factory_placeholder()` (a `Skeleton` by
  default) and the real page replaces it on the same stream when the factory finishes; a factory that
  raises shows the error and the next connection retries, and closing the tab cancels it. Sync factories are
  unchanged. A custom `SessionStore` may add `aget_or_create`; one without it is untouched.
- `Skeleton(lines=3, height=)`: grey placeholder bars that pulse (not for a viewer who prefers reduced
  motion). A new component type (additive; a second `init` mid-stream is documented in
  `docs/protocol.md`, `protocol_version` stays 1).


- `ctx.toast(message, action=("Undo", fn), ttl=)`: a toast with a button. Clicking it runs `fn` once
  (a plain function or `async def`, checked by `guard()` at the click) and dismisses the toast. It goes to
  this tab only; a second click or a stale toast does nothing. The pending handlers are held per session
  and bounded. The toast message gains an optional `action` and the click posts the reserved target
  `__toast__` (additive, `protocol_version` stays 1; a toast without `action` is unchanged).

- `ctx.every(seconds, fn, immediately=False)` and `ctx.spawn(coro)`: background work for the life of a
  session. `every` calls a plain or `async` function on a timer; both are cancelled when the session
  ends (discard, eviction, idle reaping), and an exception is logged once and does not stop the loop.
  It replaces a hand-rolled task cancelled from `on_close`. No wire change.
- Rich table cells and truncation (IND-148): `Col(kind="cell", render=<spec>, sort_key=)` draws a
  composite cell (a meter, a two-line caller, a tier rail) from the row's fields, using the same spec
  vocabulary and tag allowlist as a `List` item; it is display only. The spec travels once in the
  column, so a `Stream`-fed table sends nothing extra per row. A cell column sorts and is searched by
  `sort_key`. `Col(truncate=True, max_width=)` clips a long text value with an ellipsis and a tooltip,
  and `wrap=True` wraps it (refused with `virtual=True`). All optional and off by default, so a table
  that does not use them is unchanged, and virtual scroll is as fast as before (additive,
  `protocol_version` stays 1).

### Changed

- **Plain `Text` is now body text** (ADR-0040, IND-166). It was a 1.4rem semi-bold readout, so every
  label and status line looked like a title. The default is now 0.95rem regular text with line breaks
  kept. `Text(source, variant=)` picks a role: `body` (default), `title`, `label`, `caption`, `mono`
  and `readout`, the old large look. `size="body"` and `size="readout"` from 0.4.0 still work. A text
  that is `markdown=True` is unchanged and takes no `variant`. The wire format only gains an optional
  `variant` prop (absent means body), so `protocol_version` stays 1.

### Upgrading

- **Plain `Text` looks smaller.** If a `Text` shows a number or a figure (a counter, a metric, a KPI),
  add `variant="readout"` to get the old look back. Search your code for `Text(` whose source is a
  count or a short value. A `Text` used as a heading can use `variant="title"`.

### Known limitations

- `trusted_proxies` has still not been checked against the real Cloudflare and Fly path (IND-170), and
  sticky sessions are unverified (IND-171).
- A `Menu` and a module component cannot sit in a table cell: a cell spec is display only.
- `factory_timeout` and `factory_placeholder` apply to the built-in session store, not to a `store=` you
  pass.

## [0.5.0] - 2026-10-22

The building blocks of an app screen. This release adds a frame (`AppShell`), the controls and layout
pieces a dashboard header needs, and a way to ship your own element: a module component that the
shell loads as a web component (ADR-0039). Everything is new API; no existing app looks or behaves
differently, and `protocol_version` is still 1.

### Added

- Module components (ADR-0039): `register_component(type, module=, events=, two_way=, fallback=)` ships an
  ES module (a file or bytes, read once; never a URL; up to 1 MB) whose default export is an `HTMLElement`.
  The shell loads it from the app itself (`GET api/components/<type>.js`, content-hashed and cached for good),
  defines it as `indah-x-<type>`, sets the props as properties, forwards the declared CustomEvents to
  `custom(..., on_<event>=handler)` and writes a two-way prop from `detail.value`. A module that fails
  shows its `fallback` text and the page keeps working. It works under `csp="strict"`, `secure=True`,
  `guard()` and the audit hook. A new reserved prop and route, so `protocol_version` stays 1; spec
  components and every default are unchanged.
- Reactive options: `Select`, `Radio`, `MultiSelect`, `Chips` and `Segmented` take `options=` as a
  list, or a `Signal`, `Computed` or callable returning one, and follow it with no reload (a project
  created after the page loads appears in the switcher). A selection whose value is still offered is kept;
  a multi-value control (`MultiSelect`, `Chips(multi=True)`) drops values that are no longer offered, and a
  single-value control leaves its signal alone. A list works exactly as before and stays static on the wire;
  a live source sends `options` as a patch (additive, `protocol_version` stays 1).
- `AppShell(rail=, main=, top=, rail_width=)`: the frame of an app, with a rail that stays put while
  main scrolls, an optional top bar, main keeping `create_app(max_width=)`, and on a narrow screen a
  drawer behind a menu button (Escape, the backdrop or choosing a link closes it). It works inside a
  `Router` page and with `spa=True`. A new component type with optional props, so `protocol_version`
  stays 1 and no existing app changes (ADR-0014 amendment).
- `Chips(value, options=, multi=)` and `Segmented(value, options=, tones=)`: filter chips and a segmented
  control, two-way bound to a signal (a `Signal[str]`, or a `Signal[list]` for `multi=True`). An option may
  be `"a"`, `(value, label)` or `{value, label, count, tone}`; a count shows beside the label and a tone
  (`ok`, `warn`, `err`, `info`) tints it. A single choice is a radio group (arrow keys move and select, with a
  roving tab stop); multi chips are toggle buttons. New component types, nothing existing changes
  (additive, `protocol_version` stays 1).
- `create_app(logo=(light, dark))`: a mark per colour scheme, chosen by indah's own light/dark toggle, so a
  dark mark no longer vanishes on the dark page. A single `logo=` is unchanged (`protocol_version` stays 1).
- `NavItem(ctx, label, to=, badge=, icon=, match=)`: a `Link` for a rail or sidebar with a live count badge
  that hides when it is empty or zero. A new component type (additive, `protocol_version` stays 1).
- Layout primitives: `Row(justify=)` (`start`, `center`, `end`, `between`, `around`), `Column(gap=)`,
  `Spacer` (grows to fill a row, or `size=` for a fixed gap), `Divider` (`vertical=` for a column rule)
  and `Card(variant=, padding=)` with `"outlined"` (the default and the current look), `"flat"` and
  `"tonal"`. A title on the left and actions on the right is now `Row(justify="between")`. Every new
  prop is optional and left off the wire at its default, so an app that does not use them sends and
  looks as before; `spacer` and `divider` are new component types (additive, `protocol_version` stays 1).

### Known limitations

- `trusted_proxies` has still not been checked against the real Cloudflare and Fly path (IND-170), and
  sticky sessions are unverified (IND-171).
- A module component cannot yet sit inside a `List` row or a table cell; that needs the table cell
  spec (IND-148). A module is code that runs in the page with the app's privileges, so register only
  files you wrote or vendored, and never one a user supplies (see ADR-0039).
- A logo pair (`logo=(light, dark)`) takes two images; an SVG that uses `currentColor` does not follow
  the page colour because the logo is shown in an `<img>`.

## [0.4.0] - 2026-10-22

Hosted use. This release adds what an app needs to run for real users behind a login: identity,
signed per-user sessions, roles, one-time secrets, rate limits and a strict Content-Security-Policy,
plus a code editor and a round of small requests from the first dashboard built on indah. Nothing
is on by default: an app that worked on 0.3.0 behaves as before, with two small exceptions listed
under "Upgrading". Start with the new guide, "Host an app for real users", on the docs site.

### Added

**Identity and sessions** (ADR-0033, ADR-0034)

- `Principal` and an `Authenticator` (`create_app(auth=)`): a function from the request to who
  the caller is. `ctx.user` carries it into the session factory, and each session is owned by it.
  With `secure=True` and no `auth=`, Starlette's `scope["user"]` is used.
- `create_app(secure=True)` makes identity a rule on every route that reaches a session: no
  principal is `401`, no session id is `401`, another person's session is `403` (their file
  download `404`), and a refused request creates no session. It needs a per-viewer
  `session_factory` and a `secret` (16 bytes or more; a list rotates).
- Signed session tokens: the shell trades its login for `<sid>.<signature>` with
  `POST api/session`, and a reload keeps its session. The signature covers the principal and the
  workspace, so ids cannot be chosen, replayed or moved.
- An origin guard on a secure app (`allowed_origins=`), so a cross-site form or multipart POST
  is refused before it is parsed. `ctx.sign_out()` ends every tab of a user and shows a
  signed-out page; an open stream also ends when `Principal.expires_at` passes.
- `trusted_proxies=`: `X-Forwarded-For`, `-Proto`, `-Host` and `-Prefix` are believed only from
  the proxies you list (default none; `*` is refused). `ctx.conn.prefix` holds the forwarded
  prefix.
- `audit=` and `audit_payloads=`: a hook called after each UI event and upload with who, which
  component, which event and the payload keys. Values are included only on request, and never
  from a sensitive component.

**Authorization and secrets** (ADR-0035, ADR-0036)

- `Policy` (roles to permissions, with `*` and `prefix:*`), `ctx.can`, `ctx.require`, `ctx.only`
  and `guard(perm)(handler)`. Restricted components are omitted when the tree is built for the
  principal, because hidden components are still in the page. `guard` checks again when the
  event arrives, against the person making that request, so a role revoked mid-session fails the
  next action (`403`, a "not allowed" toast, not audited). `ctx.workspace` exposes the workspace
  a session is bound to.
- `SecretReveal`: shows a new API token once, with Copy and "I have saved it". The value is an
  *ephemeral prop*: sent to the open tab only, never put in the `init` snapshot or the replay
  history, and cleared on dismiss, on a fresh `init` and when the session closes. It is marked
  sensitive for the audit hook. `Component.ephemeral`, `Component.forget()` and
  `Hub.publish(record=False)` are the mechanism.

**Hardening** (ADR-0037, ADR-0038)

- `indah.hardening`: `Limits` (every bound optional; unset means as before), `Rate`,
  `Limits.public()`, and the rate-limit and security-header middleware that used to live in the
  public gallery's deploy code. `create_app(limits=, security_headers=)` adds a per-address,
  per-route token bucket (`429` with `Retry-After`), a cap on open streams per address (`429`),
  event and upload body caps (`413`), session count and idle bounds, and the headers
  `X-Content-Type-Options`, `Referrer-Policy` and `X-Frame-Options`.
- `create_app(csp="strict")`: a Content-Security-Policy with a fresh nonce on the shell's inline
  tags, no inline script or `eval`, same-origin connections only, and a violation report
  collector (`POST api/csp-report`, `app.state.csp_violations`). `csp_media_hosts=` lists extra
  image and audio hosts; a `Map` registers its tile host. Off by default and in `launch()`. The
  whole browser test suite now runs under it and fails on any violation.

**The Studio** (`make demo`)

- `make demo` is now the **indah Studio**: one app with a chapter per area (start, layout, overlays,
  routing, data, live, media, extend, hosting), 53 feature pages that each show a live demo, its
  source and its docs links, 9 full example apps (live log, pending queue, 20,000-row table, routed
  dashboard, editor, hosted roles and tokens, component showcase, themed app, params and deep
  links), and a playground that runs a few lines of indah you type. The per-feature `make demo-*`
  targets and the review server are gone; the full apps are still files in `examples/`.
- A test fails when a public name in `indah.__all__` has no Studio page, and the browser suite opens
  every page (under `csp="strict"`) and fails on console errors, failed requests and CSP violations.
  See `docs/STUDIO.md` to add a page.

**Editor and recipes**

- `CodeEditor`: a JSON, YAML and plain-text editor (CodeMirror 6) with highlighting,
  auto-indent, auto-closing brackets and quotes, bracket matching, folding, search, line
  numbers, JSON lint with the error position, a read-only mode, a Format button that keeps key
  order, a Ctrl/Cmd-S save hook and `{{placeholder}}` highlighting. It loads lazily from
  `GET /api/editor.js` the first time one renders (about 180 KB compressed, only for apps that
  use it), follows the app theme, and falls back to a text area if it cannot load. ADR-0032.
- `examples/oidc_login.py`: a recipe for OpenID Connect login in the parent app with authlib
  (PKCE, state, nonce, full ID-token verification), handing a `Principal` to indah. It fails
  closed on any token that does not verify and is tested against an in-process provider. indah
  itself has no authlib dependency, and there is no `indah[auth]`.
- `make demo-hosted` now shows three roles (viewer, editor, admin), an admin-only API-token
  screen (create with reveal-once, list, revoke with a confirm) and every hardening switch on.

**Small requests from the first dashboard** (ADR-0031 amendment)

- `py.typed`: the package ships type information.
- `create_app(title_suffix=)` sets the page title's suffix (`""` gives the exact title) and
  `create_app(max_width=)` sets the page frame's widest size (`"none"` fills the window).
- `Theme(extra_light=, extra_dark=)`: an app's own `x-<name>` tokens, emitted as `--x-<name>`.
- `Col(time_format="clock" | "datetime")`: absolute times in a table's time column.
- Docs: a synchronous handler runs on the event loop (use `async def` for long work). The wire
  protocol is published in full on the docs site, with a test that keeps the two copies equal.
- `scripts/latency_probe.py` times an event round trip against a deployed app. On the public
  gallery from Singapore, indah adds a few milliseconds, a hop to Fly about 16 ms, and the
  Cloudflare path 100 to 200 ms per interaction, which is why checks run in the process rather
  than calling an outside service per event.

### Changed

- A link in `Text(markdown=True)` that points within the site (`/path`, `#anchor`, `./x`, `../x`)
  now opens in the same tab; links to other sites (`http(s)`, `mailto`) still open in a new tab.
- `POST /api/event` requires `Content-Type: application/json` (`415` otherwise, before the body
  is read), so a cross-site "simple" request cannot reach the handler.
- An event with no session id is `400`, unless the app is one explicit shared `Session`
  (`create_app(session=)`). Nothing falls back to a shared `default` session any more.
- The public gallery no longer trusts a client-supplied `X-Forwarded-For` for rate limiting; it
  uses Fly's `Fly-Client-IP`, else the socket peer. Its three routes now have a bucket each
  rather than sharing one. In core, the client address is the socket peer, or the forwarded
  address from a trusted proxy.
- `authlib`, `itsdangerous` and `cryptography` joined the `dev` extra for the recipe's test.
  They are not dependencies of indah.

### Fixed

- `MultiSelect` is now a list of checkboxes (a labelled group, operable with the keyboard)
  instead of a native `<select multiple>`. The wire format and events are unchanged, so
  `protocol_version` stays 1.
- `Text(size="body")`: plain `Text` is a large readout by design, which made status lines and
  notes look like headings. `size="body"` renders normal body text with newlines kept; the
  default is unchanged. It is an additive optional prop (`protocol_version` stays 1). Plain text
  still shows backticks literally: use `markdown=True` for markup.
- `UploadedFile.text()` takes `errors=` (`"strict"` by default, as before), so a file that is not
  clean UTF-8 can be read with `"replace"` or `"ignore"` instead of raising.
- The "only one Router per session" error now explains the limit and what to do instead.
- A custom component's nested `on` now round-trips. `register_component` built its event map from
  the top-level spec only, so an `input` inside a `children` tree changed nothing on the server.
- A render spec takes `"literal"` for fixed text, so a `List` row button reads `"Remove"` without a
  `"Remove"` field on every item (`text` still names a prop or item field). The spec field is
  additive and `protocol_version` stays 1.
- `Row(align=...)` is honoured for buttons and badges: with any `align` other than the default
  `"stretch"` they size to their content instead of growing to share the row (a Badge beside two
  Buttons no longer stretches). The default row is unchanged.
- `Theme(radius=)` now reaches buttons and badges, which were always pill-shaped. They use a new
  `--radius-control` token that defaults to `--radius-pill`, so apps without a theme look as before.

### Known limitations

- A session can have only one `Router`, because the address bar is one path per tab. A second
  one raises an error that says so and what to use instead (`Tabs`, or a `Signal`); a Router
  cannot be demonstrated inside a page of another routed app. Nested routers are not planned.
- Sessions are in memory. With more than one process, use sticky sessions at the gateway. There
  is no external session store.
- `trusted_proxies` is tested with simulated headers; it has not yet been checked against the
  real Cloudflare and Fly path.
- A role revoked mid-session stops actions at once, but components already sent stay on screen
  until the session is rebuilt; a role added shows its components after a rebuild.
- A `Map` with a custom tile host built after the first page load is allowed under a strict CSP
  from the next load. Declare it with `csp_media_hosts=` to avoid that.
- Limits are per process; several replicas multiply them.

### Upgrading from 0.3.x

No code changes are needed unless your code or a script posts events by hand:

1. `POST /api/event` must send `Content-Type: application/json`. Anything else is now `415`.
2. A `POST /api/event` with no `sid` is now `400` for an app built with `session_factory=` (the
   shell always sends one). An app built with `session=` still accepts it. Tests that post
   events directly should pass a `sid`, and open the stream with the same `?sid=`.
3. If you copied the gallery's rate-limit or security-header middleware, import
   `RateLimitMiddleware` and `SecurityHeadersMiddleware` from `indah.hardening` instead.

Two things look different without any code change: `MultiSelect` is now a list of checkboxes
(same value, same events), and an app that sets `Theme(radius=)` now gets that radius on its
buttons and badges too (they were always pill-shaped). Neither changes the wire protocol.

To host an app for real users, follow "Host an app for real users" on the docs site. The new
options (`auth`, `secure`, `limits`, `security_headers`, `csp`, `trusted_proxies`, `audit`, `policy`)
are all off or unset by default.

## [0.3.0] - 2026-10-21

Dashboard support. This release adds what an app needs when indah lives inside a larger
service: live push to every tab, big tables, overlays, routing, editors and a documented
design system. Start with the new guide, "Build a dashboard", on the docs site.

### Added

- **Mounting.** The shell works under any mount prefix (a relative `<base href>`), and
  `create_app(spa=True)` serves the shell for deep links such as `/ui/projects/auth`.
- **`Context`.** A session factory may take a `Context`: `ctx.toast`, `ctx.path`,
  `ctx.params`, `ctx.navigate`, `ctx.latest`, `ctx.tail` and `ctx.on_close`.
- **Live push.** `Topic` (app-level channel), `Stream` (append-only, bounded list, sent as
  small `append` patches with a `trim`), and the 100 ms append coalescer.
- **Theming.** `Theme(light=, dark=, radius=, font=)`, a custom `logo=`, and
  `create_app(density="comfortable" | "compact")`. New tokens `on-primary-container` and
  `on-secondary-container`.
- **Design system.** A published "Design system" page and ADR-0031 record the token
  contract; a unit test keeps the shell, `Theme` and the page in step.
- **Table v2.** Keyed rows, typed columns (`Col`: text, mono, badge, time, number), a sticky
  header, `Stream` rows, client-side search, column toggle and follow-tail, row actions
  (`RowAction`), multi-select (`checked=`), `density=`, a remote mode (`remote=` with a
  `TableQuery` loader, `reload_on=`, `query=`) and virtual scroll (`virtual=`), tested with
  20,000 rows. On a remote table, "N of M selected" and **Select all M** gather every
  matching row (up to 10,000).
- **Overlays and feedback.** `Modal`, `Drawer`, `Button(confirm=)`, toasts, `Badge`,
  `Switch`, a `tooltip=` prop on every component, and `Shortcuts` with a `?` help overlay.
- **Inputs.** `TextArea`, with the same typing-safe behaviour as the other inputs.
- **Panes and routing.** `SplitPane`, `MasterDetail`, `Router`, `Link` (with active state),
  route params as signals, and `not_found`.
- **Viewers.** `JsonTree` (search, collapse, copy path) and a server-side `Diff` (split or
  unified, with word-level highlights).
- **Editable lists.** `List(key=, on_item=)`: keyed rows, row events carrying the row key,
  and in-row inputs that keep focus and text while updates arrive.
- **Demos.** `make demo-review` serves every semula demo behind one index page; the single
  demos are `make demo-semula`, `demo-pending`, `demo-entries`, `demo-routes` and
  `demo-editor`.

### Changed

- `POST /api/event` bodies are capped (`create_app(max_event_bytes=)`, default 1 MiB); a
  larger one is rejected with `413`. A text area holding a very large document may need a
  higher cap.
- A rich `Table` now draws row separators only (no vertical cell lines), and its sticky
  header is opaque with a drawn bottom edge. Search boxes are rounded like other inputs.
- The tonal button and the info badge take their text colour from the new `on-*-container`
  roles, so it shifts slightly.
- The default Bunga logo no longer follows an app theme's `primary`; it keeps its brand
  colours. Use `logo=` for your own mark.
- Tooltips open at the pointer (on keyboard focus: under the control), flip above near the
  bottom edge and stay inside the window.

### Fixed

- After a server restart, an open tab is sent a fresh `init` instead of staying on a stale
  tree, and it reopens on the page it is on now rather than the one it started on.
- `LaunchHandle.stop()` now ends the server even while a browser tab holds an SSE stream
  open.

### Known limitations

- Every `Router` page runs its reactive code even when it is not showing, with empty
  params. Read params with `ctx.params.value.get(...)`, never `[...]`. Do not put
  role-restricted content in a page: hidden pages are in the snapshot.
- `Table(follow=True)` is not available with `remote=` and raises `ValueError`.
- A keyed `List` takes a signal or a callable, not a `Stream`.
- `Modal` has no position option, and `Button` has no disabled state.
- indah keeps sessions in memory and does not authenticate users. Authentication,
  authorization and rate limiting belong in the app that mounts it.

### Upgrading from 0.2.x

No code changes are required for an app that worked on 0.2.2. Check three things:

1. If you POST very large values (for example a big `TextArea`), raise
   `max_event_bytes`.
2. If you override colours with CSS of your own, check the tonal button and the info badge.
3. If you use `Theme`, you may now set `on-primary-container` and `on-secondary-container`;
   set them whenever you override the matching `*-container` role.

[0.4.0]: https://github.com/leejianrong/indah/releases/tag/v0.4.0
[0.3.0]: https://github.com/leejianrong/indah/releases/tag/v0.3.0
