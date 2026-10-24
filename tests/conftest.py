"""Shared pytest hooks.

An sdist does not carry ``examples/`` (ADR-0042, IND-190), but dozens of tests build the demo apps
and read their source. When ``examples/`` is missing, those test files are not collected, and the
header says how many, so a run from an sdist covers the library and never fails on a missing demo.
In a git checkout ``examples/`` exists and nothing is skipped.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_HAS_EXAMPLES = (ROOT / "examples").is_dir()
# A test file needs examples/ when it names the directory, or loads a script that imports the demos
# at run time (the gallery app, the docs bundle and the page export). Matching the word anywhere is
# coarse (a docstring that says "examples" counts); the cost of a false match is only that the file
# is not collected from an sdist.
_NEEDS_EXAMPLES = re.compile(r"\bexamples\b|gallery_app|build_docs_live|export_studio_pages")
_skipped: list[str] = []


def pytest_ignore_collect(collection_path, config):
    if _HAS_EXAMPLES or collection_path.suffix != ".py":
        return None
    try:
        text = collection_path.read_text(encoding="utf-8")
    except OSError:
        return None
    if _NEEDS_EXAMPLES.search(text):
        _skipped.append(collection_path.name)
        return True
    return None


def pytest_report_header(config):
    if not _HAS_EXAMPLES:
        return "examples/ is not in this tree (an sdist): test files that read it are not collected"
    return None


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    if _skipped:
        terminalreporter.write_line(
            f"{len(_skipped)} test files that read examples/ were not collected (no examples/ here)"
        )
