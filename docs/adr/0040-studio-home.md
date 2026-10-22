# ADR-0040: Where the Studio lives, and how the docs reuse its pages

- Status: **Proposed** (IND-168; the owner reviews it before IND-169 is built)
- Date: 2026-10-22
- Deciders: Jian (owner)
- Relates to: ADR-0007 (docs site), ADR-0023 and ADR-0024 (demo hosting and hardening),
  ADR-0037 (hardening), ADR-0038 (CSP), `docs/STUDIO.md`

## Context

`make demo` runs the **Studio**: 53 feature pages and 9 full apps, about 4,400 lines under
`examples/studio/`, each page showing a live demo and its own source. It is the best way to try
indah and it is tested (`tests/e2e/test_studio.py` opens every page under `csp="strict"`, and
`tests/unit/test_studio_coverage.py` requires a page for every public name). But it only runs from
a checkout. The docs site (Zensical on GitHub Pages) shows code a reader cannot run, and the public
gallery on Fly shows 13 heavier demos, not the features.

Facts that bound the choice:

- The wheel packages `src/indah` only. The Studio imports `examples.*` (full apps that need extra
  dependencies and data files), so putting it in the wheel would add weight and dependencies for
  every user and tie the wheel to demo code.
- The Studio has a **playground** that `exec`s typed code in the server process. It is offered to
  loopback clients only (`docs/STUDIO.md`). It must never be reachable on a public host.
- The strict CSP sends `frame-ancestors 'self'` and the hardening middleware sends
  `X-Frame-Options: DENY`. A docs page on another origin cannot iframe a Studio page today. That is
  right as a default and has to be relaxed for one route, deliberately.
- The Fly gallery is deployed by hand (`deploy/fly/deploy_fly.sh`) and the Fly and Neon hosting is
  planned to move to a homelab (PAN-130). Anything new must not depend on Fly.
- IND-169 (live docs) can embed a hosted page in an iframe, or run indah in the browser with Pyodide
  (IND-83, an 8 point spike). They differ a lot in cost and risk.

## Decision

**Cheapest path first: keep the examples in the repo, host the Studio as its own container
without the playground, and let the docs embed single pages in iframes. Treat Pyodide as a separate,
optional spike.**

1. **Where the examples live: the repo only.** `examples/studio/` stays where it is. It is not put
   in the wheel and not split into an `indah-studio` package now. It is versioned by the repo tag:
   the hosted Studio for release `X.Y.Z` is built from tag `vX.Y.Z` and installs `indah==X.Y.Z`
   from PyPI (the same exact pin the gallery now uses, IND-167). Revisit a separate package only if
   someone asks to `pip install` the Studio; nothing here blocks it.

2. **A hosted Studio, separate from the gallery.** A second container image, `indah-studio`, runs
   `examples.studio` in a **hosted mode** (`STUDIO_HOSTED=1`):
   - the playground chapter and its routes are not mounted, and a test asserts that no route under
     `/play/` and no chapter `playground` exists in hosted mode (the code-execution risk is removed,
     not guarded);
   - `Limits.public()`, security headers and `csp="strict"` are on, and sessions are bounded like the
     gallery's;
   - any app that needs the owner's machine (local files, a loopback client) is listed as exempt and
     not mounted; the hosted-mode card audits `/apps/` and writes that list;
   - a new `/embed/<chapter>/<page>` route renders one page with no Studio chrome. Only that route
     sends `frame-ancestors` for the docs origin (an allow-list from configuration, never `*`) and
     omits `X-Frame-Options`. Every other route keeps `'self'` and `DENY`.
   The gallery keeps its role, the heavy model and map demos. It is **not** replaced: the Studio
   shows features, the gallery shows applications. The Studio can later take over the gallery's
   landing page if the owner wants one front door.
   Cost: one `shared-cpu-1x`, 1 GB machine that stops when idle, as the gallery does. The image is
   plain Docker with a port and environment variables, so it moves to the homelab (PAN-130) with the
   gallery and carries no Fly-specific code. Fly is only the first target.

3. **How it is tested and versioned.** The existing Studio e2e keeps running in CI on every PR. A
   new post-deploy check runs the same page list against `STUDIO_URL` (as `tests/e2e/test_gallery.py`
   does for the gallery), and `docs/RELEASING.md` gains a step: after a release is on PyPI, build
   the Studio image from the tag, deploy, run the check. A hosted-mode unit test guards the playground
   exclusion, the exempt apps and the embed headers.

4. **How a docs page reuses a Studio page: an iframe of the hosted `/embed/` route.** The docs page
   holds a small, fixed snippet (an iframe plus a link "Open in the Studio") per example. The source
   shown is the Studio page's own source panel inside the embed (it is the build function itself,
   so it cannot drift) and, below it, the same code in the docs' own code block when the page wants
   to explain it. A test reads `website/docs/**` for embed markers and fails if a slug is not in
   `discover()`, so a renamed or deleted Studio page breaks CI instead of the docs. Start with the
   quickstart and the components page, as IND-169 says.

5. **Pyodide is a spike, not the plan.** IND-83 is split: **83a** (IND-176), a 3 point timeboxed spike (does
   `indah` import in Pyodide, how long it boots, how big it is, can a postMessage transport shim
   replace `fetch` and `EventSource`), and **83b**, the real playground (5 points), filed only if the
   spike passes. The iframe route does not wait for it. If Pyodide works it gives the docs a no-server
   playground (no code execution on our machines), and it could later replace the iframes for the
   simplest pages. It is not a reason to delay the hosted Studio.

## Alternatives considered

| Option | Why not |
|--------|---------|
| Put the Studio in the wheel | Adds weight and extra dependencies for every install, couples releases to demo code, and ships the playground's `exec` to everyone. |
| A separate `indah-studio` package on PyPI | A second release train and name to maintain with no user asking for it yet. Easy to add later from the same directory. |
| Host the Studio inside the gallery app | Mixes heavy model demos with feature pages and shares one failure domain; a broken or slow demo (IND-167) would hide the feature pages. Separate images keep them apart. |
| Host with the playground behind a login | A login is a weaker boundary than not mounting the code. The playground stays local-only. |
| Pyodide for everything | Unproven (server dependencies, SSE), large first load, and an 8 point spike before any user benefit. Kept as 83a. |
| Static screenshots or recorded GIFs in the docs | Cheap and safe but not interactive, which is what IND-169 asks for; they rot with every restyle. |
| Embed with `frame-ancestors *` | Lets any site frame the Studio; only the docs origin is allowed. |

## Consequences

- IND-169 is blocked by two new pieces of work, hosted mode (IND-173, 3) and the deployment
  (IND-174, 3), plus a 1 point release-step card (IND-175). They are filed, ordered and counted in the roadmap.
- A new route with relaxed framing exists on a hosted app. It serves the same read-only feature
  pages that run in the Studio, with the playground absent. The origin allow-list is configuration.
- The Studio's pages become a public surface: they must stay deterministic and free of secrets
  (already a Studio rule), and the hosted apps under `/apps/` are limited to the ones listed as safe.
- The hosted Studio depends on a deploy that needs the owner's access (Fly today, the homelab
  later). The docs build and the embeds degrade to the "Open in the Studio" link when the host is
  down; the docs build itself does not need the host.
- Revisit this ADR if the Pyodide spike passes (the embeds could become local runs), if the owner
  wants the Studio as the single front door, or if `pip install indah-studio` is requested.
