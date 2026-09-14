# Releasing

## Status (2026-09)

The name `indah` is **already reserved** on PyPI - a `0.0.1` placeholder was
uploaded with a token (the "reserve the name" step below, now done). The first
real release is `0.1.0`, cut as a release candidate (`0.1.0rc1`) first so the
Colab/RunPod smoke test (R2) runs against an installable artifact before the final
tag.

Trusted Publishing is **not wired up yet**. Before any CI publish (the
`publish.yml` workflow) can succeed, the owner must do two one-time things once,
described under [Later releases](#later-releases-trusted-publishing-no-token):
add the GitHub publisher on PyPI and create the `pypi` GitHub Environment. Until
then, an RC can be pushed with a token upload (`uv publish --token ...`, same as
the reserve step) from the owner's terminal.

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

Then every release is:

1. Bump `version` in `pyproject.toml` and `__version__` in `src/indah/__init__.py`
   (keep them in lockstep - `tests/unit/test_version.py` and the packaging tests
   guard the invariants).
2. Run `make cleanroom` and `make check` - the R4 proof and the fast gate.
3. Commit, tag (`git tag vX.Y.Z`), push the tag.
4. Create a GitHub Release for that tag. The `publish.yml` workflow builds and
   publishes automatically.
