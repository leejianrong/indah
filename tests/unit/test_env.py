import pytest

from indah.env import Environment, detect_environment, public_url


@pytest.mark.unit
def test_detect_local_when_no_platform_env():
    assert detect_environment(env={}) is Environment.LOCAL


@pytest.mark.unit
def test_detect_runpod_from_pod_id():
    assert detect_environment(env={"RUNPOD_POD_ID": "abc123"}) is Environment.RUNPOD


@pytest.mark.unit
def test_detect_colab_from_release_tag():
    assert detect_environment(env={"COLAB_RELEASE_TAG": "release-1.2"}) is Environment.COLAB


@pytest.mark.unit
def test_public_url_local():
    url = public_url(8000, Environment.LOCAL, host="127.0.0.1", env={})
    assert url == "http://127.0.0.1:8000"


@pytest.mark.unit
def test_public_url_runpod():
    url = public_url(7860, Environment.RUNPOD, env={"RUNPOD_POD_ID": "abc123"})
    assert url == "https://abc123-7860.proxy.runpod.net"


@pytest.mark.unit
def test_public_url_colab_uses_injected_proxy_and_strips_trailing_slash():
    def fake_proxy(port: int) -> str:
        return f"https://ab12cd.googleusercontent.com/proxy/{port}/"

    url = public_url(
        8000,
        Environment.COLAB,
        env={"COLAB_RELEASE_TAG": "x"},
        colab_proxy=fake_proxy,
    )
    assert url == "https://ab12cd.googleusercontent.com/proxy/8000"
