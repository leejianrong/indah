# Documentation site

The user-facing docs site for indah, built with [Zensical](https://zensical.org)
(the successor to Material for MkDocs) and deployed to GitHub Pages.

This is a separate tree from the repo's engineering docs in `../docs/` (plan,
slices, ADRs): those are for contributors; this is the published site.

## Build and preview locally

```bash
uv sync --extra docs
cd website
uv run zensical serve      # live preview at http://127.0.0.1:8000/
uv run zensical build --clean   # one-off build into website/site/ (gitignored)
```

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
