"""The training-dashboard example (examples/training_dashboard.py) stays runnable.

Smoke-checks the mock training loop streams loss points over the append op and
appends a run-history row per epoch, and that the Start button wires an async handler.
"""

import importlib.util
from pathlib import Path

import pytest

from indah.components import Column
from indah.session import Session
from indah.transport import Hub

_EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "training_dashboard.py"


def _load_example():
    spec = importlib.util.spec_from_file_location("training_dashboard_example", _EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.integration
async def test_training_streams_two_series_and_records_history():
    example = _load_example()
    monitor = example.TrainingMonitor()
    # Wire the monitor's streaming Chart into a session + hub so push emits patches.
    session = Session(Column(children=[monitor.curves]))
    hub = Hub()
    session.bind_hub(hub)

    await monitor.train(epochs=2, steps_per_epoch=5)  # small, fast run

    rows = [
        row
        for _, msg in hub.history()
        for change in msg.get("changes", [])
        if "append" in change and "data" in change["append"]
        for row in change["append"]["data"]
    ]
    assert len(rows) == 10  # 2 epochs x 5 steps, one append per step
    assert all(len(r) == 3 for r in rows)  # [step, train_loss, val_loss]
    assert monitor.history.value and len(monitor.history.value) == 2  # a row per epoch
    assert not monitor.running.value  # loop cleared the running flag


@pytest.mark.integration
def test_start_button_wires_an_async_training_handler():
    example = _load_example()
    session = example.build()
    button = next(c for c in session._by_id.values() if c.type == "button")
    result = session.dispatch(button.id, "click", {})
    assert result is not None and result.coro is not None  # async handler, run in background
    result.coro.close()  # don't actually run the full default loop in the test
