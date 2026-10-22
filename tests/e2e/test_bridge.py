"""The web-component bridge in a real browser, under a strict CSP (ADR-0039, IND-150).

Every test here runs under ``csp="strict"`` (the conftest), so a module that needs inline code,
or a shell that loads one badly, fails on the violation. Covers: styles in a shadow root, a mount
prefix and a window-buffering proxy, caching, props and events both ways, theming, a broken module
falling back to text, resume after a dropped stream, and focus ownership of a two-way prop.
"""

import pytest
from starlette.applications import Starlette
from starlette.routing import Mount

import indah
from indah import Button, Column, Session, Signal, Text
from indah.custom import _REGISTRY, clear_registry, custom, register_component
from indah.launch import launch

from .test_proxy_buffering import BufferingProxy

playwright_sync = pytest.importorskip("playwright.sync_api")
sync_playwright = playwright_sync.sync_playwright
expect = playwright_sync.expect


@pytest.fixture(autouse=True)
def _registry():
    saved = dict(_REGISTRY)
    clear_registry()
    yield
    clear_registry()
    _REGISTRY.update(saved)


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch()
        try:
            yield b
        finally:
            b.close()


def _page(browser):
    ctx = browser.new_context(viewport={"width": 1100, "height": 800})
    return ctx, ctx.new_page()


def _serve(app):
    return launch(app, block=False, open_inline=False)


def _single(tag_type: str, **props):
    """An app with one module component, plus a Text that proves the rest of the tree is live."""
    live = Signal("live")

    def build(ctx) -> Session:
        return Session(
            Column(
                children=[
                    custom(tag_type, **props),
                    Text(lambda: f"page is {live.value}"),
                    Button("flip", on_click=lambda: live.set("still live")),
                ]
            )
        )

    return indah.create_app(session_factory=build)


# -- the two open questions of the ADR (the spike) ----------------------------------------


SHEET_MODULE = b"""
const sheet = new CSSStyleSheet();
sheet.replaceSync("b { color: rgb(1, 2, 3); }");
export default class extends HTMLElement {
  constructor() { super(); this.attachShadow({mode: "open"}).adoptedStyleSheets = [sheet]; }
  connectedCallback() {
    const b = document.createElement("b"); b.textContent = "sheet"; this.shadowRoot.append(b);
  }
}
"""

NONCE_MODULE = b"""
export default class extends HTMLElement {
  constructor() { super(); this.attachShadow({mode: "open"}); }
  connectedCallback() {
    const s = document.createElement("style");
    s.setAttribute("nonce", this.cspNonce);
    s.textContent = "b { color: rgb(4, 5, 6); }";
    const b = document.createElement("b"); b.textContent = "nonce";
    this.shadowRoot.append(s, b);
  }
}
"""

COLOUR = "e => getComputedStyle(e.shadowRoot.querySelector('b')).color"


@pytest.mark.e2e
def test_styles_in_a_shadow_root_work_under_the_strict_csp_both_ways(browser):
    """(a) A constructable stylesheet and a <style nonce=el.cspNonce> both apply, with no
    securitypolicyviolation (the conftest fails the test on one)."""
    register_component("sheet-probe", module=SHEET_MODULE)
    register_component("nonce-probe", module=NONCE_MODULE)
    app = indah.create_app(
        session_factory=lambda: Session(
            Column(children=[custom("sheet-probe"), custom("nonce-probe")])
        )
    )
    handle = _serve(app)
    ctx, page = _page(browser)
    try:
        page.goto(handle.url, wait_until="domcontentloaded")
        sheet, nonce = page.locator("indah-x-sheet-probe"), page.locator("indah-x-nonce-probe")
        expect(sheet).to_be_visible()
        assert sheet.evaluate(COLOUR) == "rgb(1, 2, 3)"
        assert nonce.evaluate(COLOUR) == "rgb(4, 5, 6)"
        assert nonce.evaluate("e => e.cspNonce.length") > 10
    finally:
        ctx.close()
        handle.stop()


class _CountModuleRequests:
    """ASGI middleware: how many times the module route was requested."""

    def __init__(self, app):
        self.app, self.hits = app, []

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and "/api/components/" in scope["path"]:
            self.hits.append(scope["path"])
        await self.app(scope, receive, send)


