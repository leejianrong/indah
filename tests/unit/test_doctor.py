"""The deploy doctor's diagnosis and gate (IND-205), without an app around them."""

import pytest

from indah.doctor import Gate, diagnose, make_gate

pytestmark = pytest.mark.unit


def facts(**over):
    base = {
        "request": {
            "resolved_client": "172.16.1.2",
            "socket_peer": "172.16.1.2",
            "resolved_client_is_trusted": False,
            "cookie_sent": True,
        },
        "headers": {},
        "trusted_proxies": [],
        "process": {"requests_answered": 3},
        "drain": {"draining": False},
        "settings": {"node_header": True},
    }
    for key, value in over.items():
        base[key] = {**base[key], **value} if isinstance(value, dict) else value
    return base


def texts(found, level=None):
    return [w["text"] for w in found if level is None or w["level"] == level]


def test_a_quiet_direct_request_has_no_warning():
    assert texts(diagnose(facts()), "warn") == []


def test_forwarding_headers_with_no_trusted_proxies_is_the_first_warning():
    found = diagnose(facts(headers={"x-forwarded-for": "1.2.3.4, 66.1.1.1"}))
    warn = texts(found, "warn")
    assert len(warn) == 1
    assert "trusted_proxies is empty" in warn[0]
    assert "x-forwarded-for" in warn[0] and "172.16.1.2" in warn[0]


def test_a_peer_that_is_not_trusted_means_the_headers_were_ignored():
    found = diagnose(facts(headers={"x-forwarded-for": "1.2.3.4"}, trusted_proxies=["10.0.0.0/8"]))
    assert any("not in trusted_proxies" in t for t in texts(found, "warn"))


def test_a_client_that_is_itself_a_trusted_proxy_hides_the_visitor():
    found = diagnose(
        facts(
            request={"resolved_client": "10.1.1.1", "resolved_client_is_trusted": True},
            trusted_proxies=["10.0.0.0/8"],
            headers={"x-forwarded-for": "10.1.1.1"},
        )
    )
    assert any("inside trusted_proxies" in t for t in texts(found, "warn"))


def test_the_gateway_naming_another_visitor_is_a_warning_with_the_fly_fix():
    """The default Fly mistake: Fly-Client-IP is the visitor, indah resolved the ingress IP."""
    found = diagnose(
        facts(
            request={"resolved_client": "66.241.124.81", "socket_peer": "172.16.1.2"},
            headers={"fly-client-ip": "122.1.2.3", "x-forwarded-for": "122.1.2.3, 66.241.124.81"},
            trusted_proxies=["172.16.0.0/12"],
        )
    )
    warn = " ".join(texts(found, "warn"))
    assert "122.1.2.3" in warn and "66.241.124.81" in warn
    assert "fly ips list" in warn


def test_matching_gateway_and_resolved_addresses_are_quiet():
    found = diagnose(
        facts(
            request={"resolved_client": "122.1.2.3"},
            headers={"fly-client-ip": "122.1.2.3", "x-forwarded-for": "122.1.2.3, 66.241.124.81"},
            trusted_proxies=["172.16.0.0/12", "66.241.124.81"],
        )
    )
    assert texts(found, "warn") == []


def test_draining_is_a_warning():
    found = diagnose(facts(drain={"draining": True}))
    assert any("draining" in t for t in texts(found, "warn"))


def test_the_several_processes_hint_always_shows_the_request_count():
    found = diagnose(facts())
    hint = [t for t in texts(found, "info") if "Several processes" in t]
    assert hint and "3 request" in hint[0]


def test_hints_to_turn_on_the_node_header_and_about_cookies():
    found = diagnose(facts(settings={"node_header": False}, request={"cookie_sent": False}))
    info = " ".join(texts(found, "info"))
    assert "node_header=True" in info and "no cookie" in info.lower()


def test_warnings_come_before_hints():
    found = diagnose(facts(drain={"draining": True}))
    levels = [w["level"] for w in found]
    assert levels == sorted(levels, key=lambda lv: lv != "warn")


# --- the gate


def test_make_gate_off_by_default():
    assert make_gate(None, auth=None, secure=False) is None
    assert make_gate(False, auth=None, secure=False) is None


def test_a_short_token_is_refused_and_the_message_names_the_source():
    with pytest.raises(ValueError, match="16"):
        make_gate("short", auth=None, secure=False)
    with pytest.raises(ValueError, match="INDAH_DOCTOR_TOKEN"):
        make_gate("short", auth=None, secure=False, source="INDAH_DOCTOR_TOKEN")


def test_true_needs_someone_to_be_logged_in():
    with pytest.raises(ValueError, match="secure=True"):
        make_gate(True, auth=None, secure=False)
    assert make_gate(True, auth=lambda r: None, secure=True) is not None


def test_a_non_string_non_bool_is_refused():
    with pytest.raises(ValueError):
        make_gate(123, auth=None, secure=False)


def test_token_comparison_and_the_lockout_clock():
    clock = [1000.0]
    gate = Gate(token="x" * 20, permission=False, now=lambda: clock[0])
    assert gate.token_ok("x" * 20)
    assert not gate.token_ok("y" * 20)
    assert not gate.token_ok(None) and not gate.token_ok("")
    for _ in range(gate.MAX_FAILURES):
        gate.record_failure("9.9.9.9")
    assert gate.blocked("9.9.9.9")
    assert not gate.blocked("8.8.8.8")
    clock[0] += gate.WINDOW_SECONDS + 1
    assert not gate.blocked("9.9.9.9")


def test_the_failure_table_is_bounded():
    gate = Gate(token="x" * 20, permission=False)
    for i in range(gate.MAX_TRACKED + 50):
        gate.record_failure(f"10.0.{i // 250}.{i % 250}")
    assert len(gate._failures) <= gate.MAX_TRACKED
