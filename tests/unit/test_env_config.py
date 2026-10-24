"""create_app reads documented INDAH_* variables when an argument is not given (IND-202)."""

import logging

import pytest

import indah
from indah.hardening import Limits
from indah.proxy import parse_trusted

VARIABLES = (
    "INDAH_SECRET",
    "INDAH_SECRETS",
    "INDAH_TRUSTED_PROXIES",
    "INDAH_ALLOWED_ORIGINS",
    "INDAH_CSP",
    "INDAH_DRAIN_SECONDS",
    "INDAH_FACTORY_TIMEOUT",
    "INDAH_COMPRESS",
    "INDAH_LIMITS",
    "INDAH_WARN_UNTRUSTED_FORWARDING",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in VARIABLES:
        monkeypatch.delenv(name, raising=False)


def _factory():
    return indah.Session(indah.Text("hi"))


@pytest.mark.unit
def test_no_variable_set_changes_nothing():
    app = indah.create_app(session_factory=_factory)
    assert app.state.trusted_proxies == ()
    assert app.state.allowed_origins == frozenset()
    assert app.state.csp is None
    assert app.state.compress is True
    assert app.state.drain.seconds == 10.0
    assert app.state.store.factory_timeout == 1.0
    assert app.state.proxy_notice.enabled is True
    assert app.state.env_used == ()


@pytest.mark.unit
def test_trusted_proxies_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("INDAH_TRUSTED_PROXIES", "172.16.0.0/12, 66.241.124.81")
    app = indah.create_app(session_factory=_factory)
    assert app.state.trusted_proxies == parse_trusted(["172.16.0.0/12", "66.241.124.81"])
    assert "INDAH_TRUSTED_PROXIES" in app.state.env_used


@pytest.mark.unit
def test_an_explicit_argument_wins_even_when_empty(monkeypatch):
    monkeypatch.setenv("INDAH_TRUSTED_PROXIES", "10.0.0.0/8")
    app = indah.create_app(session_factory=_factory, trusted_proxies=())
    assert app.state.trusted_proxies == ()
    assert "INDAH_TRUSTED_PROXIES" not in app.state.env_used
    other = indah.create_app(session_factory=_factory, trusted_proxies=["192.168.0.0/16"])
    assert other.state.trusted_proxies == parse_trusted(["192.168.0.0/16"])


@pytest.mark.unit
def test_a_blank_variable_counts_as_not_set(monkeypatch):
    monkeypatch.setenv("INDAH_TRUSTED_PROXIES", "  ")
    monkeypatch.setenv("INDAH_COMPRESS", "")
    app = indah.create_app(session_factory=_factory)
    assert app.state.trusted_proxies == ()
    assert app.state.compress is True


@pytest.mark.unit
@pytest.mark.parametrize("value", ["*", "10.0.0.0/8, *", "not-an-ip", "0.0.0.0/0"])
def test_bad_trusted_proxies_names_the_variable(monkeypatch, value):
    monkeypatch.setenv("INDAH_TRUSTED_PROXIES", value)
    with pytest.raises(ValueError, match="INDAH_TRUSTED_PROXIES"):
        indah.create_app(session_factory=_factory)


@pytest.mark.unit
def test_allowed_origins(monkeypatch):
    monkeypatch.setenv(
        "INDAH_ALLOWED_ORIGINS", "https://app.example.com, https://b.example.com:8443/"
    )
    app = indah.create_app(session_factory=_factory)
    assert app.state.allowed_origins == frozenset(
        {"https://app.example.com", "https://b.example.com:8443"}
    )
    monkeypatch.setenv("INDAH_ALLOWED_ORIGINS", "app.example.com")
    with pytest.raises(ValueError, match="INDAH_ALLOWED_ORIGINS"):
        indah.create_app(session_factory=_factory)


@pytest.mark.unit
def test_csp_strict_or_off(monkeypatch):
    monkeypatch.setenv("INDAH_CSP", "strict")
    assert indah.create_app(session_factory=_factory).state.csp == "strict"
    monkeypatch.setenv("INDAH_CSP", "off")
    assert indah.create_app(session_factory=_factory).state.csp is None
    monkeypatch.setenv("INDAH_CSP", "default-src *")
    with pytest.raises(ValueError, match="INDAH_CSP"):
        indah.create_app(session_factory=_factory)
    monkeypatch.setenv("INDAH_CSP", "strict")
    assert indah.create_app(session_factory=_factory, csp=None).state.csp is None


@pytest.mark.unit
def test_drain_and_factory_timeout(monkeypatch):
    monkeypatch.setenv("INDAH_DRAIN_SECONDS", "25")
    monkeypatch.setenv("INDAH_FACTORY_TIMEOUT", "2.5")
    app = indah.create_app(session_factory=_factory)
    assert app.state.drain.seconds == 25.0
    assert app.state.store.factory_timeout == 2.5
    assert indah.create_app(session_factory=_factory, drain_seconds=3).state.drain.seconds == 3.0
    monkeypatch.setenv("INDAH_DRAIN_SECONDS", "soon")
    with pytest.raises(ValueError, match="INDAH_DRAIN_SECONDS"):
        indah.create_app(session_factory=_factory)
    monkeypatch.setenv("INDAH_DRAIN_SECONDS", "-1")
    with pytest.raises(ValueError, match="INDAH_DRAIN_SECONDS"):
        indah.create_app(session_factory=_factory)
    monkeypatch.setenv("INDAH_DRAIN_SECONDS", "1")
    monkeypatch.setenv("INDAH_FACTORY_TIMEOUT", "0")
    with pytest.raises(ValueError, match="INDAH_FACTORY_TIMEOUT"):
        indah.create_app(session_factory=_factory)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1", True),
        ("true", True),
        ("Yes", True),
        ("on", True),
        ("0", False),
        ("false", False),
        ("No", False),
        ("off", False),
    ],
)
def test_booleans(monkeypatch, value, expected):
    monkeypatch.setenv("INDAH_COMPRESS", value)
    monkeypatch.setenv("INDAH_WARN_UNTRUSTED_FORWARDING", value)
    app = indah.create_app(session_factory=_factory)
    assert app.state.compress is expected
    assert app.state.proxy_notice.enabled is expected
    assert indah.create_app(session_factory=_factory, compress=not expected).state.compress is (
        not expected
    )


