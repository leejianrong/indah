"""The deploy recipes (deploy/recipes/) agree with each other and with indah (IND-206).

These are cheap checks of the files, not a cluster: the manifests parse, the ports, probe paths and
drain times line up, the settings they use exist and are valid, and the sample app answers its
probes. `deploy/recipes/k8s/verify-k3d.sh` is the real check on a cluster.
"""

import importlib.util
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

pytestmark = pytest.mark.unit

RECIPES = Path(__file__).resolve().parents[2] / "deploy" / "recipes"
K8S = RECIPES / "k8s"
OVERLAYS = ("traefik", "ingress-nginx", "plain")

if not RECIPES.is_dir():  # an install that does not carry deploy/
    pytest.skip("deploy/recipes is not in this tree", allow_module_level=True)


def _docs(path: Path) -> list[dict]:
    return [d for d in yaml.safe_load_all(path.read_text()) if d]


def _deployment() -> dict:
    (dep,) = [d for d in _docs(K8S / "base" / "deployment.yaml") if d["kind"] == "Deployment"]
    return dep


def _container() -> dict:
    return _deployment()["spec"]["template"]["spec"]["containers"][0]


def _config() -> dict:
    (cm,) = _docs(K8S / "base" / "configmap.yaml")
    return cm["data"]


def _fly() -> dict:
    tomllib = pytest.importorskip("tomllib")  # Python 3.11 and later
    return tomllib.loads((RECIPES / "fly" / "fly.toml").read_text())


def _dockerfile() -> str:
    return (RECIPES / "app" / "Dockerfile").read_text()


def test_every_manifest_parses_and_the_kustomizations_point_at_real_files():
    for path in K8S.rglob("*.yaml"):
        assert _docs(path), f"{path.relative_to(RECIPES)} is empty"
    for kust in [K8S / "base" / "kustomization.yaml"] + [
        K8S / "overlays" / o / "kustomization.yaml" for o in OVERLAYS
    ]:
        (doc,) = _docs(kust)
        for res in doc["resources"]:
            target = kust.parent / res
            assert target.exists(), f"{kust.relative_to(RECIPES)} names {res}, which is missing"
        # the base sets the namespace, but not for resources an overlay adds (the Ingress)
        assert doc["namespace"] == "indah", kust


def test_probe_paths_and_the_port_line_up_across_the_dockerfile_fly_and_k8s():
    container = _container()
    assert container["readinessProbe"]["httpGet"]["path"] == "/ready"
    assert container["livenessProbe"]["httpGet"]["path"] == "/health"
    port = container["ports"][0]["containerPort"]
    assert port == 8080
    assert f"EXPOSE {port}" in _dockerfile()
    assert f'"--port", "{port}"' in _dockerfile()
    fly = _fly()
    assert fly["http_service"]["internal_port"] == port
    (check,) = fly["http_service"]["checks"]
    assert check["path"] == "/ready"
    # the Service and the Ingresses reach the named port
    (svc,) = [d for d in _docs(K8S / "base" / "service.yaml") if d["kind"] == "Service"]
    assert svc["spec"]["ports"][0]["targetPort"] == container["ports"][0]["name"]
    for o in OVERLAYS:
        (ing,) = _docs(K8S / "overlays" / o / "ingress.yaml")
        backend = ing["spec"]["rules"][0]["http"]["paths"][0]["backend"]["service"]
        assert backend["name"] == svc["metadata"]["name"]
        assert backend["port"]["name"] == svc["spec"]["ports"][0]["name"]


def test_the_grace_periods_leave_room_for_the_drain():
    drain = int(_config()["INDAH_DRAIN_SECONDS"])
    pre_stop = int(_container()["lifecycle"]["preStop"]["exec"]["command"][1])
    grace = _deployment()["spec"]["template"]["spec"]["terminationGracePeriodSeconds"]
    assert grace > pre_stop + drain
    fly = _fly()
    assert fly["kill_signal"] == "SIGTERM"  # Fly's default is SIGINT, which does not drain
    assert fly["kill_timeout"] > int(fly["env"]["INDAH_DRAIN_SECONDS"])
    assert fly["http_service"]["auto_stop_machines"] == "off"  # a stopped machine drops its tabs


