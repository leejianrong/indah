# Documentation site

The user-facing docs site for indah, built with [Zensical](https://zensical.org)
(the successor to Material for MkDocs) and deployed to GitHub Pages.

This is a separate tree from the repo's engineering docs in `../docs/` (plan,
slices, ADRs): those are for contributors; this is the published site.

## Build and preview locally

```bash
uv sync --extra docs
uv run python scripts/build_docs_live.py bundle   # the live-example bundle (see below); once
cd website
uv run zensical serve      # live preview at http://127.0.0.1:8000/
uv run zensical build --clean   # one-off build into website/site/ (gitignored)
```

Without the bundle the build still passes, but a live example (`<indah-live>`) cannot run. `make docs`
and `make docs-serve` build it for you.

Or from the repo root via the Makefile:

```bash
make docs         # build into website/site/
make docs-serve   # live preview
```

## Structure

- `zensical.toml` - site config (nav, theme, markdown extensions).
- `docs/` - the Markdown source for each page.
- `site/` - build output (gitignored; CI rebuilds it fresh).

## How it ships

`.github/workflows/docs.yml` builds the site on every pull request (a build-check,
so a broken build fails before merge) and deploys to GitHub Pages on push to
`main`. Enable Pages once in the repo settings (Settings → Pages → Source: GitHub
Actions).

## Live examples

A docs page can run a Studio page in the reader's browser with Pyodide (ADR-0041). Put
`<indah-live page="chapter/page"></indah-live>` on its own line; the page ids are the Studio's
(`c/<chapter>/<page>`). Nothing downloads until the reader presses **Run it** (about 9 MB). The
bundle is generated into `docs/assets/live/` by `scripts/build_docs_live.py` (git-ignored) and the
element script is `docs/javascripts/indah-live.js`. See `../docs/STUDIO.md` for the rules (a page that
needs a server is marked `local_only`) and the size budgets.

