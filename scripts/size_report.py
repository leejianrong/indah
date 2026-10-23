"""Print the numbers ADR-0042 budgets: wheel size, shell and editor sizes, base dependencies.

Not wired into CI (ADR-0042 proposes that). Standard library only; needs Python 3.11+ (tomllib).

    uv build && python scripts/size_report.py            # prints JSON
    python scripts/size_report.py --budget budget.json   # exit 1 when a number is over its limit

A budget file maps a metric name to its maximum, for example {"wheel_bytes": 650000}.
"""

import argparse
import gzip
import json
import sys
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "indah" / "static"


def _gzip_size(path: Path) -> int:
    return len(gzip.compress(path.read_bytes(), 9))


def measure() -> dict[str, int]:
    out: dict[str, int] = {}
    wheels = sorted((ROOT / "dist").glob("indah-*.whl"))
    if wheels:
        out["wheel_bytes"] = wheels[-1].stat().st_size
    shell, editor = STATIC / "index.html", STATIC / "editor.js"
    out["shell_raw_bytes"] = shell.stat().st_size
    out["shell_gzip_bytes"] = _gzip_size(shell)
    out["editor_raw_bytes"] = editor.stat().st_size
    out["editor_gzip_bytes"] = _gzip_size(editor)
    sources = (ROOT / "src" / "indah").glob("*.py")
    out["python_source_bytes"] = sum(p.stat().st_size for p in sources)
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    out["direct_dependencies"] = len(project["dependencies"])
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--budget", type=Path, help="JSON file of maximums to check against")
    args = parser.parse_args()
    numbers = measure()
    print(json.dumps(numbers, indent=2))
    if args.budget is None:
        return 0
    limits = json.loads(args.budget.read_text())
    over = {k: (numbers[k], v) for k, v in limits.items() if k in numbers and numbers[k] > v}
    for key, (value, limit) in over.items():
        print(f"OVER BUDGET: {key} is {value}, limit {limit}", file=sys.stderr)
    return 1 if over else 0


if __name__ == "__main__":
    sys.exit(main())
