"""The optional extras of ADR-0042 (IND-188): what each holds, and the messages that name them."""

import re
from pathlib import Path

import pytest

import indah

tomllib = pytest.importorskip("tomllib", reason="reading pyproject needs Python 3.11+")

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
PROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
EXTRAS = PROJECT["optional-dependencies"]


def _names(requirements):
    return {
        re.split(r"[<>=!~\[ ;]", r, maxsplit=1)[0].lower().replace("_", "-") for r in requirements
    }


def test_the_feature_extras_hold_what_the_adr_says():
    assert _names(EXTRAS["plot"]) == {"matplotlib"}
    assert _names(EXTRAS["data"]) == {"pandas", "numpy"}
    assert _names(EXTRAS["redis"]) == {"redis"}
    assert _names(EXTRAS["demos"]) == {
        "numpy",
        "pillow",
        "onnxruntime",
        "huggingface-hub",
        "matplotlib",
    }


def test_all_is_the_feature_extras_and_never_tooling_or_demos():
    flat = _names(EXTRAS["all"])
    assert flat == _names(EXTRAS["plot"]) | _names(EXTRAS["data"]) | _names(EXTRAS["redis"])
    assert not flat & {"pytest", "playwright", "zensical", "onnxruntime", "pillow"}


def test_every_feature_requirement_has_a_version_floor():
    for extra in ("plot", "data", "redis", "demos"):
        for requirement in EXTRAS[extra]:
            assert re.search(r">=\s*\d", requirement), f"{extra}: {requirement!r} has no floor"


def test_the_base_install_keeps_four_direct_dependencies_and_no_feature_library():
    names = _names(PROJECT["dependencies"])
    assert len(PROJECT["dependencies"]) == 4
    assert not names & {"matplotlib", "pandas", "numpy", "pillow", "onnxruntime"}


def test_a_dataframe_given_the_wrong_thing_names_the_data_extra():
    df = indah.DataFrame(42)
    with pytest.raises(TypeError, match=r"indah\[data\]"):
        df.reactive_props()["data"]()


def test_a_table_given_the_wrong_rows_names_the_data_extra():
    with pytest.raises(TypeError, match=r"indah\[data\]"):
        indah.Table(rows=42, key="id")