@pytest.mark.unit
def test_a_bad_boolean_names_the_variable(monkeypatch):
    monkeypatch.setenv("INDAH_COMPRESS", "maybe")
    with pytest.raises(ValueError, match="INDAH_COMPRESS"):
        indah.create_app(session_factory=_factory)


@pytest.mark.unit
def test_limits_preset(monkeypatch):
    monkeypatch.setenv("INDAH_LIMITS", "public")
    app = indah.create_app(session_factory=_factory)
    public = Limits.public()
    assert app.state.store.max_sessions == public.max_sessions
    assert app.state.store.idle_timeout_seconds == public.session_idle_seconds
    monkeypatch.setenv("INDAH_LIMITS", "none")
    assert indah.create_app(session_factory=_factory).state.store.max_sessions is None
    monkeypatch.setenv("INDAH_LIMITS", "huge")
    with pytest.raises(ValueError, match="INDAH_LIMITS"):
        indah.create_app(session_factory=_factory)
    monkeypatch.setenv("INDAH_LIMITS", "public")
    explicit = indah.create_app(session_factory=_factory, limits=Limits())
    assert explicit.state.store.max_sessions is None


@pytest.mark.unit
def test_secret_from_the_environment_makes_a_secure_app(monkeypatch):
    monkeypatch.setenv("INDAH_SECRET", "x" * 32)
    app = indah.create_app(session_factory=_factory, secure=True)
    assert app.state.signer is not None
    assert "INDAH_SECRET" in app.state.env_used


@pytest.mark.unit
def test_secrets_list_rotates_and_wins_over_secret(monkeypatch):
    from indah.auth import Principal

    monkeypatch.setenv("INDAH_SECRET", "a" * 32)
    monkeypatch.setenv("INDAH_SECRETS", f"{'n' * 32}, {'o' * 32}")
    app = indah.create_app(session_factory=_factory, secure=True)
    who = Principal(id="u1")
    old_app = indah.create_app(session_factory=_factory, secure=True, secret=["o" * 32])
    old_token = old_app.state.signer.mint(who)
    # The first secret signs, any listed secret verifies: an old token still works,
    # and INDAH_SECRET (not in the list) is ignored when INDAH_SECRETS is set.
    assert app.state.signer.verify(old_token, who) is not None
    ignored = indah.create_app(session_factory=_factory, secure=True, secret="a" * 32)
    assert app.state.signer.verify(ignored.state.signer.mint(who), who) is None
    new_token = app.state.signer.mint(who)
    assert (
        indah.create_app(
            session_factory=_factory, secure=True, secret="n" * 32
        ).state.signer.verify(new_token, who)
        is not None
    )


@pytest.mark.unit
def test_a_short_secret_from_the_environment_names_the_variable(monkeypatch):
    monkeypatch.setenv("INDAH_SECRET", "short")
    with pytest.raises(ValueError, match="INDAH_SECRET"):
        indah.create_app(session_factory=_factory, secure=True)


@pytest.mark.unit
def test_an_explicit_secret_wins(monkeypatch):
    monkeypatch.setenv("INDAH_SECRET", "short")  # would fail if it were read
    app = indah.create_app(session_factory=_factory, secure=True, secret="y" * 32)
    assert app.state.signer is not None
    assert "INDAH_SECRET" not in app.state.env_used


@pytest.mark.unit
def test_secure_without_any_secret_still_fails(monkeypatch):
    with pytest.raises(ValueError, match="secret"):
        indah.create_app(session_factory=_factory, secure=True)


@pytest.mark.unit
def test_the_log_names_variables_and_never_a_value(monkeypatch, caplog):
    monkeypatch.setenv("INDAH_SECRET", "supersecretsupersecretsupersecret")
    monkeypatch.setenv("INDAH_TRUSTED_PROXIES", "10.1.2.3")
    with caplog.at_level(logging.INFO, logger="indah"):
        indah.create_app(session_factory=_factory, secure=True)
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "INDAH_SECRET" in text and "INDAH_TRUSTED_PROXIES" in text
    assert "supersecret" not in text
    assert "10.1.2.3" not in text


@pytest.mark.unit
def test_nothing_is_logged_when_no_variable_is_used(caplog):
    with caplog.at_level(logging.INFO, logger="indah"):
        indah.create_app(session_factory=_factory)
    assert not [r for r in caplog.records if "INDAH_" in r.getMessage()]
