"""The route hint's settings (IND-197, ADR-0043): when it is on, and what it carries.

The hint is for Fly: a machine id the shell sends back as ``fly-force-instance-id``. It needs
``INDAH_CLUSTER_SECRET`` (never derived from ``secret=``); without it the hint stays off.
"""

import pytest

from indah.route import RouteHint, resolve_route_hint

SECRET = "a-cluster-secret-of-some-length"
FLY = {"FLY_MACHINE_ID": "e826010b63e458", "INDAH_CLUSTER_SECRET": SECRET}


@pytest.mark.unit
def test_auto_on_fly_with_a_cluster_secret_is_the_machine_id():
    hint = resolve_route_hint(environ=FLY)
    assert hint == RouteHint(hint="e826010b63e458", transport="fly")


@pytest.mark.unit
def test_auto_off_the_platform_is_off():
    assert resolve_route_hint(environ={"INDAH_CLUSTER_SECRET": SECRET}) is None
    assert resolve_route_hint(environ={}) is None


@pytest.mark.unit
def test_without_the_cluster_secret_the_hint_stays_off():
    assert resolve_route_hint(environ={"FLY_MACHINE_ID": "e826010b63e458"}) is None


@pytest.mark.unit
def test_the_secret_argument_wins_and_secret_is_never_a_stand_in():
    env = {"FLY_MACHINE_ID": "e826010b63e458", "INDAH_SECRET": SECRET}
    assert resolve_route_hint(environ=env) is None
    assert resolve_route_hint(cluster_secret=SECRET, environ=env) is not None
    # an explicit empty argument turns it off even when the variable is set
    assert resolve_route_hint(cluster_secret="", environ=FLY) is None


@pytest.mark.unit
def test_off_wins_over_everything():
    assert resolve_route_hint(mode="off", environ=FLY) is None
    assert resolve_route_hint(environ={**FLY, "INDAH_ROUTE_HINT": "off"}) is None


@pytest.mark.unit
def test_the_argument_beats_the_variable():
    env = {**FLY, "INDAH_ROUTE_HINT": "off"}
    assert resolve_route_hint(mode="fly", environ=env) is not None


@pytest.mark.unit
def test_fly_mode_without_a_machine_id_is_an_error():
    with pytest.raises(ValueError, match="FLY_MACHINE_ID"):
        resolve_route_hint(mode="fly", environ={"INDAH_CLUSTER_SECRET": SECRET})


@pytest.mark.unit
def test_peers_is_not_built_yet_and_junk_is_refused():
    with pytest.raises(ValueError, match="peers"):
        resolve_route_hint(mode="peers", environ=FLY)
    with pytest.raises(ValueError, match="INDAH_ROUTE_HINT"):
        resolve_route_hint(environ={**FLY, "INDAH_ROUTE_HINT": "sometimes"})


@pytest.mark.unit
@pytest.mark.parametrize("machine", ["bad id", "a" * 80, "10.0.0.1:80", "x\r\ny"])
def test_an_odd_machine_id_is_never_sent(machine):
    env = {"FLY_MACHINE_ID": machine, "INDAH_CLUSTER_SECRET": SECRET}
    assert resolve_route_hint(environ=env) is None


@pytest.mark.unit
def test_the_wire_form_and_the_file_query():
    hint = RouteHint(hint="e826010b63e458", transport="fly")
    assert hint.wire("web-1") == {"hint": "e826010b63e458", "node": "web-1", "transport": "fly"}
