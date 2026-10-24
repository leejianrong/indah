# ADR-0042: Extras, lazy modules and a size budget

- Status: **Accepted** (2026-10-24, owner)
- Date: 2026-10-23
- Deciders: Jian (owner)
- Relates to: ADR-0004 (pre-built shell, no Node), ADR-0032 (lazy editor module), ADR-0039 (module
  components), ADR-0041 (the docs and the Studio)

## Context

The owner's stance (2026-10-23): make indah as expressive as possible, and manage the size of
`pip install indah` with **extras** instead of leaving features out. This ADR says what extras can
and cannot do, which mechanism fits which kind of weight, and what size we hold ourselves to.

Terms. An *extra* (also called an optional dependency) is a named group in
`[project.optional-dependencies]` in `pyproject.toml`, installed with `pip install "indah[plot]"`
(PEP 621 and the PEP 508 extras syntax). The base install is `pip install indah`.

## Measurements

All numbers are from `main` at `f0abf4e` (0.6.0 plus later merges) unless a row names a tag, taken on
2026-10-23.

**The wheel and the sdist** (`uv build`; `unzip -l dist/*.whl`; PyPI JSON for released sizes)

| Item | Bytes | Note |
|------|-------|------|
| wheel, built from `main` | 555,280 | PyPI 0.6.0 wheel: 549,563 |
| sdist, built from `main` | 6,260,579 | PyPI 0.6.0 sdist: 6,227,831 |
| `static/editor.js` | 633,404 raw, 177,815 gzip | lazy, ADR-0032 |
| `static/index.html` (the shell) | 569,673 raw, 239,950 gzip | Svelte, uPlot and Leaflet inlined |
| Python modules (28 files) | 381,089 raw, about 110,150 gzip | `components.py` alone is 153,053 |

Uncompressed the wheel holds 1,610,963 bytes in 35 files. Shell, editor and Python together are about
528 KB of the 555 KB wheel, so the wheel is almost entirely these three. The sdist is 11 times the
wheel because it carries the repository: by uncompressed directory, `examples/` 4.97 MB, `deploy/`
1.70 MB (thumbnails), `src/` 1.58 MB, `tests/` 0.75 MB, `docs/` 0.46 MB, `frontend/` 0.41 MB.
`pip install` uses the wheel, so the sdist size does not reach users, but it is what a source
build downloads.

**The base install** (clean venv, `uv pip install dist/*.whl`; `du -sk site-packages`)

The base install is 12 third-party distributions and 12,092 kB of `site-packages`, of which indah
itself is 1,624 kB (13 percent). The weight is `pydantic_core` (4,972 kB) and `pydantic` (2,040 kB).
The direct dependencies are four: `starlette`, `uvicorn`, `pydantic`, `python-multipart`. The
wheel is small next to what it pulls in.

**The existing extras** (each installed from the built wheel into a fresh venv)

| Extra | Distributions (with indah) | `site-packages` | Holds |
|-------|---------------|-----------------|-------|
| (base) | 13 | 12.1 MB | the four direct dependencies and their dependencies |
| `dev` | 29 | 39.5 MB | pytest, pytest-asyncio, httpx, ruff, authlib, itsdangerous, cryptography |
| `e2e` | 16 | 154.8 MB | playwright (its driver; the Chromium download is separate and not measured) |
| `docs` | 23 | 117.0 MB | zensical |

All three are contributor tooling. No extra today holds a feature library.

**What the browser downloads** (Playwright against a launched app; every response body except the
event stream, raw and gzip level 9; `scripts/size_report.py` prints the file sizes)

| App | Raw | Gzip |
|-----|-----|------|
| starter app (the shell only) | 569,673 | 239,950 |
| with a `CodeEditor` (adds `editor.js`) | 1,203,077 | 417,765 |
| with a module component (adds the 4 KB module) | 573,773 | 241,683 |

indah itself sends **no** `Content-Encoding`: with `Accept-Encoding: gzip, br` the local server
returned the 569,673-byte shell and the 633,404-byte editor as is. The proxy in front decides the real
transfer: through Fly's edge `/chatbot/` was 270,534 bytes (brotli), and through the Cloudflare
Worker 240,877 bytes (brotli). Colab's and Runpod's proxies were not measured.

