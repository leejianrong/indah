import pytest

import indah


@pytest.mark.unit
def test_version_is_exposed():
    assert isinstance(indah.__version__, str)
    assert indah.__version__.count(".") >= 2
