#!/usr/bin/env python3
"""Create + upload the indah demo Spaces to Hugging Face (ADR-0023).

Reads demos.tsv, and for each demo creates a Docker Space `<owner>/indah-<slug>`
(idempotent) and uploads the matching build/<slug>/ folder. Run build_space.sh first.

Auth: uses the logged-in Hugging Face CLI token (huggingface_hub picks it up), so
no secret lives in the repo. Run with the owner's account:

    ./build_space.sh
    uv run python deploy/spaces/deploy_hf.py            # all demos
    uv run python deploy/spaces/deploy_hf.py poster     # or one, by slug
"""

from __future__ import annotations

import sys
from pathlib import Path

from huggingface_hub import HfApi

HERE = Path(__file__).resolve().parent
BUILD = HERE / "build"


def main() -> None:
    only = sys.argv[1] if len(sys.argv) > 1 else ""
    api = HfApi()
    who = api.whoami()
    owner = who["name"]
    print(f"deploying as {owner}")

    for line in (HERE / "demos.tsv").read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        slug, *_rest = line.split("\t")
        if only and slug != only:
            continue
        folder = BUILD / slug
        if not folder.is_dir():
            print(f"!! {slug}: {folder} missing (run build_space.sh), skipping")
            continue
        repo_id = f"{owner}/indah-{slug}"
        api.create_repo(repo_id=repo_id, repo_type="space", space_sdk="docker", exist_ok=True)
        api.upload_folder(
            repo_id=repo_id,
            repo_type="space",
            folder_path=str(folder),
            commit_message="Deploy indah demo",
        )
        print(f"  deployed https://huggingface.co/spaces/{repo_id}")
        print(f"  live at  https://{owner}-indah-{slug}.hf.space")


if __name__ == "__main__":
    main()