@pytest.mark.e2e
def test_module_loads_under_a_mount_prefix_through_a_buffering_proxy_and_is_cached(browser):
    """(b) The module URL is relative, so it resolves under /ui; a window-buffering proxy (Colab's)
    does not hold it; and a second page load does not fetch it again (content-hashed URL)."""
    register_component("tier-rail", module=_demo_js(), events=["pick"], two_way={"value": "change"})
    inner = indah.create_app(
        session_factory=lambda: Session(Column(children=[custom("tier-rail", steps=["A", "B"])])),
        spa=True,
    )
    counted = _CountModuleRequests(Starlette(routes=[Mount("/ui", app=inner)]))
    handle = _serve(counted)
    proxy = BufferingProxy("127.0.0.1", handle.port).start()
    ctx, page = _page(browser)
    try:
        page.goto(proxy.url + "/ui/", wait_until="domcontentloaded")
        rail = page.locator("indah-x-tier-rail")
        expect(rail.get_by_role("button", name="B")).to_be_visible()
        assert counted.hits and all(
            h.startswith("/ui/api/components/tier-rail.js") for h in counted.hits
        )
        first = len(counted.hits)
        page.goto(proxy.url + "/ui/", wait_until="domcontentloaded")
        expect(page.locator("indah-x-tier-rail").get_by_role("button", name="B")).to_be_visible()
        assert len(counted.hits) == first, "the immutable module was fetched again"
    finally:
        ctx.close()
        proxy.stop()
        handle.stop()


@pytest.mark.e2e
def test_an_app_without_a_module_component_never_requests_one(browser):
    counted = _CountModuleRequests(indah.create_app(session_factory=lambda: Session(Text("hi"))))
    handle = _serve(counted)
    ctx, page = _page(browser)
    try:
        page.goto(handle.url, wait_until="domcontentloaded")
        expect(page.get_by_text("hi")).to_be_visible()
        page.wait_for_timeout(300)
        assert counted.hits == []
    finally:
        ctx.close()
        handle.stop()


# -- the demo module ----------------------------------------------------------------------


def _demo_js() -> bytes:
    from pathlib import Path

    import examples.studio.chapters.extend as extend

    return (Path(extend.__file__).resolve().parent.parent / "modules" / "tier-rail.js").read_bytes()


def _demo_app():
    from examples.studio.chapters.extend import bridge_page

    return indah.create_app(session_factory=lambda ctx: Session(bridge_page(ctx)))


@pytest.mark.e2e
def test_demo_module_props_signal_updates_and_a_customevent_round_trip(browser):
    import examples.studio.chapters.extend  # noqa: F401  (registers "tier-rail")

    register_component(
        "tier-rail",
        module=_demo_js(),
        events=["pick"],
        two_way={"value": "change"},
        fallback="steps",
    )
    handle = _serve(_demo_app())
    ctx, page = _page(browser)
    try:
        page.goto(handle.url, wait_until="domcontentloaded")
        rail = page.locator("indah-x-tier-rail")
        expect(rail.get_by_role("button", name="Seed")).to_have_attribute("aria-pressed", "true")
        expect(page.get_by_text("Tier 0, last pick: nothing yet")).to_be_visible()
        rail.get_by_role("button", name="Bloom").click()  # CustomEvent -> signal + handler
        expect(page.get_by_text("Tier 2, last pick: Bloom")).to_be_visible()
        page.get_by_role("button", name="Next tier").click()  # signal -> property
        expect(rail.get_by_role("button", name="Seed")).to_have_attribute("aria-pressed", "true")
        page.get_by_role("button", name="Add a tier").click()  # an array prop is replaced
        expect(rail.get_by_role("button", name="Tier 3")).to_be_visible()
        # props are data: a prop holding markup is text, not DOM
        assert rail.evaluate("e => e.shadowRoot.querySelectorAll('button').length") == 4
    finally:
        ctx.close()
        handle.stop()


@pytest.mark.e2e
def test_demo_module_follows_the_shell_theme_through_css_variables(browser):
    register_component("tier-rail", module=_demo_js(), events=["pick"], two_way={"value": "change"})
    handle = _serve(
        indah.create_app(
            session_factory=lambda: Session(
                Column(children=[custom("tier-rail", steps=["A", "B"], value=Signal(0))])
            )
        )
    )
    ctx, page = _page(browser)
    try:
        page.goto(handle.url, wait_until="domcontentloaded")
        rail = page.locator("indah-x-tier-rail")
        expect(rail.get_by_role("button", name="B")).to_be_visible()
        bg = "e => getComputedStyle(e.shadowRoot.querySelectorAll('button')[1]).backgroundColor"
        page.get_by_role("button", name="Light theme").click()
        light = rail.evaluate(bg)
        page.get_by_role("button", name="Dark theme").click()
        dark = rail.evaluate(bg)
        assert light != dark, "the module did not follow the theme"
    finally:
        ctx.close()
        handle.stop()


# -- failure ------------------------------------------------------------------------------

BROKEN = {
    "ctor-throws": (
        b"export default class extends HTMLElement {"
        b" constructor() { super(); throw new Error('boom'); } }"
    ),
    "connect-throws": (
        b"export default class extends HTMLElement {"
        b" connectedCallback() { throw new Error('boom'); } }"
    ),
    "no-default": b"export const nope = 1;",
    "bad-syntax": b"export default class {{{",
}


