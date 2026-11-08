"""``Table(narrow="cards")`` (IND-258): the prop, its validation, and the default staying off."""

import pytest

from indah.components import Col, Column, Signal, Table
from indah.session import Session
from indah.transport import Hub

ROWS = [{"id": "a", "n": 1}]
COLS = [Col("id"), Col("n")]


def _props(**kw) -> dict:
    session = Session(Column(children=[Table(rows=ROWS, columns=COLS, key="id", **kw)]))
    session.bind_hub(Hub(coalesce_seconds=0))
    return session.root.to_json()["children"][0]["props"]


@pytest.mark.unit
def test_narrow_cards_is_on_the_wire():
    assert _props(narrow="cards")["narrow"] == "cards"


@pytest.mark.unit
def test_a_default_table_wires_no_narrow_prop():
    assert "narrow" not in _props()


@pytest.mark.unit
def test_narrow_works_with_the_remote_form():
    table = Table(columns=COLS, key="id", remote=lambda q: ([], 0), narrow="cards")
    assert table.static_props()["narrow"] == "cards"


@pytest.mark.unit
@pytest.mark.parametrize("bad", ["card", "", "scroll", 1])
def test_narrow_must_be_cards(bad):
    with pytest.raises(ValueError, match="narrow"):
        Table(rows=ROWS, columns=COLS, key="id", narrow=bad)


@pytest.mark.unit
def test_narrow_needs_the_rich_form():
    with pytest.raises(ValueError, match="narrow"):
        Table({"columns": ["a"], "rows": [[1]]}, narrow="cards", selected=Signal(None))


@pytest.mark.unit
def test_narrow_is_not_for_virtual_tables():
    with pytest.raises(ValueError, match="narrow"):
        Table(rows=ROWS, columns=COLS, key="id", height="10rem", virtual=True, narrow="cards")
