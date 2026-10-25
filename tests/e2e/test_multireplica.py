"""Three replicas and a Redis behind two balancers (IND-211, ADR-0043).

Infra-heavy: needs Docker, builds an image and runs seven containers. It is opt-in
(``INDAH_TEST_MULTIREPLICA=1``, set by ``make test-multireplica``), carries its own mark, and is
not part of ``-m "unit or integration"``. The compose file is ``deploy/multireplica/compose.yml``:

* plain spray (``balancer:8081``): every request goes to a random replica, no affinity at all;
* simulated Fly (``balancer:8082``): honours ``fly-force-instance-id``, answers a plain 400 for a
  machine that is gone. This is a simulation, not Fly; the real run is
  ``docs/spikes/multi-replica-e2e.md``.

Scenarios: events sprayed over the replicas work with the route hint and fail loudly (409)
without it; a rolling restart with drain keeps a tab (reconnect, restore from Redis); a killed
owner gives one toast and the restored state; a replica without the cluster secret is visible
across the fleet; ``sticky_check.py --follow-route`` reports 20 of 20.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.multireplica

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "deploy" / "multireplica" / "compose.yml"
STICKY = ROOT / "deploy" / "probe" / "sticky_check.py"
DOCTOR_TOKEN = "doctor-token-for-the-test-only"
TOAST = "Reconnected. Your last action was not applied, please try it again."
REPLICAS = ("r1", "r2", "r3")

if not os.environ.get("INDAH_TEST_MULTIREPLICA"):
    pytest.skip("set INDAH_TEST_MULTIREPLICA=1 (make test-multireplica)", allow_module_level=True)

playwright_sync = pytest.importorskip("playwright.sync_api")
expect = playwright_sync.expect


def dc(*args: str, check: bool = True, timeout: float = 300) -> str:
    done = subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if check and done.returncode:
        raise RuntimeError(f"docker compose {' '.join(args)}: {done.stderr or done.stdout}")
    return done.stdout.strip()


def host_port(service: str, port: int) -> int:
    return int(dc("port", service, str(port)).rsplit(":", 1)[1])


def sticky(base: str, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(STICKY), base, "--machine-header", "x-indah-node", *extra],
        capture_output=True,
        text=True,
        timeout=120,
    )


def container_running(service: str) -> bool:
    return bool(dc("ps", "--status", "running", "-q", service, check=False))


def stop_with_drain(service: str) -> float:
    """SIGTERM (a drain), wait for the process to exit, return how long that took."""
    started = time.monotonic()
    dc("kill", "-s", "SIGTERM", service)
    deadline = started + 30
    while container_running(service):
        assert time.monotonic() < deadline, f"{service} did not exit after SIGTERM"
        time.sleep(0.2)
    return time.monotonic() - started


def bring_up(service: str) -> None:
    dc("up", "-d", "--no-recreate", "--wait", "--wait-timeout", "90", service)


@pytest.fixture(scope="module")
def fleet():
    t0 = time.monotonic()
    dc("up", "-d", "--build", "--wait", "--wait-timeout", "240", timeout=600)
    print(f"\nfleet up in {time.monotonic() - t0:.1f}s")
    ports = {"spray": host_port("balancer", 8081), "fly": host_port("balancer", 8082)}
    yield {
        "spray": f"http://127.0.0.1:{ports['spray']}",
        "fly": f"http://127.0.0.1:{ports['fly']}",
    }
    dc("--profile", "odd", "down", "-v", "--timeout", "5", check=False)


@pytest.fixture(autouse=True)
def all_replicas_up(fleet, request):
    """Every test starts with three healthy replicas, whatever the last one did to them."""
    for name in REPLICAS:
        if not container_running(name):
            bring_up(name)
    yield
    if request.session.testsfailed:
        print(dc("logs", "--no-color", "--tail", "60", check=False))


@pytest.fixture
def page(fleet):
    with playwright_sync.sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            yield browser.new_page()
        finally:
            browser.close()


def owner_of(page) -> str:
    text = page.get_by_text(re.compile(r"^built on n\d$")).first.inner_text()
    return {"n1": "r1", "n2": "r2", "n3": "r3"}[text.removeprefix("built on ")]


def count_is(page, n: int, timeout: float = 45_000) -> None:
    expect(page.get_by_text(f"count {n}", exact=True)).to_be_visible(timeout=timeout)


def click(page) -> None:
    page.get_by_role("button", name="Send an event").click()


# --- events sprayed over the replicas


def test_spray_without_the_hint_fails_loudly(fleet):
    """No affinity and no header: most events reach a replica that does not hold the tab."""
    out = sticky(fleet["spray"])
    print(out.stdout)
    assert "NOT STICKY" in out.stdout
    assert "409" in out.stdout, "a misrouted event must be refused loudly, not dropped"
    # And the refusal says why, in indah's own JSON.
    sid = "0" * 32
    r = httpx.post(
        f"{fleet['spray']}/api/event",
        json={"sid": sid, "component": "x", "event": "click", "payload": {}},
    )
    assert r.status_code == 409 and r.json()["error"] == "unknown_session"


def test_sticky_check_follow_route_is_20_of_20_on_simulated_fly(fleet):
    out = sticky(fleet["fly"], "--follow-route")
    print(out.stdout)
    assert out.returncode == 0, out.stderr
    assert "events handled on the stream's machine: 20 of 20" in out.stdout
    assert "patches that reached the tab's stream: 20 of 20" in out.stdout
    assert out.stdout.strip().endswith("STICKY")
    # The same run without the header is what the hint fixes.
    assert "NOT STICKY" in sticky(fleet["fly"]).stdout


def test_a_tab_keeps_working_through_the_simulated_fly(fleet, page):
    page.goto(fleet["fly"], wait_until="domcontentloaded")
    count_is(page, 0)
    sent: list[dict] = []
    page.on("request", lambda r: sent.append(r.headers) if r.url.endswith("/api/event") else None)
    owner = owner_of(page)
    for n in range(1, 11):
        click(page)
        count_is(page, n, timeout=15_000)
    assert len(sent) == 10
    assert {h["fly-force-instance-id"] for h in sent} == {
        {"r1": "n1", "r2": "n2", "r3": "n3"}[owner]
    }
    expect(page.get_by_text(TOAST)).to_have_count(0)


# --- a rolling restart with drain keeps the tab


@pytest.mark.parametrize("balancer", ["fly", "spray"])
def test_rolling_restart_with_drain_keeps_the_tab(fleet, page, balancer):
    page.goto(fleet[balancer], wait_until="domcontentloaded")
    count_is(page, 0)
    if balancer == "fly":  # the route hint makes the clicks reach the owner
        for n in (1, 2, 3):
            click(page)
            count_is(page, n, timeout=15_000)
        saved = 3
    else:  # no affinity: the clicks that miss are refused, so the test sets state by retry
        saved = 0
    time.sleep(1.2)  # a change is written to Redis about a quarter of a second after it
    timings = {}
    for name in REPLICAS:
        timings[name] = stop_with_drain(name)
        bring_up(name)
        # The same page, never reloaded: it reconnects and shows the restored state.
        count_is(page, saved)
        expect(page.get_by_text("live", exact=True)).to_be_visible(timeout=30_000)
    print(f"rolling restart ({balancer}): drain-and-exit seconds {timings}")
    if balancer == "fly":
        click(page)
        count_is(page, saved + 1, timeout=30_000)


# --- the owner is killed


def test_killed_owner_gives_one_toast_and_the_restored_state(fleet, page):
    # A toast fades after a few seconds, so count how many were ever shown, not how many are now.
    page.add_init_script(
        "window.__toasts = 0; new MutationObserver((ms) => ms.forEach((m) =>"
        " m.addedNodes.forEach((n) => { if (n.nodeType !== 1) return;"
        " const all = n.matches('.toast') ? [n] : [...n.querySelectorAll('.toast')];"
        " all.forEach((t) => {"
        " if (t.textContent.includes('Reconnected. Your')) window.__toasts++; });"
        " }))).observe(document, {subtree: true, childList: true});"
    )
    page.goto(fleet["fly"], wait_until="domcontentloaded")
    count_is(page, 0)
    for n in (1, 2):
        click(page)
        count_is(page, n, timeout=15_000)
    owner = owner_of(page)
    time.sleep(1.2)  # the value is in Redis before the process dies
    dc("kill", "-s", "SIGKILL", owner)
    click(page)  # the hint names a machine that is gone: the simulated Fly answers 400
    expect(page.get_by_text(TOAST)).to_be_visible(timeout=15_000)
    built = page.get_by_text(re.compile(r"^built on n\d$")).first
    expect(built).not_to_have_text(f"built on n{owner[1]}", timeout=30_000)  # rebuilt elsewhere
    count_is(page, 2)  # restored from Redis, not zero
    click(page)
    count_is(page, 3, timeout=30_000)
    assert page.evaluate("window.__toasts") == 1


# --- the cluster secret


def _doctor(base: str) -> dict:
    r = httpx.get(
        f"{base}/_indah/doctor?format=json",
        headers={"Authorization": f"Bearer {DOCTOR_TOKEN}"},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()


def test_a_replica_without_the_cluster_secret_is_visible_across_the_fleet(fleet):
    """A replica that lacks the secret sends no route hint, so its tabs are not pinned.

    Today the secret only switches the hint on (it signs nothing until the forwarder, IND-209),
    so "mismatch" is "missing": the doctor on that replica says route hint off, the others say
    fly, and the shell's init carries no route. A differing secret cannot be detected yet.
    """
    dc("--profile", "odd", "up", "-d", "--wait", "--wait-timeout", "90", "odd")
    odd = f"http://127.0.0.1:{host_port('odd', 8000)}"
    hints = {
        name: _doctor(url)["settings"]["route_hint"]
        for name, url in {n: f"http://127.0.0.1:{host_port(n, 8000)}" for n in REPLICAS}.items()
    }
    hints["odd"] = _doctor(odd)["settings"]["route_hint"]
    assert hints == {"r1": "fly", "r2": "fly", "r3": "fly", "odd": "off"}, hints
    out = sticky(odd, "--follow-route")
    assert out.returncode != 0
    assert "init carried no route" in (out.stdout + out.stderr)
    dc("--profile", "odd", "stop", "odd")
