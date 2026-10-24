# Releasing

## Status (2026-10)

Trusted Publishing is wired up: `publish.yml` runs on a published GitHub Release and its `publish` job
waits for the owner to approve the `pypi` environment. Releases 0.1.0 to 0.4.0 went out this way. The
sections below on reserving the name and the token upload are kept as history.

## Pre-flight: the clean-room check (every release)

Before tagging, prove R4 - that the wheel needs zero Node at install or runtime:

```bash
make cleanroom   # uv build, then scripts/cleanroom.sh
```

It installs the freshly built wheel into a throwaway venv with `node`, `npm`,
`npx`, `bun`, `yarn`, `pnpm`, `vite`, `svelte`, and `esbuild` tripwires first on
`PATH`; each logs any invocation and exits non-zero. The check passes only when the
log is empty and the app builds its tree and serves the pre-built shell. `twine
check dist/*` (also run in CI) is the metadata/README gate.

## The size budget (every pull request)

CI's `build` job runs `scripts/size_report.py` against `docs/size-budget.json` (ADR-0042) and fails
when the wheel, the shell (raw or gzip), `editor.js`, the direct dependencies or the number of
third-party distributions in a clean base install go over their limit. The job summary shows every
number with the room left. Run it locally with `make size`.

A limit is a ceiling, not a target. A pull request that really needs more room raises the limit in
`docs/size-budget.json` in the same diff, and says why in its description and the CHANGELOG, so a
reviewer sees the number move. Do not raise it to make a red build green without that sentence.

## Release candidates

An RC (`X.Y.ZrcN`) is a pre-release: `pip install indah` skips it, so testers must
opt in with `--pre`:

```bash
pip install --pre indah==0.1.0rc1
```

Cut it exactly like a final release (bump, clean-room, tag `vX.Y.ZrcN`, GitHub
Release) - `publish.yml` and PyPI both treat an rc-suffixed version as a
pre-release automatically. Promote to the final version only after the RC checks
out (for `0.1.0`, after the R2 smoke test).

## Dry-run on TestPyPI (optional, before the first real upload)

