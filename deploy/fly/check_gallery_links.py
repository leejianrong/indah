"""Check every listed gallery app and update the status file (IND-192).

Run by .github/workflows/gallery-links.yml, not at deploy. A dead listed app is reported in the step
summary and recorded in the state file; it does not fail the run. Only a script error does.

    python deploy/fly/check_gallery_links.py [--state PATH]
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import gallery_health as gh
from gallery_catalog import CATALOG, THUMB_DIR, listed, load_catalog, validate_catalog


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", type=Path, default=gh.STATE_FILE)
    args = ap.parse_args(argv)

    entries = load_catalog(CATALOG)
    bad = validate_catalog(entries)
    if bad:
        print("gallery.toml is invalid: " + "; ".join(bad), file=sys.stderr)
        return 1
    outside = listed(entries)
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    results = {e["slug"]: gh.check_url(e["url"]) for e in outside}
    state = gh.update_state(gh.load_state(args.state), results, now)
    gh.save_state(args.state, state)
    text = gh.summary(outside, state, gh.thumbnail_problems(outside, THUMB_DIR))
    print(text)
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if target:
        with open(target, "a", encoding="utf-8") as f:
            f.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
