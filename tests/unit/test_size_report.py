"""scripts/size_report.py and docs/size-budget.json: the size gate of ADR-0042 (IND-187)."""

import importlib.util
import json
from pathlib import Path

import pytest

pytest.importorskip("tomllib", reason="size_report.py needs Python 3.11+")

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("size_report", ROOT / "scripts" / "size_report.py")
sr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sr)


def test_the_committed_budget_names_only_real_metrics():
    limits = sr.load_limits(ROOT / "docs" / "size-budget.json")
    numbers = sr.measure()
    numbers.setdefault("wheel_bytes", 0)  # only exists after `uv build`
    numbers.setdefault("sdist_bytes", 0)  # likewise
    numbers["base_install_distributions"] = 0  # measured in CI, from the installed wheel
    unknown = set(limits) - set(numbers)
    assert not unknown, f"size-budget.json budgets metrics that are not measured: {unknown}"


def test_the_committed_limits_hold_today():
    limits = sr.load_limits(ROOT / "docs" / "size-budget.json")
    numbers = sr.measure()
    # The wheel only exists after `uv build`; the others are always measurable.
    problems, over = sr.check(numbers, {k: v for k, v in limits.items() if k in numbers})
    assert not problems and not over, (problems, over)


def test_a_number_over_its_limit_fails():
    problems, over = sr.check({"wheel_bytes": 700_000}, {"wheel_bytes": 650_000})
    assert not problems
    assert over == ["OVER BUDGET: wheel_bytes is 700000, limit 650000"]


def test_a_number_at_its_limit_passes():
    assert sr.check({"wheel_bytes": 650_000}, {"wheel_bytes": 650_000}) == ([], [])


def test_a_budgeted_metric_with_no_measurement_is_a_problem_not_a_pass():
    problems, over = sr.check({}, {"wheel_bytes": 650_000})
    assert problems and not over


def test_comment_keys_are_ignored_and_a_typo_is_not(tmp_path):
    budget = tmp_path / "b.json"
    budget.write_text(json.dumps({"_comment": "words", "wheel_bytes": 1, "wheel_byts": 1}))
    limits = sr.load_limits(budget)
    assert limits == {"wheel_bytes": 1, "wheel_byts": 1}
    problems, _ = sr.check({"wheel_bytes": 1}, limits)
    assert any("wheel_byts" in p for p in problems)


def test_the_summary_table_shows_room_and_marks_overruns():
    table = sr.summary({"a": 90, "b": 120}, {"a": 100, "b": 100})
    assert "| a | 90 | 100 | 10 | ok |" in table
    assert "| b | 120 | 100 | -20 | OVER |" in table


def test_main_exits_nonzero_over_budget(tmp_path, monkeypatch, capsys):
    budget = tmp_path / "b.json"
    budget.write_text(json.dumps({"shell_gzip_bytes": 1}))
    monkeypatch.setattr("sys.argv", ["size_report.py", "--budget", str(budget)])
    assert sr.main() == 1
    assert "OVER BUDGET: shell_gzip_bytes" in capsys.readouterr().err


def test_main_exits_zero_within_budget(tmp_path, monkeypatch):
    budget = tmp_path / "b.json"
    budget.write_text(json.dumps({"shell_gzip_bytes": 10_000_000}))
    monkeypatch.setattr("sys.argv", ["size_report.py", "--budget", str(budget)])
    assert sr.main() == 0


def test_dist_size_takes_the_newest_file_and_is_none_without_one(tmp_path):
    assert sr._dist_size(tmp_path, "indah-*.tar.gz") is None
    (tmp_path / "indah-0.6.0.tar.gz").write_bytes(b"x" * 10)
    (tmp_path / "indah-0.7.0.tar.gz").write_bytes(b"x" * 25)
    assert sr._dist_size(tmp_path, "indah-*.tar.gz") == 25


def test_the_committed_budget_covers_every_measured_size():
    """After IND-215 each size the report measures has a limit, so none can drift unwatched."""
    limits = sr.load_limits(ROOT / "docs" / "size-budget.json")
    measured = (
        "wheel_bytes",
        "sdist_bytes",
        "shell_raw_bytes",
        "shell_gzip_bytes",
        "shell_served_gzip_bytes",
        "editor_raw_bytes",
        "editor_gzip_bytes",
        "map_raw_bytes",
        "map_gzip_bytes",
        "python_source_bytes",
    )
    for metric in measured:
        assert metric in limits, f"{metric} has no limit in size-budget.json"
