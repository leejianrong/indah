"""Integration: a Chart streams points through the session dispatch + hub path.

The append patches carry only the new rows (O(point) on the wire), the same way
StreamText streams text - no protocol change (chart data rides props, ADR-0018).
"""

import pytest

from indah.components import Button, Chart, Column
from indah.session import Session
from indah.transport import Hub


def _appended_rows(hub: Hub) -> list[list]:
    rows: list[list] = []
    for _, msg in hub.history():
        for change in msg.get("changes", []):
            if "append" in change and "data" in change["append"]:
                rows.extend(change["append"]["data"])
    return rows


@pytest.mark.integration
def test_button_handler_streams_chart_points_as_append_patches():
    chart = Chart(series=["loss"], title="loss")

    def run():
        for step in range(3):
            chart.push(step, 1.0 / (step + 1))

    session = Session(Column(children=[chart, Button("run", on_click=run)]))
    hub = Hub()
    session.bind_hub(hub)

    result = session.dispatch("n2", "click", {})  # the Button

    assert result is not None
    assert result.coro is None  # a sync handler
    # The points arrived as append deltas (each row), not one big props replace.
    assert _appended_rows(hub) == [[0, 1.0], [1, 0.5], [2, 1.0 / 3]]
    # And the component's own buffer matches, so a resume snapshot is complete.
    assert chart.to_json()["props"]["data"] == [[0, 1.0], [1, 0.5], [2, 1.0 / 3]]
