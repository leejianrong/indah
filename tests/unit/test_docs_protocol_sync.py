"""The published protocol page is the engineering contract, copied verbatim.

website/docs/protocol.md had drifted to a September summary that lacked the toast and
navigate messages, sessions, uploads and resume epochs. One source now: edit
docs/protocol.md, then `cp docs/protocol.md website/docs/protocol.md`.
"""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.unit
def test_published_protocol_page_matches_the_contract():
    assert (ROOT / "website/docs/protocol.md").read_text() == (
        ROOT / "docs/protocol.md"
    ).read_text(), "run: cp docs/protocol.md website/docs/protocol.md"
