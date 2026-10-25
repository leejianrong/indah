"""The /metrics text and its counters (IND-212), without an app around them."""

import pytest

from indah.doctor import make_gate
from indah.metrics import Metrics, render

pytestmark = pytest.mark.unit


def lines(text):
    return [ln for ln in text.splitlines() if ln and not ln.startswith("#")]


def test_counters_start_at_zero_and_count():
    m = Metrics()
    assert (m.events, m.errors, m.forwards, m.forward_failures) == (0, 0, 0, 0)
    m.events += 2
    m.errors += 1
    out = dict(ln.split(" ") for ln in lines(render(m, sessions=3, streams=5, draining=False)))
    assert out["indah_events_total"] == "2"
    assert out["indah_errors_total"] == "1"
    assert out["indah_sessions_open"] == "3"
    assert out["indah_streams_open"] == "5"
    assert out["indah_draining"] == "0"
    assert out["indah_forwards_total"] == "0"
    assert out["indah_forward_failures_total"] == "0"


def test_drain_state_is_a_gauge():
    out = render(Metrics(), sessions=0, streams=0, draining=True)
    assert "indah_draining 1" in out.splitlines()


def test_every_series_has_help_and_type():
    text = render(Metrics(), sessions=1, streams=1, draining=False)
    names = {ln.split(" ")[0].split("{")[0] for ln in lines(text)}
    for name in names:
        assert f"# HELP {name} " in text
        assert f"# TYPE {name} " in text
    assert "# TYPE indah_events_total counter" in text
    assert "# TYPE indah_streams_open gauge" in text


def test_an_unknown_count_is_left_out_not_zero():
    text = render(Metrics(), sessions=None, streams=0, draining=False)
    assert "indah_sessions_open" not in text


def test_the_metrics_gate_names_its_own_setting():
    with pytest.raises(ValueError, match="metrics token"):
        make_gate("short", auth=None, secure=False, name="metrics", permission="metrics")
    with pytest.raises(ValueError, match="metrics=True"):
        make_gate(True, auth=None, secure=False, name="metrics", permission="metrics")
