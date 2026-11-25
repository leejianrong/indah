"""Peer forwarding between two in-process apps (IND-209, ADR-0043 Tier C).

Two apps share a cluster secret and stand for two pods at ``127.0.0.1`` and ``127.0.0.2``. A
loopback forwarder carries a forward from one to the other's ASGI app, so nothing opens a socket.
The owner holds the session and a subscriber on its hub (the tab's stream); the receiver holds
nothing.
"""

import json
import time

import httpx
import pytest

from indah import Limits, Principal, Rate, create_app
from indah.components import Button, Column, Text, Upload
from indah.context import ConnectionInfo
from indah.forward import PeerConfig, forward_signature, sign_hint
from indah.reactive import Signal
from indah.session import Session

# the tests open the owner's session themselves; the conftest must not open one on the receiver too
pytestmark = [pytest.mark.integration, pytest.mark.raw_events]
SECRET = "a-cluster-secret-of-some-length"
KEY = SECRET.encode()
A, B = "127.0.0.1", "127.0.0.2"
PORT = 9100


class Loopback:
    """The ``Forwarder`` interface with no network: calls a peer's ASGI app by address."""

    def __init__(self):
        self.apps: dict[tuple[str, int], object] = {}
        self.calls: list[dict] = []
        self.fail: Exception | None = None

    async def forward(self, address, port, path, headers, body):
        self.calls.append(
            {"to": (address, port), "path": path, "headers": dict(headers), "body": body}
        )
        if self.fail:
            raise self.fail
        app = self.apps[(address, port)]
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://p"
        ) as c:
            r = await c.post(path, content=body, headers=dict(headers))
        return r.status_code, r.content


def _factory(log: list):
    def build(ctx):
        n = Signal(0)

        def click():
            log.append((ctx.user.id if ctx.user else None, n.value))
            n.set(n.value + 1)

        def got(f):
            log.append(("upload", f.filename))

        return Session(
            Column(children=[Button("go", on_click=click), Text(lambda: str(n.value)), Upload(got)])
        )

    return build


@pytest.fixture
def pods(monkeypatch):
    for name in ("FLY_MACHINE_ID", "INDAH_ROUTE_HINT", "INDAH_PEERS", "INDAH_CLUSTER_SECRET"):
        monkeypatch.delenv(name, raising=False)
    loop = Loopback()
    log: list = []
    audits: list = []

    def make(address, node, **kw):
        monkeypatch.setenv("INDAH_NODE", node)
        app = create_app(
            session_factory=_factory(log),
            cluster_secret=SECRET,
            peers=PeerConfig(peers="self", address=address, port=PORT, forwarder=loop),
            audit=audits.append,
            **kw,
        )
        loop.apps[(address, PORT)] = app
        return app

    class Pods:
        pass

    p = Pods()
    p.make, p.loop, p.log, p.audits = make, loop, log, audits
    return p


def _client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _owner_session(app, sid="t1", user=None):
    handle = app.state.store.get_or_create(sid, ConnectionInfo(user=user))
    return handle, handle.hub.subscribe()


def _event(sid="t1"):
    return {"sid": sid, "component": "n1", "event": "click"}


def _hint(address=A, port=PORT, at=None):
    return sign_hint(KEY, address, port, time.time() if at is None else at)


async def _post(app, body=None, hint=None, sid="t1"):
    headers = {"X-Indah-Route": hint} if hint else {}
    async with _client(app) as c:
        return await c.post("/api/event", json=body or _event(sid), headers=headers)


async def test_init_carries_a_signed_peers_hint(pods):
    a = pods.make(A, "pod-a")
    route = a.state.route_hint.wire("pod-a")
    assert route["transport"] == "peers" and route["node"] == "pod-a"
    from indah.forward import verify_hint

    assert verify_hint(KEY, route["hint"], own_port=PORT) == (A, PORT)


async def test_an_event_that_lands_on_the_wrong_pod_reaches_the_owner(pods):
    owner, receiver = pods.make(A, "pod-a"), pods.make(B, "pod-b")
    handle, queue = _owner_session(owner)
    reply = await _post(receiver, hint=_hint(A))
    assert reply.status_code == 200 and reply.json() == {"ok": True}
    assert pods.log == [(None, 0)]  # the handler ran, on the owner's signals
    assert handle.session.snapshot()["children"][1]["props"]["text"] == "1"
    assert queue.get_nowait() is not None  # the patch went to the owner's stream
    assert receiver.state.store.get("t1") is None  # and nothing was built on the receiver
    assert pods.loop.calls[0]["to"] == (A, PORT)
    assert receiver.state.peers.stats["ok"] == 1 and owner.state.peers.stats["received"] == 1


async def test_a_hint_that_names_this_pod_is_handled_here_without_a_call(pods):
    owner, _ = pods.make(A, "pod-a"), pods.make(B, "pod-b")
    _owner_session(owner)
    assert (await _post(owner, hint=_hint(A))).status_code == 200
    assert pods.loop.calls == []


