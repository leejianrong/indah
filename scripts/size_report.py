"""Print the numbers ADR-0042 budgets: wheel size, shell and editor sizes, base dependencies.

CI runs it in the `build` job against docs/size-budget.json and fails when a number is over its
limit. Standard library only; needs Python 3.11+ (tomllib).

    uv build && python scripts/size_report.py                          # prints JSON
    python scripts/size_report.py --budget docs/size-budget.json       # exit 1 when over a limit
    python scripts/size_report.py --budget docs/size-budget.json --distributions 12 --summary

A budget file maps a metric name to its maximum, for example {"wheel_bytes": 650000}; keys that
start with an underscore are comments, and any other key that is not a metric is an error (a typo
must not switch a limit off). `--distributions N` adds `base_install_distributions`: the number of
third-party distributions pip installed next to indah (the CI step counts them in a clean venv).
`--summary` prints a markdown table of every limit with its headroom (used for the job summary).

To raise a limit on purpose, edit docs/size-budget.json in the pull request that needs the room,
and say why in the description and the CHANGELOG, so a reviewer sees the number move.
"""

import argparse
import gzip
import importlib.util
import json
import sys
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "indah" / "static"


def _gzip_size(path: Path) -> int:
    return len(gzip.compress(path.read_bytes(), 9))


def _load(name: str):
    """A module of the package by file, without importing `indah` (and so pydantic)."""
    spec = importlib.util.spec_from_file_location(f"_size_{name}", STATIC.parent / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _served_shell_bytes() -> int:
    """The shell as indah sends it to a gzip client under `csp="strict"`: compressed in pieces
    around the nonce, so a little larger than one gzip of the whole file (ADR-0042)."""
    compress, csp = _load("compress"), _load("csp")
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    return len(compress.gzip_joined(csp.add_nonce_parts(html), ' nonce="' + "x" * 24 + '"'))


def measure() -> dict[str, int]:
    out: dict[str, int] = {}
    wheels = sorted((ROOT / "dist").glob("indah-*.whl"))
    if wheels:
        out["wheel_bytes"] = wheels[-1].stat().st_size
    shell, editor = STATIC / "index.html", STATIC / "editor.js"
    out["shell_raw_bytes"] = shell.stat().st_size
    out["shell_gzip_bytes"] = _gzip_size(shell)
    out["shell_served_gzip_bytes"] = _served_shell_bytes()
    out["editor_raw_bytes"] = editor.stat().st_size
    out["editor_gzip_bytes"] = _gzip_size(editor)
    sources = (ROOT / "src" / "indah").glob("*.py")
    out["python_source_bytes"] = sum(p.stat().st_size for p in sources)
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    out["direct_dependencies"] = len(project["dependencies"])
    return out


def load_limits(path: Path) -> dict[str, int]:
    """The limits in a budget file, without its `_comment`-style keys."""
    raw = json.loads(path.read_text())
    return {k: v for k, v in raw.items() if not k.startswith("_")}


def check(numbers: dict[str, int], limits: dict[str, int]) -> tuple[list[str], list[str]]:
    """(problems, over-budget lines). A limit with no measured number is a problem, not a pass."""
    problems = [f"no measurement for the budgeted metric {k!r}" for k in limits if k not in numbers]
    over = [
        f"OVER BUDGET: {k} is {numbers[k]}, limit {v}"
        for k, v in limits.items()
        if k in numbers and numbers[k] > v
    ]
    return problems, over


def summary(numbers: dict[str, int], limits: dict[str, int]) -> str:
    """A markdown table of every budgeted number, its limit and the room left."""
    rows = ["| Metric | Now | Limit | Room | |", "|---|---:|---:|---:|---|"]
    for key, limit in limits.items():
        if key not in numbers:
            rows.append(f"| {key} | n/a | {limit:,} | | missing |")
            continue
        now = numbers[key]
        room = limit - now
        state = "OVER" if room < 0 else "ok"
        rows.append(f"| {key} | {now:,} | {limit:,} | {room:,} | {state} |")
    return "\n".join(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--budget", type=Path, help="JSON file of maximums to check against")
    parser.add_argument(
        "--distributions",
        type=int,
        help="third-party distributions in a clean base install (adds base_install_distributions)",
    )
    parser.add_argument("--summary", action="store_true", help="also print a markdown table")
    args = parser.parse_args()
    numbers = measure()
    if args.distributions is not None:
        numbers["base_install_distributions"] = args.distributions
    print(json.dumps(numbers, indent=2))
    if args.budget is None:
        return 0
    limits = load_limits(args.budget)
    problems, over = check(numbers, limits)
    if args.summary:
        print()
        print(summary(numbers, limits))
    for line in problems + over:
        print(line, file=sys.stderr)
    return 1 if (problems or over) else 0


if __name__ == "__main__":
    sys.exit(main())
