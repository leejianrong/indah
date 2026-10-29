"""The cellular-automaton example (examples/automaton.py) builds and responds."""

import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest

from indah.transport import Hub

_EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "automaton.py"


def _load_example():
    spec = importlib.util.spec_from_file_location("automaton_integration_example", _EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _by_type(session, type_name):
    return [c for c in session._by_id.values() if c.type == type_name]


def _button(session, label):
    return next(c for c in _by_type(session, "button") if c.reactive_props()["label"]() == label)


def _stat(session, label):
    stat = next(c for c in _by_type(session, "stat") if c.static_props()["label"] == label)
    return stat.reactive_props()["value"]()


@pytest.mark.integration
def test_example_builds_with_the_expected_components():
    session = _load_example().build()
    types = {c.type for c in session._by_id.values()}
    assert {"heatmap", "select", "slider", "button", "stat"} <= types


@pytest.mark.integration
def test_step_advances_the_generation_counter_and_pushes_a_new_field():
    example = _load_example()
    session = example.build()
    session.bind_hub(Hub())
    heatmap = _by_type(session, "heatmap")[0]
    before = heatmap.reactive_props()["z"]()
    assert _stat(session, "Generation") == "0"
    session.dispatch(_button(session, "Step").id, "click", {})
    assert _stat(session, "Generation") == "1"
    assert heatmap.reactive_props()["z"]() != before


@pytest.mark.integration
def test_grid_size_slider_resizes_the_field_and_restarts():
    example = _load_example()
    session = example.build()
    session.bind_hub(Hub())
    session.dispatch(_button(session, "Step").id, "click", {})
    size_slider = next(
        s for s in _by_type(session, "slider") if s.static_props()["label"] == "Grid size"
    )
    session.dispatch(size_slider.id, "input", {"value": 24})
    z = _by_type(session, "heatmap")[0].reactive_props()["z"]()
    assert len(z) == 24 and len(z[0]) == 24
    assert _stat(session, "Generation") == "0"


@pytest.mark.integration
async def test_play_runs_until_paused_and_streams_generations():
    example = _load_example()
    session = example.build()
    session.bind_hub(Hub())
    # Fastest speed; the loop checks the pause flag after every generation.
    speed = next(s for s in _by_type(session, "slider") if "Speed" in s.static_props()["label"])
    session.dispatch(speed.id, "input", {"value": 30})
    result = session.dispatch(_button(session, "Play").id, "click", {})
    assert result is not None and result.coro is not None
    task = asyncio.ensure_future(result.coro)
    await asyncio.sleep(0.25)
    session.dispatch(_button(session, "Pause").id, "click", {})
    await asyncio.wait_for(task, timeout=2)
    assert int(_stat(session, "Generation")) >= 2


@pytest.mark.integration
async def test_play_stops_at_the_generation_cap():
    example = _load_example()
    model = example.Automaton()
    model.board.generation = example.MAX_GENERATIONS - 2
    model.speed.set(30)
    await asyncio.wait_for(model.play(), timeout=5)
    assert model.board.generation == example.MAX_GENERATIONS
    assert not model.playing.value
    assert "cap" in model.status.value


@pytest.mark.integration
def test_choosing_a_named_rule_switches_to_the_1d_world():
    example = _load_example()
    session = example.build()
    session.bind_hub(Hub())
    select = _by_type(session, "select")[0]
    session.dispatch(select.id, "input", {"value": "rule-90"})
    z = _by_type(session, "heatmap")[0].reactive_props()["z"]()
    assert sum(map(sum, z)) == 1  # one live seed cell
    session.dispatch(_button(session, "Step").id, "click", {})
    z = _by_type(session, "heatmap")[0].reactive_props()["z"]()
    assert sum(map(sum, z)) == 3  # rule 90: the seed row plus two cells beneath it
