import sys
from pathlib import Path

import pytest

import indah

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 has no stdlib tomllib
    tomllib = None


@pytest.mark.unit
def test_version_is_exposed():
    assert isinstance(indah.__version__, str)
    assert indah.__version__.count(".") >= 2


@pytest.mark.unit
@pytest.mark.skipif(sys.version_info < (3, 11), reason="tomllib needs Python 3.11+")
def test_version_matches_pyproject():
    """The packaged version and the runtime __version__ must not drift.

    RELEASING.md bumps both in lockstep; this pins that they agree.
    """
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    packaged = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"]
    assert packaged == indah.__version__