@pytest.mark.e2e
@pytest.mark.parametrize("kind", sorted(BROKEN))
def test_a_broken_module_shows_its_fallback_and_the_page_keeps_working(browser, kind):
    register_component(kind, module=BROKEN[kind], fallback="steps")
    handle = _serve(_single(kind, steps="A B C"))
    ctx, page = _page(browser)
    try:
        page.goto(handle.url, wait_until="domcontentloaded")
        expect(page.locator(".bridge-fallback")).to_have_text("A B C")
        page.get_by_role("button", name="flip").click()
        expect(page.get_by_text("page is still live")).to_be_visible()
    finally:
        ctx.close()
        handle.stop()


# -- resume and focus ---------------------------------------------------------------------


@pytest.mark.e2e
def test_the_element_survives_a_dropped_stream_and_keeps_receiving_updates(browser):
    register_component("tier-rail", module=_demo_js(), events=["pick"], two_way={"value": "change"})
    tier = Signal(0)

    def build(ctx) -> Session:
        return Session(
            Column(
                children=[
                    custom("tier-rail", steps=["A", "B", "C"], value=tier),
                    Button("go-c", on_click=lambda: tier.set(2)),
                ]
            )
        )

    handle = _serve(indah.create_app(session_factory=build))
    ctx, page = _page(browser)
    try:
        page.goto(handle.url, wait_until="domcontentloaded")
        rail = page.locator("indah-x-tier-rail")
        expect(rail.get_by_role("button", name="A")).to_have_attribute("aria-pressed", "true")
        rail.evaluate("e => { window.__rail = e; }")
        ctx.set_offline(True)
        page.wait_for_timeout(500)
        ctx.set_offline(False)
        page.wait_for_timeout(500)
        # reconnects (the shell resumes its session); the same element gets the next change
        page.get_by_role("button", name="go-c").click(timeout=20_000)
        expect(rail.get_by_role("button", name="C")).to_have_attribute(
            "aria-pressed", "true", timeout=20_000
        )
        assert rail.evaluate("e => e === window.__rail"), "the element was recreated"
    finally:
        ctx.close()
        handle.stop()


INPUT_MODULE = b"""
export default class extends HTMLElement {
  constructor() {
    super();
    this.box = document.createElement("input");
    this.attachShadow({mode: "open"}).append(this.box);
    this.box.addEventListener("input", () =>
      this.dispatchEvent(new CustomEvent("change", {detail: {value: this.box.value}})));
  }
  set value(v) { this.box.value = v; }
  get value() { return this.box.value; }
}
"""


@pytest.mark.e2e
def test_a_two_way_prop_is_not_clobbered_while_the_viewer_edits_it(browser):
    register_component("text-box", module=INPUT_MODULE, two_way={"value": "change"})
    text = Signal("")

    def build(ctx) -> Session:
        return Session(
            Column(
                children=[
                    custom("text-box", value=text),
                    Button("stale", on_click=lambda: text.set("STALE")),
                    Text(lambda: f"server has {text.value!r}"),
                ]
            )
        )

    handle = _serve(indah.create_app(session_factory=build))
    ctx, page = _page(browser)
    try:
        page.goto(handle.url, wait_until="domcontentloaded")
        box = page.locator("indah-x-text-box input")
        expect(box).to_be_visible()
        box.click()
        page.keyboard.type("hello")
        expect(page.get_by_text("server has 'hello'")).to_be_visible()  # the event wrote the signal
        page.get_by_role("button", name="stale").dispatch_event("click")  # focus stays in the box
        expect(page.get_by_text("server has 'STALE'")).to_be_visible()
        page.wait_for_timeout(300)
        expect(box).to_have_value("hello")  # not clobbered while focused
        box.blur()
        expect(box).to_have_value("STALE")  # adopted once editing ends
    finally:
        ctx.close()
        handle.stop()


UNNONCED_MODULE = b"""
export default class extends HTMLElement {
  constructor() { super(); this.attachShadow({mode: "open"}); }
  connectedCallback() {
    const s = document.createElement("style");      // no nonce: the strict policy refuses it
    s.textContent = "b { color: rgb(7, 8, 9); }";
    const b = document.createElement("b"); b.textContent = "x";
    this.shadowRoot.append(s, b);
  }
}
"""


@pytest.mark.e2e
@pytest.mark.expects_csp_violation
def test_guard_proof_an_unnonced_style_in_a_module_is_refused_by_the_policy(browser):
    """Proves the policy is live in these tests: the same module as the nonce probe, minus the
    nonce, does not get its style."""
    register_component("bare-style", module=UNNONCED_MODULE)
    handle = _serve(
        indah.create_app(session_factory=lambda: Session(Column(children=[custom("bare-style")])))
    )
    ctx, page = _page(browser)
    try:
        page.goto(handle.url, wait_until="domcontentloaded")
        el = page.locator("indah-x-bare-style")
        expect(el).to_be_visible()
        assert el.evaluate(COLOUR) != "rgb(7, 8, 9)"
    finally:
        ctx.close()
        handle.stop()
