# Releasing

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

1. Bump `version` in `pyproject.toml` and `__version__` in `src/indah/__init__.py`.
2. Commit, tag (`git tag vX.Y.Z`), push the tag.
3. Create a GitHub Release for that tag. The `publish.yml` workflow builds and
   publishes automatically.
