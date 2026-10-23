"""The DataFrame explorer demo (examples/dataframe_explorer.py, IND-61): its data and its logic."""

import pytest

from examples import dataframe_explorer as df

pytestmark = pytest.mark.unit


def test_the_data_is_the_same_every_time():
    assert df.make_cars() == df.make_cars()
    assert df.make_cars(seed=1) != df.make_cars(seed=2)
    assert len(df.CARS) == df.N_CARS


def test_every_row_is_complete_and_in_range():
    keys = {"id", "make", "model", "cls", "year", "mpg", "hp", "weight", "price"}
    assert len({r["id"] for r in df.CARS}) == len(df.CARS)  # row keys are unique
    for r in df.CARS:
        assert set(r) == keys
        assert r["cls"] in df.CLASSES
        assert df.YEAR_MIN <= r["year"] <= df.YEAR_MAX
        assert r["mpg"] > 0 and r["hp"] >= 60 and r["weight"] > 0 and r["price"] >= 8000


def test_every_class_is_present():
    assert {r["cls"] for r in df.CARS} == set(df.CLASS_NAMES)


def test_filter_by_class_and_year():
    suvs = df.filter_rows(df.CARS, ["SUV"], df.YEAR_MIN)
    assert suvs and all(r["cls"] == "SUV" for r in suvs)
    recent = df.filter_rows(df.CARS, df.CLASS_NAMES, 2020)
    assert recent and all(r["year"] >= 2020 for r in recent)
    assert df.filter_rows(df.CARS, [], df.YEAR_MIN) == []
    assert df.filter_rows(df.CARS, df.CLASS_NAMES, df.YEAR_MAX + 1) == []
    assert len(df.filter_rows(df.CARS, df.CLASS_NAMES, df.YEAR_MIN)) == len(df.CARS)


def test_class_counts_follow_the_year():
    counts = df.class_counts(df.CARS, df.YEAR_MIN)
    assert sum(counts.values()) == len(df.CARS)
    later = df.class_counts(df.CARS, 2022)
    assert sum(later.values()) == len([r for r in df.CARS if r["year"] >= 2022])
    assert all(later[c] <= counts[c] for c in df.CLASS_NAMES)


@pytest.mark.parametrize("field", df.METRIC_FIELDS)
def test_histogram_counts_every_row_once(field):
    edges = df.histogram_edges(df.CARS, field)
    assert len(edges) == df.BINS + 1
    assert edges[0] == min(r[field] for r in df.CARS)
    counts = df.histogram_counts(df.CARS, field, edges)
    assert len(counts) == df.BINS
    assert sum(counts) == len(df.CARS)  # the top edge belongs to the last bin


def test_histogram_of_no_rows_and_of_one_value():
    assert df.histogram_edges([], "mpg") == []
    assert df.histogram_counts([], "mpg", []) == []
    assert df.distribution_rows([], [], "mpg") == []
    nothing_ticked = df.distribution_rows(df.CARS[:50], [], "mpg")
    assert all(row[2] == 0.0 for row in nothing_ticked)
    same = [{"mpg": 30.0}, {"mpg": 30.0}]
    edges = df.histogram_edges(same, "mpg")
    assert sum(df.histogram_counts(same, "mpg", edges)) == 2


def test_distribution_rows_carry_matching_and_ticked_shares():
    matching = df.filter_rows(df.CARS, ["Sedan", "SUV"], 2015)
    ticked = matching[:10]
    rows = df.distribution_rows(matching, ticked, "hp")
    assert len(rows) == df.BINS
    assert all(len(row) == 3 for row in rows)
    assert sum(row[1] for row in rows) == pytest.approx(100, abs=1.5)  # shares of one group
    assert sum(row[2] for row in rows) == pytest.approx(100, abs=1.5)
    assert [row[0] for row in rows] == sorted(row[0] for row in rows)  # x increases


def test_summary():
    assert df.summary([], "mpg") == {"count": 0, "mean": None, "median": None}
    s = df.summary([{"mpg": 10.0}, {"mpg": 20.0}, {"mpg": 60.0}], "mpg")
    assert s == {"count": 3, "mean": 30.0, "median": 20.0}


def test_format_value():
    assert df.format_value("price", 31250.4) == "$31,250"
    assert df.format_value("mpg", 33.04) == "33.0 mpg"
    assert df.format_value("hp", 165.2) == "165 hp"
    assert df.format_value("weight", 1450.0) == "1,450 kg"
    assert df.format_value("mpg", None) == "-"


def test_the_story_the_data_tells():
    """Trucks are thirstier and pricier than hatchbacks, so the filters are worth using."""
    by = {c: [r for r in df.CARS if r["cls"] == c] for c in df.CLASS_NAMES}
    mean = lambda rows, f: sum(r[f] for r in rows) / len(rows)  # noqa: E731
    assert mean(by["Truck"], "mpg") < mean(by["Hatchback"], "mpg")
    assert mean(by["Truck"], "price") > mean(by["Hatchback"], "price")
    assert mean(by["Sports"], "hp") > mean(by["Sedan"], "hp")


def test_the_app_builds_and_the_filters_drive_the_table_and_the_chart():
    from indah.protocol import init_message

    session = df.build()
    snapshot = init_message(session.root.to_json())
    types = []

    def walk(node):
        types.append(node["type"])
        for child in node.get("children", []):
            walk(child)

    walk(snapshot["root"])
    for expected in ("chips", "slider", "segmented", "chart", "table", "stat"):
        assert expected in types