**Growth** (tags; `git show vX:src/indah/static/index.html`; PyPI for wheels)

| Release | Shell raw | Shell gzip | `editor.js` raw | Python source | Wheel |
|---------|-----------|------------|-----------------|---------------|-------|
| 0.2.2 | 460,293 | 208,086 | - | 148,051 | 266,767 |
| 0.3.0 | 517,922 | 225,597 | - | 241,569 | 316,604 |
| 0.4.0 | 525,599 | 227,724 | 633,404 | 311,995 | 525,197 |
| 0.5.0 | 541,634 | 232,475 | 633,404 | 334,736 | 535,584 |
| 0.6.0 | 558,344 | 237,111 | 633,404 | 370,188 | 549,563 |
| `main` | 569,673 | 239,950 | 633,404 | 381,089 | 555,280 (built) |

Since 0.3.0 the shell has grown about 10 percent raw and 6 percent gzip across three releases and
dozens of components. A typical component costs 3 to 5 KB raw and 1 to 2 KB gzip (the bridge:
+3,255 raw and +1,167 gzip, PR #191; BarStrip: +4,250 and +1,229, PR #209). The wheel jumped
at 0.4.0 only because `editor.js` joined it.

**What is inside the shell.** The shell inlines Leaflet (`Map`) and uPlot (`Chart`). Their minified
library sources are 147,552 + 14,806 bytes (Leaflet JS and CSS; 42,356 + 3,534 gzip) and 51,081 +
1,857 bytes (uPlot; 22,009 + 772 gzip): about 215 KB raw, 38 percent of the shell, and about 69 KB
gzip, 29 percent. These are the library files, before bundling, so the true share is approximate.

**Not measured.** The exact bundle share of Leaflet, uPlot or `TableRich` (needs a bundle visualiser
run; a task below). The Chromium download for `e2e`. Colab and Runpod proxy compression. Memory in the
browser. Install time. The CPU cost of compressing the shell on each request.

## What extras can and cannot do

- An extra only adds **third-party packages**. It never removes code from the wheel. The wheel is the
  same 555 KB for `pip install indah` and `pip install "indah[plot]"`. Extras alone do not shrink the
  wheel, and they cannot shrink the shell the browser downloads.
- An extra is useful for what a feature needs *from other people*: matplotlib for a `Plot`,
  pandas for a data frame, Pillow for images. It documents and pins a tested range, and it keeps a
  heavy library out of the base install.
- The base wheel is only 5 percent of the install by size. The dominant costs are `pydantic-core`
  (outside our control) and, in the browser, the shell. So the lever that matters for users is the
  **first load**, and the sections below treat it separately from the install.

## Decision

### Three mechanisms, and when to use each

1. **A lazy module inside the wheel** (the `editor.js` pattern, ADR-0032). Use it for a first-party
   feature that is heavy in the browser and used by a minority of apps. Apps that never render it
   download nothing. It still ships in the wheel, so it does not reduce the PyPI download.
2. **An extra for a third-party library.** Use it when a feature needs another package to work. The
   core never imports it at module level: the import happens where it is used, with an error that
   names the extra (`pip install "indah[plot]"`). Duck-typing (today's `Plot` and `DataFrame`)
   needs no import and no error.
3. **A companion distribution** (`indah-<name>`, pulled in by an extra and pinned to the same indah
   version). Use it only for a first-party asset big enough that the wheel itself becomes the problem
   (thresholds below). Not needed today.

### What must stay in core

The protocol and its models, the reactive core, every component's Python side, sessions and the
session store, the app and transport, the shell and everything the quickstart needs, and the
off-by-default hosting layer (auth, authz, hardening, CSP; all pure Python). The base install keeps
**four direct dependencies** and installs with **no Node at install or runtime** (R4,
`make cleanroom`). Two further limits on the dependency list:

- A new hard dependency must be pure Python or already shipped by Pyodide. The docs playground
  installs indah with `micropip.install(..., deps=False)` and relies on Pyodide's own `pydantic`,
  `starlette`, `anyio` and `h11` (spike IND-176, `docs/spikes/pyodide.md`). A new compiled
  dependency in core would break it.
- Anything optional goes behind an extra, never into `dependencies`.

### Extras: naming rules and the proposed set

- Feature extras are named for the **kind of data or job**, lower case, one word: `plot`, `data`.
  Tooling extras keep their names (`dev`, `e2e`, `docs`). No extra is named for a vendor or a version.
- An extra exists only when the code uses the library, or documents a tested version range for it.
  `all` is the union of the feature extras and never includes tooling.
- Each extra has a version floor and a line in the docs saying which components it enables.

| Extra | Holds | Enables | Status |
|-------|-------|---------|--------|
| `plot` | `matplotlib` | `Plot(figure)`; the matplotlib chart in the built-in demo | add now (documents the tested floor) |
| `data` | `pandas`, `numpy` | `DataFrame` and `Table` from frames; numpy scalars in cells | add now |
| `demos` | `numpy`, `pillow`, `onnxruntime`, `huggingface_hub`, `matplotlib` | the gallery demos and examples (the list `build_gallery.sh` installs) | add now; the gallery build installs `indah[demos]` |
| `all` | `plot` + `data` | everything above except demos | add now |
| `media` | `pillow`, `numpy` | `Image` from a PIL image or array (not supported today) | wait for the feature |
| `geo` | not decided | tracks, shapes | wait for a Python-side need (`Map` is client side) |

Honest limit: `plot` and `data` change nothing for a user who already has matplotlib or pandas, since
indah duck-types them. Their value is documentation, a tested floor and a place for future checks.

### Lazy first-party modules: how to build one and the checklist

The editor pattern, generalised. A module is built by its own Vite config
(`frontend/vite.<name>.config.js`, `lib` mode, `format: "es"`, output `dist-<name>/<name>.js`), copied
by `npm run build:indah` into `src/indah/static/`, served by the app at `GET api/<name>.js`, and
`import()`ed by the shell the first time the component renders.

Checklist when adding one:

1. A Vite config and a `build` and `build:indah` step, like `vite.editor.config.js`.
2. A route serving the file from an **allow-list of names** (the current `_editor_js` route,
   generalised), with an ETag, and a content-hash in the URL (`?v=`, as ADR-0039) so a new release
   is fetched at once and an old one is cached for good.
3. A relative URL (works under any mount prefix) and no CSP change (`script-src 'self'` already
   covers it; the dynamic `<style>` nonce rule from ADR-0038 applies).
4. A line in the CI `frontend` job that rebuilds and diffs the file, so a stale module fails CI
   (as `editor.js` does today).
5. A Studio page, a docs note on the first-load cost, and a row in the size budget.
6. `make cleanroom` passes (no Node tripwire) and the wheel still builds with the file inside.

Candidates, in order, subject to measuring: **`Map` (Leaflet)**, the largest single library in the
shell and a niche feature; then **`Chart` (uPlot)**. Taking both out would cut the shell by roughly 215
KB raw and 69 KB gzip, 29 to 38 percent, at the price of one extra request on first use of each. Do
Map first, measure the real saving with a bundle visualiser, and only then decide on Chart.

### A size budget and a CI gate

Budgets sit about 15 percent above today, which is roughly five releases at the recent 3 percent a
release (shell gzip grew 227,724 to 239,950 from 0.4.0 to `main`). They are limits that a pull request
must raise on purpose, not targets.

| Metric (`scripts/size_report.py`) | Now (`main`) | Limit | Reading |
|-----------------------------------|--------------|-------|---------|
| `wheel_bytes` | 555,280 | 650,000 | the PyPI download |
| `shell_gzip_bytes` | 239,950 | 275,000 | first load of the starter app; room for about 25 more components |
| `shell_raw_bytes` | 569,673 | 650,000 | what indah sends when nothing compresses |
| `editor_gzip_bytes` | 177,815 | 200,000 | the largest lazy module |
| `direct_dependencies` | 4 | 5 | base install |
| transitive distributions in the base install | 12 | 14 | measured in the CI `build` job, not by the script |

**Gate.** `scripts/size_report.py` (added with this ADR, not wired) prints these numbers as JSON and,
given `--budget docs/size-budget.json`, exits non-zero when one is over its limit. The proposal is
one step in the CI `build` job after `uv build`, plus the budget file under review like any other
file. A card that needs more room raises the limit in its own pull request, with a sentence in the
description and the CHANGELOG; a reviewer sees the number move. A soft check can also print the
delta against `main` on every pull request.

### Companion distributions: when, and what they cost

Split a first-party asset into `indah-<name>` only when **one** of these holds:

- the asset exceeds 1 MB raw (about 300 KB gzip) and fewer than about one app in five uses it; or
- the wheel exceeds 1.5 MB compressed.

Today the largest asset is `editor.js` at 633 KB raw and 178 KB gzip, and the wheel is 0.55 MB. Neither
line is crossed, so **no split**.

What a split costs, so the line is not crossed lightly: a second PyPI project per package (the name has
to be reserved, as `indah` was with the 0.0.1 placeholder); a Trusted Publisher entry on PyPI for each
project (an owner task, once each); `publish.yml` must build and upload every distribution in one
release, and the `pypi` environment approval gates it (one approval if it is one job, one per job
otherwise); the versions move in **lockstep** (`indah-<name>==X.Y.Z` pinned by indah's extra, and
`indah==X.Y.Z` by the companion), so a release is not installable until both are published;
`make cleanroom` and the tripwires must install both; and `docs/RELEASING.md` grows. That is a lot to
carry for a few hundred kilobytes.

### Recommendation

1. **Stay a single distribution** with four dependencies.
2. **Lazy modules first** for heavy first-party browser code: `Map` next, then `Chart` if the
   measurement supports it.
3. **Extras for third-party libraries**, added when the code needs them. Add `plot`, `data`, `demos`
   and `all` now.
4. Adopt the budget above and wire the gate in a follow-up card.
5. Do **not** split a companion package until a threshold above is crossed.

## Consumers

- **The docs playground (ADR-0041, IND-83).** The Pyodide bundle is about 16.4 MB raw and 9.1 MB gzip
  (spike), of which the indah wheel is 0.55 MB. It loads only after a "Run it" click, so it is a
  docs-site cost, not an install cost, and the budget above does not cover it. The constraint it puts
  on core is the dependency rule above. The playground installs the wheel at the docs version, so
  every release automatically moves its wheel size.
- **The gallery (`deploy/fly`).** It pins `indah==<version in pyproject.toml>` (IND-167) and today
  installs the demo libraries by name. It should install `indah[demos]` so one list serves the
  gallery, the examples and the docs.

## Alternatives considered

| Option | Why not |
|--------|---------|
| Drop features to keep the shell small | Against the owner's aim of being as expressive as possible; lazy modules keep the feature and move the cost. |
| Split into `indah-core` plus feature packages now | Large release overhead (above) for a wheel that is 5 percent of the install. |
| Compile with a smaller UI framework or drop uPlot and Leaflet | Both are small for what they do; lazy loading keeps the capability. |
| Rely on extras to cut size | They cannot: they only add packages. |
| No budget, "watch the number" | The shell has grown every release; a gate makes growth a choice. |

## Consequences

- Features can keep arriving. The first-load cost is held by the budget and relieved by lazy modules,
  not by saying no.
- The extras are cheap to add and honest about being mostly documentation until a feature needs a
  library.
- A heavy library can no longer be added to `dependencies` without a review: it fails the dependency
  rule and the gate.
- Splitting a companion package stays possible, with its costs written down.

## Follow-ups (cards to file)

1. Measure the bundle share of Leaflet, uPlot and `TableRich` (bundle visualiser), and build the Map
   lazy module if the saving holds. 3 points.
2. Wire `scripts/size_report.py` into CI with `docs/size-budget.json`. 1 point.
3. Add the `plot`, `data`, `demos` and `all` extras, document them, and make the gallery install
   `indah[demos]`. 2 points.
4. Compress what indah serves: the shell and `editor.js` are sent uncompressed today, so apps without
   a compressing proxy download 570 KB (and 633 KB for the editor). Measure the CPU cost; the shell is
   rewritten per response for the CSP nonce, so it cannot be compressed once and cached as is. 2 points.
5. Trim the sdist (exclude `examples/` and `deploy/` thumbnails with a hatch sdist rule). It does not
   affect `pip install`, only source downloads. 1 point.