@pytest.mark.parametrize(
    "hint",
    [
        "junk",
        "",
        sign_hint(b"another-secret-of-some-length!", A, PORT, time.time()),  # wrong key
        sign_hint(KEY, "8.8.8.8", PORT, time.time()),  # public address, even when signed
        sign_hint(KEY, A, PORT + 1, time.time()),  # not this app's port
        sign_hint(KEY, A, PORT, time.time() - 3 * 86400),  # expired
    ],
)
async def test_a_bad_hint_never_makes_a_connection(pods, hint):
    pods.make(A, "pod-a")
    receiver = pods.make(B, "pod-b")
    reply = await _post(receiver, hint=hint)
    assert reply.status_code == 409 and reply.json()["error"] == "unknown_session"
    assert pods.loop.calls == []


async def test_a_tampered_hint_is_refused(pods):
    pods.make(A, "pod-a")
    receiver = pods.make(B, "pod-b")
    body, mac = _hint(A).split(".")
    forged = sign_hint(KEY, "10.1.1.1", PORT, time.time()).split(".")[0] + "." + mac
    assert (await _post(receiver, hint=forged)).status_code == 409
    assert pods.loop.calls == []


async def test_an_owner_that_cannot_be_reached_is_a_loud_409(pods):
    pods.make(A, "pod-a")
    receiver = pods.make(B, "pod-b")
    pods.loop.fail = TimeoutError()
    reply = await _post(receiver, hint=_hint(A))
    assert reply.status_code == 409 and reply.json()["error"] == "owner_unreachable"
    assert len(pods.loop.calls) == 1  # no retry
    assert receiver.state.peers.stats["failed"] == 1


async def test_an_owner_that_lost_the_session_says_unknown_session(pods):
    pods.make(A, "pod-a")  # restarted: holds nothing
    receiver = pods.make(B, "pod-b")
    reply = await _post(receiver, hint=_hint(A))
    assert reply.status_code == 409 and reply.json()["error"] == "unknown_session"


async def test_a_stale_owner_with_no_live_stream_refuses_instead_of_eating_the_click(pods):
    owner, receiver = pods.make(A, "pod-a"), pods.make(B, "pod-b")
    owner.state.store.get_or_create("t1", ConnectionInfo())  # a session, but no subscriber
    reply = await _post(receiver, hint=_hint(A))
    assert reply.status_code == 409 and pods.log == []


async def test_the_audit_record_names_the_pod_that_forwarded_it(pods):
    owner, receiver = pods.make(A, "pod-a"), pods.make(B, "pod-b")
    _owner_session(owner)
    await _post(receiver, hint=_hint(A))
    assert [e.forwarded_by for e in pods.audits] == ["pod-b"]
    await _post(owner)  # a local event has no sender
    assert pods.audits[-1].forwarded_by is None


async def test_the_rate_limit_counts_at_the_receiver_only(pods):
    limits = Limits(rate={"/api/event": Rate(per_second=0.001, burst=3)})
    owner, receiver = pods.make(A, "pod-a", limits=limits), pods.make(B, "pod-b", limits=limits)
    _owner_session(owner)
    codes = [(await _post(receiver, hint=_hint(A))).status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]  # the owner did not count them a second time
    assert [(await _post(owner)).status_code for _ in range(3)] == [200, 200, 200]  # its own budget


async def _forward_to(owner, **over):
    """Build a valid forward for the owner and send it directly, with fields overridden."""
    body = json.dumps(_event()).encode()
    fields = dict(
        timestamp=str(int(time.time())),
        nonce="n1",
        sender="pod-b",
        kind="event",
        content_type="application/json",
        body=body,
        blob="",
    )
    fields.update(over)
    sig = forward_signature(KEY, **fields)
    headers = {
        "Content-Type": fields["content_type"],
        "X-Indah-Forward-Ts": fields["timestamp"],
        "X-Indah-Forward-Nonce": fields["nonce"],
        "X-Indah-Forward-Sender": fields["sender"],
        "X-Indah-Forward-Kind": fields["kind"],
        "X-Indah-Forward-Principal": fields["blob"],
        "X-Indah-Forward-Sig": sig,
    }
    async with _client(owner) as c:
        return await c.post("/_indah/forward", content=fields["body"], headers=headers)


async def test_the_forward_endpoint_accepts_a_good_one_once_and_refuses_the_replay(pods):
    owner = pods.make(A, "pod-a")
    _owner_session(owner)
    stamp = str(int(time.time()))
    assert (await _forward_to(owner, timestamp=stamp)).status_code == 200
    assert (
        await _forward_to(owner, timestamp=stamp)
    ).status_code == 403  # the same signature again
    assert owner.state.peers.stats["refused"] == 1


