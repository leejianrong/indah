"""The hybrid-charting example (examples/charts.py) stays runnable.

Smoke-checks the example's session in CI: the client Chart streams points through
its async handler, and the static/reactive panels build (matplotlib is optional -
the example falls back to an inline-SVG note when it is absent).
"""

import importlib.util
from pathlib import Path

import pytest

from indah.transport import Hub

_EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "charts.py"


def _load_example():
    spec = importlib.util.spec_from_file_location("charts_example", _EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.integration
def test_example_builds_a_session_with_chart_nodes():
    example = _load_example()
    session = example.build()
    types = {c.type for c in session._by_id.values()}
    assert "chart" in types  # at least the live + reactive client charts


@pytest.mark.integration
async def test_run_training_streams_points_over_the_append_op():
    example = _load_example()
    session = example.build()
    hub = Hub()
    session.bind_hub(hub)

    button = next(c for c in session._by_id.values() if c.type == "button")
    result = session.dispatch(button.id, "click", {})
    assert result is not None and result.coro is not None  # async training handler
    await result.coro

    # Training pushed points as append deltas (rows), not one big replace.
    rows = [
        row
        for _, msg in hub.history()
        for change in msg.get("changes", [])
        if "append" in change and "data" in change["append"]
        for row in change["append"]["data"]
    ]
    assert len(rows) == 80  # one append per step
    assert all(len(r) == 2 for r in rows)  # [step, loss]
