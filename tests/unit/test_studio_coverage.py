"""The Studio must keep up with the library (``make demo``).

Every public name in ``indah.__all__`` is either demonstrated by some Studio page (listed in its
``covers``) or exempt with a reason in ``examples/studio/core.EXEMPT``. A new component with no
page fails here, which is the prompt to add one (see docs/STUDIO.md).
"""

from pathlib import Path

import pytest

import indah
from examples.studio.core import EXEMPT, covered_names, discover, page_source

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def chapters():
    return discover()


@pytest.mark.unit
def test_every_public_name_has_a_page_or_a_reason(chapters):
    missing = set(indah.__all__) - covered_names(chapters) - set(EXEMPT)
    assert not missing, (
        f"no Studio page covers {sorted(missing)}: add a Page with covers=(...) to a chapter in "
        "examples/studio/chapters/, or add the name to EXEMPT with a reason"
    )


@pytest.mark.unit
def test_pages_only_claim_names_that_exist_and_exemptions_are_not_stale(chapters):
    public = set(indah.__all__)
    stale = covered_names(chapters) - public
    assert not stale, f"pages cover names that are not in indah.__all__: {sorted(stale)}"
    assert not set(EXEMPT) - public, "EXEMPT lists names that are no longer public"
    both = set(EXEMPT) & covered_names(chapters)
    assert not both, f"{sorted(both)} are exempt but also covered: drop them from EXEMPT"


@pytest.mark.unit
def test_pages_are_well_formed(chapters):
    assert chapters, "no chapters found"
    adrs = {p.name[:4] for p in (ROOT / "docs" / "adr").glob("[0-9]*.md")}
    for chapter in chapters:
        assert chapter.pages or chapter.apps, f"{chapter.slug} is empty"
        for item in [*chapter.pages, *chapter.apps]:
            where = f"{chapter.slug}/{item.slug}"
            assert item.title and item.summary, where
            assert "—" not in item.summary + item.title, f"{where}: use hyphens, not em-dashes"
            if item.docs:
                assert (ROOT / "website/docs" / item.docs.split("#")[0]).exists(), where
            for n in item.adr:
                assert f"{n:04d}" in adrs, f"{where}: no ADR-{n:04d}"
        for page in chapter.pages:
            assert page_source(page).strip(), f"{chapter.slug}/{page.slug} has no source"