def test_the_settings_the_recipes_use_exist_and_are_valid():
    from indah.proxy_presets import PRESET_NAMES

    names = set(_config()) | set(_fly()["env"])
    source = (Path(sys.modules["indah"].__file__).parent / "envconfig.py").read_text()
    for name in names:
        assert name in source, f"{name} is not a variable indah reads"
    for value in (_config()["INDAH_TRUSTED_PROXIES"], _fly()["env"]["INDAH_TRUSTED_PROXIES"]):
        for entry in value.split(","):
            assert entry.strip() in PRESET_NAMES, f"{entry!r} is not a trusted_proxies preset"
    # a secret is never part of the manifests
    for path in K8S.rglob("kustomization.yaml"):
        for doc in _docs(path):
            assert "secret.example.yaml" not in doc.get("resources", [])
    assert "kind: Secret" not in "".join(
        p.read_text() for p in K8S.rglob("*.yaml") if p.name != "secret.example.yaml"
    )


def test_the_affinity_annotations_are_the_documented_ones():
    traefik = (K8S / "overlays" / "traefik" / "kustomization.yaml").read_text()
    assert 'traefik.ingress.kubernetes.io/service.sticky.cookie: "true"' in traefik
    assert "kind: Service" in traefik  # Traefik reads them on the Service, not the Ingress
    (ing,) = _docs(K8S / "overlays" / "ingress-nginx" / "ingress.yaml")
    notes = ing["metadata"]["annotations"]
    assert notes["nginx.ingress.kubernetes.io/affinity"] == "cookie"
    # `balanced` moves sessions when pods are added, and a moved tab loses its state
    assert notes["nginx.ingress.kubernetes.io/affinity-mode"] == "persistent"
    # the event stream is long-lived
    assert notes["nginx.ingress.kubernetes.io/proxy-buffering"] == "off"
    (plain,) = _docs(K8S / "overlays" / "plain" / "ingress.yaml")
    assert "annotations" not in plain["metadata"]


@pytest.mark.skipif(shutil.which("kubectl") is None, reason="kubectl is not installed")
@pytest.mark.parametrize("overlay", OVERLAYS)
def test_kustomize_builds_each_overlay(overlay):
    out = subprocess.run(
        ["kubectl", "kustomize", str(K8S / "overlays" / overlay)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    kinds = [d["kind"] for d in yaml.safe_load_all(out) if d]
    assert sorted(kinds) == [
        "ConfigMap",
        "Deployment",
        "Ingress",
        "Namespace",
        "PodDisruptionBudget",
        "Service",
    ]
    for doc in yaml.safe_load_all(out):
        if doc and doc["kind"] != "Namespace":
            assert doc["metadata"]["namespace"] == "indah", doc["kind"]


def test_the_sample_app_answers_its_probes():
    from starlette.testclient import TestClient

    spec = importlib.util.spec_from_file_location("recipe_app", RECIPES / "app" / "app.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    client = TestClient(module.app)
    assert client.get("/health").status_code == 200
    assert client.get("/ready").status_code == 200
    page = client.get("/")
    assert page.status_code == 200


def test_the_docs_name_the_recipe_files_that_exist():
    root = RECIPES.parents[1]
    text = "".join(
        (root / "website" / "docs" / name).read_text()
        for name in ("deploy-fly.md", "deploy-k8s.md")
    )
    for ref in set(re.findall(r"deploy/recipes/[\w./-]+", text)):
        ref = ref.rstrip(".")
        assert (root / ref).exists(), f"the docs mention {ref}, which does not exist"
