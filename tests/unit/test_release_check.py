"""scripts/release_check.py: the pre-tag checks that stop a wrong release (docs/RELEASING.md)."""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "release_check.py"
spec = importlib.util.spec_from_file_location("release_check", SCRIPT)
rc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rc)

CHANGELOG = """# Changelog

## [Unreleased]

## [1.2.3] - 2026-01-02

Body of the release.

### Added

- A thing.

## [1.2.2] - 2025-12-01

Older.
"""


def make_repo(
    tmp_path,
    *,
    pyproject="1.2.3",
    module="1.2.3",
    changelog=CHANGELOG,
    adrs=("0001-a.md", "0002-b.md"),
):
    (tmp_path / "src/indah").mkdir(parents=True)
    (tmp_path / "docs/adr").mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text(
        f'[project]\nname = "indah"\nversion = "{pyproject}"\n'
    )
    (tmp_path / "src/indah/__init__.py").write_text(f'__version__ = "{module}"\n')
    (tmp_path / "CHANGELOG.md").write_text(changelog)
    for name in adrs:
        (tmp_path / "docs/adr" / name).write_text("# adr\n")
    return tmp_path


@pytest.mark.unit
def test_a_consistent_release_has_no_problems(tmp_path):
    assert rc.problems("1.2.3", make_repo(tmp_path)) == []


@pytest.mark.unit
def test_a_release_candidate_version_is_accepted(tmp_path):
    repo = make_repo(
        tmp_path,
        pyproject="1.3.0rc1",
        module="1.3.0rc1",
        changelog=CHANGELOG.replace("1.2.3", "1.3.0rc1"),
    )
    assert rc.problems("1.3.0rc1", repo) == []


@pytest.mark.unit
@pytest.mark.parametrize("bad", ["1.2", "v1.2.3", "1.2.3.4", "latest", ""])
def test_a_malformed_version_is_rejected(tmp_path, bad):
    assert "is not X.Y.Z" in rc.problems(bad, make_repo(tmp_path))[0]


@pytest.mark.unit
def test_version_drift_between_the_files_is_reported(tmp_path):
    found = rc.problems("1.2.3", make_repo(tmp_path, pyproject="1.2.2", module="1.2.4"))
    assert any("pyproject.toml says 1.2.2" in p for p in found)
    assert any("__version__ says 1.2.4" in p for p in found)


@pytest.mark.unit
def test_a_missing_or_empty_changelog_section_is_reported(tmp_path):
    missing = rc.problems("1.2.3", make_repo(tmp_path / "a", changelog="## [Unreleased]\n"))
    assert any("no '## [1.2.3]" in p for p in missing)
    empty = rc.problems(
        "1.2.3",
        make_repo(
            tmp_path / "b",
            changelog="## [Unreleased]\n\n## [1.2.3] - 2026-01-02\n\n## [1.2.2] - 2025-12-01\nx\n",
        ),
    )
    assert any("is empty" in p for p in empty)


@pytest.mark.unit
def test_entries_left_under_unreleased_are_reported(tmp_path):
    text = CHANGELOG.replace("## [Unreleased]\n", "## [Unreleased]\n\n### Added\n\n- Forgotten.\n")
    assert any("Unreleased" in p for p in rc.problems("1.2.3", make_repo(tmp_path, changelog=text)))


@pytest.mark.unit
def test_an_em_dash_in_the_release_notes_is_reported(tmp_path):
    text = CHANGELOG.replace("A thing.", "A thing — with a dash.")
    assert any("em-dash" in p for p in rc.problems("1.2.3", make_repo(tmp_path, changelog=text)))


@pytest.mark.unit
def test_two_adrs_with_one_number_are_reported(tmp_path):
    repo = make_repo(tmp_path, adrs=("0040-text-scale.md", "0040-studio-home.md", "0041-x.md"))
    assert any("0040" in p for p in rc.problems("1.2.3", repo))
    assert rc.duplicate_adr_numbers(repo / "docs/adr") == ["0040"]


@pytest.mark.unit
def test_an_existing_tag_is_reported(tmp_path):
    found = rc.problems("1.2.3", make_repo(tmp_path), tag_taken=lambda tag: tag == "v1.2.3")
    assert found == ["the tag v1.2.3 already exists"]


@pytest.mark.unit
def test_changelog_section_stops_at_the_next_heading():
    section = rc.changelog_section(CHANGELOG, "1.2.3")
    assert section.startswith("Body of the release.")
    assert "Older." not in section and "## [" not in section
    assert rc.changelog_section(CHANGELOG, "9.9.9") is None


@pytest.mark.unit
def test_the_post_release_commands_pin_the_version_and_run_nothing(capsys):
    assert rc.main(["post", "1.2.3"]) == 0
    out = capsys.readouterr().out
    assert "Expect 1.2.3" in out and "indah==1.2.3" in out
    assert "GALLERY_URL=https://indah-demos.fly.dev" in out and "deploy_fly.sh" in out


@pytest.mark.unit
def test_this_repository_passes_its_own_check_for_the_current_version():
    """The checked-in files agree about the current version (its tag exists, so skip that)."""
    found = rc.problems(rc.pyproject_version(), tag_taken=lambda tag: False)
    assert not [p for p in found if "Unreleased" not in p], found