async def test_the_forward_endpoint_refuses_stale_future_and_tampered_forwards(pods):
    owner = pods.make(A, "pod-a")
    _owner_session(owner)
    assert (await _forward_to(owner, timestamp=str(int(time.time()) - 120))).status_code == 403
    assert (await _forward_to(owner, timestamp=str(int(time.time()) + 120))).status_code == 403
    async with _client(owner) as c:  # no signature at all
        assert (await c.post("/_indah/forward", json=_event())).status_code == 403
    # a body changed after signing: sign one body, send another
    body = json.dumps(_event()).encode()
    stamp = str(int(time.time()))
    sig = forward_signature(
        KEY,
        timestamp=stamp,
        nonce="n",
        sender="x",
        kind="event",
        content_type="application/json",
        body=body,
        blob="",
    )
    headers = {
        "Content-Type": "application/json",
        "X-Indah-Forward-Ts": stamp,
        "X-Indah-Forward-Nonce": "n",
        "X-Indah-Forward-Sender": "x",
        "X-Indah-Forward-Kind": "event",
        "X-Indah-Forward-Principal": "",
        "X-Indah-Forward-Sig": sig,
    }
    async with _client(owner) as c:
        other = json.dumps({**_event(), "event": "input"}).encode()
        assert (await c.post("/_indah/forward", content=other, headers=headers)).status_code == 403
    assert pods.log == []  # nothing ran


async def test_the_forward_endpoint_is_not_mounted_without_peers(monkeypatch):
    for name in ("FLY_MACHINE_ID", "INDAH_PEERS", "INDAH_CLUSTER_SECRET"):
        monkeypatch.delenv(name, raising=False)
    app = create_app(session_factory=_factory([]), cluster_secret=SECRET)
    async with _client(app) as c:
        assert (await c.post("/_indah/forward", json={})).status_code in (404, 405)
    assert app.state.peers is None


async def test_an_upload_is_forwarded_to_the_owner(pods):
    owner, receiver = pods.make(A, "pod-a"), pods.make(B, "pod-b")
    _owner_session(owner)
    async with _client(receiver) as c:
        reply = await c.post(
            "/api/upload",
            data={"component": "n3", "sid": "t1"},
            files={"file": ("a.txt", b"hello")},
            headers={"X-Indah-Route": _hint(A)},
        )
    assert reply.status_code == 200 and reply.json()["files"] == ["a.txt"]
    assert pods.log == [("upload", "a.txt")]
    assert pods.loop.calls[0]["headers"]["X-Indah-Forward-Kind"] == "upload"


async def test_a_draining_owner_still_answers_its_own_tabs_forwards(pods):
    owner, receiver = pods.make(A, "pod-a"), pods.make(B, "pod-b")
    _owner_session(owner)
    owner.state.drain.draining = True
    assert (await _post(receiver, hint=_hint(A))).status_code == 200


async def test_secure_forward_runs_as_the_principal_the_receiver_authenticated(pods, monkeypatch):
    people = {"alice": Principal(id="alice", roles={"admin"})}

    def who(request):
        return people.get(request.headers.get("x-user", ""))

    monkeypatch.setenv("INDAH_NODE", "pod-a")
    owner = create_app(
        session_factory=_factory(pods.log),
        secure=True,
        secret="s" * 40,
        auth=who,
        cluster_secret=SECRET,
        audit=pods.audits.append,
        peers=PeerConfig(peers="self", address=A, port=PORT, forwarder=pods.loop),
    )
    monkeypatch.setenv("INDAH_NODE", "pod-b")
    receiver = create_app(
        session_factory=_factory(pods.log),
        secure=True,
        secret="s" * 40,
        auth=who,
        cluster_secret=SECRET,
        peers=PeerConfig(peers="self", address=B, port=PORT, forwarder=pods.loop),
    )
    pods.loop.apps[(A, PORT)] = owner
    token = owner.state.signer.mint(people["alice"])
    sid = token.split(".")[0]
    owner.state.store.get_or_create(sid, ConnectionInfo(user=people["alice"])).hub.subscribe()

    async with _client(receiver) as c:
        anon = await c.post("/api/event", json=_event(token), headers={"X-Indah-Route": _hint(A)})
        ok = await c.post(
            "/api/event", json=_event(token), headers={"X-Indah-Route": _hint(A), "X-User": "alice"}
        )
    assert anon.status_code == 401 and pods.loop.calls[0:0] == []  # never forwarded
    assert ok.status_code == 200
    assert pods.log == [("alice", 0)]  # the handler saw the forwarded principal
    assert [(e.user, e.forwarded_by) for e in pods.audits] == [("alice", "pod-b")]


async def test_the_doctor_page_shows_forwarding_without_secrets(pods):
    owner, receiver = (
        pods.make(A, "pod-a", doctor="doc-token-doc-token"),
        pods.make(B, "pod-b", doctor="doc-token-doc-token"),
    )
    _owner_session(owner)
    await _post(receiver, hint=_hint(A))
    async with _client(receiver) as c:
        got = await c.get(
            "/_indah/doctor?format=json", headers={"Authorization": "Bearer doc-token-doc-token"}
        )
    assert got.status_code == 200
    facts = got.json()["settings"]["peer_forwarding"]
    assert facts["forwarded"] == 1 and facts["ok"] == 1 and facts["peers_resolved"] == 1
    assert SECRET not in got.text
    assert "127.0.0.2" not in got.text and "pod-b|" not in got.text  # no address, no hint
