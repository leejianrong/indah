"""The semula review server (examples/semula_review.py): one index page and every demo
mounted under its own prefix."""

import importlib.util
import sys
from pathlib import Path

import httpx
import pytest

_EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "semula_review.py"
spec = importlib.util.spec_from_file_location("semula_review_example", _EXAMPLE)
ex = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = ex
spec.loader.exec_module(ex)


@pytest.mark.integration
async def test_index_links_every_demo_and_each_shell_is_served():
    app = ex.build_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        index = await c.get("/")
        assert index.status_code == 200
        for key, _title, _hint in ex.DEMOS:
            assert f'href="{key}/ui/"' in index.text
            if key == "hosted":  # needs a login: anonymous visitors are sent to the login page
                anon = await c.get("/hosted/ui/")
                assert anon.status_code == 302 and anon.headers["location"] == "../login"
            shell = await c.get(
                f"/{key}/ui/", headers={"X-User": "alice"} if key == "hosted" else {}
            )
            assert shell.status_code == 200, key
            assert "<title>" in shell.text
