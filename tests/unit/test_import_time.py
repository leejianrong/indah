"""IND-137: `import indah` stays cheap (semula has a 2 s cold-start budget).

Measured at 0.15 s warm (about 0.25 s the first time, while bytecode compiles): asyncio 44 ms,
pydantic 40 ms, starlette 17 ms, and indah's own modules the rest. The bound is deliberately
loose so a slow CI box does not flake; it catches an accidental eager import of something
heavy, which is the realistic way this regresses.
"""

import subprocess
import sys

import pytest

_HEAVY = ("numpy", "PIL", "matplotlib", "pandas", "uvicorn", "torch", "transformers", "yaml")

_PROBE = """
import sys, time
t = time.perf_counter()
import indah
elapsed = time.perf_counter() - t
heavy = [m for m in %r if m in sys.modules]
print(elapsed, ",".join(heavy))
"""


def _import_once() -> tuple[float, list[str]]:
    out = subprocess.run(
        [sys.executable, "-c", _PROBE % (_HEAVY,)], capture_output=True, text=True, check=True
    ).stdout.split()
    return float(out[0]), (out[1].split(",") if len(out) > 1 else [])


@pytest.mark.unit
def test_import_is_fast_and_pulls_no_heavy_libraries():
    # Best of three: a host stall (seen on a busy WSL box: one 27 s outlier next to 0.2 s runs)
    # says nothing about indah, but a real regression is slow every time.
    runs = [_import_once() for _ in range(3)]
    loaded = runs[0][1]
    assert not loaded, f"import indah eagerly pulled in {loaded}; import it lazily"
    elapsed = min(t for t, _ in runs)
    assert elapsed < 1.5, f"import indah took {elapsed:.2f}s (was about 0.15 s)"