TestPyPI (<https://test.pypi.org>) is a throwaway index for rehearsing a publish.
It is a separate instance from PyPI: a different account, a different namespace,
and it is pruned periodically. So uploading here does **not** reserve `indah` on
real PyPI - it only proves the pipeline works and the metadata and README render
before you spend the real name on a possibly-broken wheel. (As a side effect it
does park the name on TestPyPI for now, which keeps your staging uploads from
colliding with someone else's - a convenience, not brand protection.)

1. Create a TestPyPI account and token at
   <https://test.pypi.org/manage/account/token/> (separate from your PyPI one).
2. Build and upload to the test index:

   ```bash
   uv build
   uv publish --publish-url https://test.pypi.org/legacy/ --token pypi-TEST-XXXX
   ```

3. Confirm at <https://test.pypi.org/project/indah/>, then install into a clean
   venv to check it resolves (pull real deps from PyPI, only `indah` from TestPyPI):

   ```bash
   uv venv /tmp/indah-test && . /tmp/indah-test/bin/activate
   uv pip install --index-url https://test.pypi.org/simple/ \
     --extra-index-url https://pypi.org/simple/ indah
   ```

When it looks right, do the real upload below. (Brand protection lives there, not
here - see ADR-0006.)

## First release: reserve the name (one-time, token upload)

The very first publish needs an API token because no project exists on PyPI yet
and Trusted Publishing has nothing to attach to. Do this from your own terminal so
the token never lands in a shared log:

1. Create a PyPI account and an API token at <https://pypi.org/manage/account/token/>
   (scope it to "Entire account" for the first upload; you can narrow it to the
   `indah` project afterwards).
2. Build and upload:

   ```bash
   uv build
   uv publish --token pypi-XXXXXXXX   # paste your real token
   ```

3. Confirm at <https://pypi.org/project/indah/>.

## Later releases: Trusted Publishing (no token)

After the project exists, switch to OIDC-based Trusted Publishing so no secret is
stored anywhere. One-time setup:

1. On PyPI: project `indah` -> Settings -> Publishing -> add a GitHub publisher:
   - Owner: `leejianrong`
   - Repository: `indah`
   - Workflow: `publish.yml`
   - Environment: `pypi`
2. In the GitHub repo: create an Environment named `pypi` (Settings -> Environments).

## The release checklist (every release)

Do these in order. Nothing here deploys or publishes by itself except step 7 (the GitHub Release), and
that only starts the `publish.yml` job, which waits for the owner to approve the `pypi` environment.
Replace `X.Y.Z` with the version. A release candidate is `X.Y.ZrcN` and follows the same steps.

**Before the release PR**

1. Check the board: every card meant for the release is done, and the roadmap (`docs/ROADMAP.md`) matches.
2. Check the ADR numbers are unique (`ls docs/adr`; two ADRs once both got 0040). `make release-check`
   repeats this check.
3. If the Pyodide version changed, it was a reviewed commit of its own: `PYODIDE_VERSION` in
   `scripts/build_docs_live.py` pins it and the docs build writes it to `runtime.json` (ADR-0041). A bump
   can change the Python and package versions the live examples run on, so run the live-example check
   (`make docs`, then open a live example) in that commit, not in the release PR.

**The release PR** (one PR, branch `release/X.Y.Z`)

4. Bump the version in both files, which must agree (`tests/unit/test_version.py` guards it):
   - `pyproject.toml`: `version = "X.Y.Z"`
   - `src/indah/__init__.py`: `__version__ = "X.Y.Z"`
5. In `CHANGELOG.md`, turn the `## [Unreleased]` entries into `## [X.Y.Z] - YYYY-MM-DD` with a short
   introduction, add "Known limitations" and, if anything looks different, an "Upgrading" section, and
   leave an empty `## [Unreleased]` above it. Hyphens, no em-dashes.
6. Run the checks locally, then open the PR:

   ```bash
   make release-check VERSION=X.Y.Z   # files agree, CHANGELOG heading exists, [Unreleased] is empty,
                                      # no em-dash, ADR numbers unique, the tag is free (reads only)
   make cleanroom                     # R4: the wheel needs no Node, at install or run time
   make check                         # the fast gate
   ```

   Merge the PR **only when every check is green and none is pending**. `gh pr checks --watch` can return
   while checks are still queued, so confirm with a loop:

   ```bash
   until ! gh pr checks | grep -qE "pending|queued|in_progress"; do sleep 20; done; gh pr checks
   ```

   Read the final list: the checks must exist (an empty list also exits the loop) and all say `pass`.

   The `Docs` workflow is part of that: its build runs the live-example bundle (`build_docs_live.py
   bundle`, then `finalize`) from this commit, with the wheel built from the same commit, so a red docs
   build means the live examples would be broken on the site.
7. After the merge, wait for CI on the release commit on `main`: `gh run list --branch main --limit 4
   --json name,status,conclusion,headSha` must show `CI` and `Docs` for that commit as `completed` and
   `success`. Then tag and publish the GitHub Release with the CHANGELOG section as its notes:

   ```bash
   git checkout main && git pull
   make release-check VERSION=X.Y.Z                       # once more, on the merged commit
   python3 scripts/release_check.py notes X.Y.Z > /tmp/notes-X.Y.Z.md
   git tag vX.Y.Z && git push origin vX.Y.Z
   gh release create vX.Y.Z --title "vX.Y.Z" --notes-file /tmp/notes-X.Y.Z.md
   ```

**Publishing (the owner's step)**

8. `publish.yml` builds the wheel and then **waits for the owner to approve the `pypi` environment**
   (GitHub: Actions, the run, Review deployments). Never bypass it. Confirm the result:

   ```bash
   gh run list --workflow "Publish to PyPI" --limit 1 --json status,conclusion
   curl -s https://pypi.org/pypi/indah/json | python3 -c "import json,sys; print(json.load(sys.stdin)['info']['version'])"
   ```

**After the release is on PyPI** (`make post-release VERSION=X.Y.Z` prints these with the version filled in)

9. **Redeploy the gallery.** `deploy/fly/build_gallery.sh` pins `indah==<version in pyproject.toml>`
   (an exact pin, because a `>=` range let Docker reuse an old cached layer and demos that need newer
   API broke). So deploy only **after** step 8, from a clean checkout of the release commit. It needs
   `fly auth login` on that machine:

   ```bash
   ./deploy/fly/deploy_fly.sh
   ```

10. **Smoke-test the live gallery.** It opens every demo, uses its main control and fails on console
    errors, failed requests, CSP violations or a stuck "connecting":

    ```bash
    GALLERY_URL=https://indah-demos.fly.dev uv run pytest tests/e2e/test_gallery.py
    ```

11. **Check the docs site and its live examples.** The `Docs` workflow deploys to GitHub Pages on every
    merge to `main`, so the site already carries the release commit's bundle. Confirm the deploy is
    green (`gh run list --workflow Docs --branch main --limit 1`), open
    <https://indah.abangai.dev/docs/>, press **Run it** on an example and check that it responds. The
    first run downloads about 9 MB (Pyodide, from the pinned jsDelivr URL) and takes a few seconds.
    There is no separate Studio deploy: the Studio runs locally (`make demo`) and its pages run in the
    docs through Pyodide (ADR-0041).
12. **Housekeeping.** Move the release's cards to done, update `docs/ROADMAP.md` (what shipped, what
    moved), and note the release on any card that was waiting for it. If the gallery or docs check
    failed, file a card; do not retag.

If a step fails after the tag exists, fix forward with a patch release (`X.Y.Z+1`); do not move or
delete a published tag.
