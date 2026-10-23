"""Release helpers (docs/RELEASING.md). They only read and print: none tags, deploys or publishes.

    release_check.py check X.Y.Z [--offline]   # the files agree and the tag is free
    release_check.py notes X.Y.Z               # the CHANGELOG section (GitHub Release notes)
    release_check.py post X.Y.Z                # the commands to run once PyPI has the release

``make release-check VERSION=X.Y.Z`` and ``make post-release VERSION=X.Y.Z`` call these.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(rc\d+)?$")
EM_DASH = "—"


def pyproject_version(root: Path = ROOT) -> str | None:
    m = re.search(r'^version\s*=\s*"([^"]+)"', (root / "pyproject.toml").read_text(), re.M)
    return m.group(1) if m else None


def module_version(root: Path = ROOT) -> str | None:
    m = re.search(
        r'^__version__\s*=\s*"([^"]+)"', (root / "src/indah/__init__.py").read_text(), re.M
    )
    return m.group(1) if m else None


def changelog_section(text: str, version: str) -> str | None:
    """The body of ``## [version] - date`` up to the next ``## [`` heading, or None."""
    m = re.search(rf"^## \[{re.escape(version)}\] - (\d{{4}}-\d{{2}}-\d{{2}})\s*$", text, re.M)
    if not m:
        return None
    rest = text[m.end() :]
    nxt = re.search(r"^## \[", rest, re.M)
    return (rest[: nxt.start()] if nxt else rest).strip("\n")


def unreleased_body(text: str) -> str | None:
    m = re.search(r"^## \[Unreleased\]\s*$", text, re.M)
    if not m:
        return None
    rest = text[m.end() :]
    nxt = re.search(r"^## \[", rest, re.M)
    return (rest[: nxt.start()] if nxt else rest).strip()


def duplicate_adr_numbers(adr_dir: Path) -> list[str]:
    counts = Counter(p.name[:4] for p in adr_dir.glob("[0-9][0-9][0-9][0-9]-*.md"))
    return sorted(n for n, c in counts.items() if c > 1)


def tag_exists(tag: str, *, remote: bool, root: Path = ROOT) -> bool:
    def run(*args: str) -> str:
        return subprocess.run(args, cwd=root, capture_output=True, text=True, check=False).stdout

    if run("git", "tag", "-l", tag).strip():
        return True
    return remote and bool(run("git", "ls-remote", "--tags", "origin", f"refs/tags/{tag}").strip())


def problems(version: str, root: Path = ROOT, *, tag_taken=lambda tag: False) -> list[str]:
    """Everything that would make tagging ``version`` a mistake. An empty list means go."""
    out: list[str] = []
    if not VERSION_RE.match(version):
        return [f"{version!r} is not X.Y.Z or X.Y.ZrcN"]
    if (v := pyproject_version(root)) != version:
        out.append(f"pyproject.toml says {v}, not {version}")
    if (v := module_version(root)) != version:
        out.append(f"src/indah/__init__.py __version__ says {v}, not {version}")
    text = (root / "CHANGELOG.md").read_text()
    section = changelog_section(text, version)
    if section is None:
        out.append(f"CHANGELOG.md has no '## [{version}] - YYYY-MM-DD' heading")
    else:
        if not section.strip():
            out.append(f"the CHANGELOG section for {version} is empty")
        if EM_DASH in section:
            out.append("the CHANGELOG section has an em-dash; user-facing text uses hyphens")
    if (u := unreleased_body(text)) is None:
        out.append("CHANGELOG.md has no '## [Unreleased]' heading")
    elif u:
        out.append("'## [Unreleased]' still has entries; they belong in the release section")
    if dup := duplicate_adr_numbers(root / "docs" / "adr"):
        out.append(f"two ADRs share a number: {', '.join(dup)}")
    if tag_taken(f"v{version}"):
        out.append(f"the tag v{version} already exists")
    return out


def post_release_commands(version: str) -> str:
    return f"""\
# 1. PyPI has the release (the pypi environment approval is the owner's). Expect {version}:
curl -s https://pypi.org/pypi/indah/json | \\
  python3 -c "import json,sys; print(json.load(sys.stdin)['info']['version'])"
gh run list --workflow "Publish to PyPI" --limit 1 --json status,conclusion

# 2. Redeploy the gallery. It pins indah=={version}, so only after step 1 (needs `fly auth login`):
./deploy/fly/deploy_fly.sh

# 3. Smoke-test the live gallery (every demo: console errors, failed requests, stuck 'connecting'):
GALLERY_URL=https://indah-demos.fly.dev uv run pytest tests/e2e/test_gallery.py

# 4. The docs site deploys on the merge to main (Docs workflow). Confirm it and open a live example:
gh run list --workflow Docs --branch main --limit 1 --json status,conclusion
# then open https://indah.abangai.dev/docs/ and press 'Run it' on an example (about 9 MB, once)

# 5. Board: move the release's cards to done, and note the release on any card waiting for it.
"""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("command", choices=["check", "notes", "post"])
    ap.add_argument("version")
    ap.add_argument(
        "--offline", action="store_true", help="check: do not ask the remote about the tag"
    )
    args = ap.parse_args(argv)
    if args.command == "post":
        print(post_release_commands(args.version))
        return 0
    if args.command == "notes":
        section = changelog_section((ROOT / "CHANGELOG.md").read_text(), args.version)
        if section is None:
            print(f"no CHANGELOG section for {args.version}", file=sys.stderr)
            return 1
        print(section)
        return 0
    found = problems(args.version, tag_taken=lambda tag: tag_exists(tag, remote=not args.offline))
    for p in found:
        print(f"FAIL: {p}", file=sys.stderr)
    if found:
        return 1
    print(
        f"ok: {args.version} is consistent and the tag is free.\n"
        "Next: confirm every check on the release commit is green, then tag."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
