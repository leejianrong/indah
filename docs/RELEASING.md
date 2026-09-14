# Releasing

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
