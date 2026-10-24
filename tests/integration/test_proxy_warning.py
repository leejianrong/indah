"""A forwarded header arrives but ``trusted_proxies`` is empty: say so, once (IND-200).

The commonest deployment mistake is silent: behind a proxy every visitor resolves to the
proxy's address and shares one rate-limit bucket. The warning names the header, never its value.
"""

import logging

import pytest
from starlette.testclient import TestClient

import indah

HEADERS = [
    "X-Forwarded-For",
    "Forwarded",
    "X-Forwarded-Proto",
    "Fly-Client-IP",
    "CF-Connecting-IP",
]


def _warnings(caplog):
    return [r for r in caplog.records if r.name == "indah" and "trusted_proxies" in r.getMessage()]


@pytest.mark.integration
@pytest.mark.parametrize("header", HEADERS)
def test_each_forwarded_header_warns_once_and_names_the_header_not_the_value(caplog, header):
    app = indah.create_app()
    secret_looking = "203.0.113.77"
    with caplog.at_level(logging.WARNING, logger="indah"):
        with TestClient(app) as client:
            client.get("/health", headers={header: secret_looking})
            client.get("/health", headers={header: secret_looking})
            client.get("/", headers={header: secret_looking})
    found = _warnings(caplog)
    assert len(found) == 1
    text = found[0].getMessage()
    assert header.lower() in text.lower()
    assert secret_looking not in text
    assert "testclient" in text  # the socket peer is useful and not secret
    assert app.state.proxy_warning_issued is True


@pytest.mark.integration
def test_no_forwarded_header_no_warning(caplog):
    app = indah.create_app()
    with caplog.at_level(logging.WARNING, logger="indah"):
        with TestClient(app) as client:
            client.get("/health")
            client.get("/health", headers={"User-Agent": "x"})
    assert _warnings(caplog) == []
    assert app.state.proxy_warning_issued is False


@pytest.mark.integration
def test_trusted_proxies_set_means_no_warning_even_from_an_untrusted_peer(caplog):
    app = indah.create_app(trusted_proxies=["10.0.0.0/8"])
    with caplog.at_level(logging.WARNING, logger="indah"):
        with TestClient(app) as client:
            client.get("/health", headers={"X-Forwarded-For": "203.0.113.9"})
    assert _warnings(caplog) == []
    assert app.state.proxy_warning_issued is False


@pytest.mark.integration
def test_warn_untrusted_forwarding_false_silences_it(caplog):
    app = indah.create_app(warn_untrusted_forwarding=False)
    with caplog.at_level(logging.WARNING, logger="indah"):
        with TestClient(app) as client:
            client.get("/health", headers={"X-Forwarded-For": "203.0.113.9"})
    assert _warnings(caplog) == []
    assert app.state.proxy_warning_issued is False


@pytest.mark.integration
def test_the_warning_does_not_change_what_the_app_does():
    app = indah.create_app()
    with TestClient(app) as client:
        r = client.get("/health", headers={"X-Forwarded-For": "203.0.113.9"})
    assert r.status_code == 200


@pytest.mark.integration
@pytest.mark.parametrize(
    "environment,silenced",
    [
        (indah.Environment.COLAB, True),
        (indah.Environment.RUNPOD, True),
        (indah.Environment.LOCAL, False),
    ],
)
def test_launch_silences_the_warning_only_where_a_host_proxy_is_expected(environment, silenced):
    from indah.launch import _expect_host_proxy

    app = indah.create_app()
    _expect_host_proxy(app, environment)
    assert app.state.proxy_notice.enabled is (not silenced)
    _expect_host_proxy(object(), environment)  # a non-indah ASGI app is left alone
