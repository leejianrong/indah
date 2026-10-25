"""GET /metrics in a real app (IND-212): off by default, gated like the doctor, and it counts."""

import pytest
from starlette.testclient import TestClient

import indah
from indah import Policy, Principal, create_app

pytestmark = pytest.mark.integration

TOKEN = "metrics-token-0123456789"


def client(app, peer="172.16.1.2"):
    return TestClient(app, client=(peer, 50000))


def plain(**kw):
    return create_app(session_factory=lambda: indah.Session(indah.Text("hi")), **kw)


def series(response):
    return {
        k: v
        for k, v in (ln.split(" ") for ln in response.text.splitlines() if ln[:1] != "#" and ln)
    }


def auth(token=TOKEN):
    return {"Authorization": f"Bearer {token}"}


def test_off_by_default(monkeypatch):
    monkeypatch.delenv("INDAH_METRICS_TOKEN", raising=False)
    assert client(plain()).get("/metrics").status_code == 404


def test_the_doctor_token_does_not_open_metrics(monkeypatch):
    monkeypatch.delenv("INDAH_METRICS_TOKEN", raising=False)
    c = client(plain(doctor=TOKEN))
    assert c.get("/metrics", headers=auth()).status_code == 404


def test_a_token_gate_gives_a_plain_404_to_everyone_else(monkeypatch):
    monkeypatch.delenv("INDAH_METRICS_TOKEN", raising=False)
    c = client(plain(metrics=TOKEN))
    for r in (c.get("/metrics"), c.get("/metrics", headers=auth("nope-nope-nope-nope"))):
        assert r.status_code == 404
        assert r.text == "Not Found"


def test_the_token_gets_prometheus_text(monkeypatch):
    monkeypatch.delenv("INDAH_METRICS_TOKEN", raising=False)
    r = client(plain(metrics=TOKEN)).get("/metrics", headers=auth())
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain; version=0.0.4")
    assert r.headers["cache-control"] == "no-store"
    s = series(r)
    assert s["indah_sessions_open"] == "0"
    assert s["indah_streams_open"] == "0"
    assert s["indah_draining"] == "0"
    assert TOKEN not in r.text


def test_the_environment_variable_turns_it_on(monkeypatch):
    monkeypatch.setenv("INDAH_METRICS_TOKEN", TOKEN)
    assert client(plain()).get("/metrics", headers=auth()).status_code == 200


def test_a_short_token_is_refused_at_startup():
    with pytest.raises(ValueError, match="metrics token"):
        plain(metrics="short")


def test_it_needs_no_session_and_creates_none(monkeypatch):
    monkeypatch.delenv("INDAH_METRICS_TOKEN", raising=False)
    app = plain(metrics=TOKEN)
    c = client(app)
    c.get("/metrics", headers=auth())
    assert series(c.get("/metrics", headers=auth()))["indah_sessions_open"] == "0"


def test_events_and_errors_count(monkeypatch):
    monkeypatch.delenv("INDAH_METRICS_TOKEN", raising=False)

    def boom():
        raise RuntimeError("boom")

    def factory():
        return indah.Session(
            indah.Column(
                children=[
                    indah.Button("ok", on_click=lambda: None),
                    indah.Button("bad", on_click=boom),
                ]
            )
        )

    app = create_app(session_factory=factory, metrics=TOKEN)
    c = client(app)
    # a session must exist: open one the way the shell does
    handle = app.state.store.get_or_create("s1")
    ok_id, bad_id = (n.id for n in handle.session.root.children)
    for node in (ok_id, ok_id, bad_id):
        r = c.post("/api/event", json={"sid": "s1", "component": node, "event": "click"})
        assert r.status_code == 200
    s = series(c.get("/metrics", headers=auth()))
    assert s["indah_events_total"] == "3"
    assert s["indah_errors_total"] == "1"
    assert s["indah_sessions_open"] == "1"


def test_drain_state_shows(monkeypatch):
    monkeypatch.delenv("INDAH_METRICS_TOKEN", raising=False)
    app = plain(metrics=TOKEN)
    c = client(app)
    app.state.drain.draining = True
    assert series(c.get("/metrics", headers=auth()))["indah_draining"] == "1"


def test_a_fly_file_replay_counts_as_a_forward(monkeypatch):
    monkeypatch.setenv("FLY_MACHINE_ID", "e826010b63e458")
    monkeypatch.setenv("INDAH_CLUSTER_SECRET", "a-cluster-secret-of-some-length")
    monkeypatch.delenv("INDAH_ROUTE_HINT", raising=False)
    monkeypatch.delenv("INDAH_METRICS_TOKEN", raising=False)
    c = client(plain(metrics=TOKEN))
    r = c.get("/api/file/not-here/tok", params={"r": "d8d1e2a5f3b7c9"})
    assert r.headers["fly-replay"] == "instance=d8d1e2a5f3b7c9"
    s = series(c.get("/metrics", headers=auth()))
    assert s["indah_forwards_total"] == "1"
    assert s["indah_forward_failures_total"] == "0"


def principal_from_header(request):
    name = request.headers.get("x-user")
    return Principal(id=name, roles={"ops"}) if name else None


def test_the_permission_gate_admits_only_a_principal_holding_metrics():
    app = create_app(
        session_factory=lambda: indah.Session(indah.Text("hi")),
        secure=True,
        secret="s" * 24,
        auth=principal_from_header,
        policy=Policy({"ops": ["metrics"], "viewer": ["read"]}),
        metrics=True,
    )
    c = client(app)
    assert c.get("/metrics").status_code == 404
    assert c.get("/metrics", headers={"x-user": "ada"}).status_code == 200


def test_metrics_true_without_a_login_is_refused_at_startup():
    with pytest.raises(ValueError, match="secure=True"):
        plain(metrics=True)
