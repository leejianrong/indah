"""Run the whole browser suite under a strict Content-Security-Policy (ADR-0038, IND-121).

Every app the e2e tests build gets ``csp="strict"`` unless a test sets its own, and every page
reports ``securitypolicyviolation`` events. A test that triggers one fails at teardown, so a
new component or shell change cannot quietly start needing inline code.
"""

import pytest

_LISTENER = """
window.__cspViolations = [];
document.addEventListener('securitypolicyviolation', (e) => {
  window.__cspViolations.push(e.violatedDirective + ' ' + e.blockedURI);
  console.error('INDAH-CSP-VIOLATION ' + e.violatedDirective + ' ' + e.blockedURI);
});
"""


@pytest.fixture(autouse=True)
def csp_everywhere(monkeypatch, request):
    import sys

    import indah
    import indah.app

    launch_module = sys.modules["indah.launch"]  # `indah.launch` the name is the function

    real = indah.app.create_app

    def with_csp(*args, **kwargs):
        kwargs.setdefault("csp", "strict")
        app = real(*args, **kwargs)
        apps.append(app)
        return app

    apps: list = []
    monkeypatch.setattr(indah, "create_app", with_csp)
    monkeypatch.setattr(indah.app, "create_app", with_csp)
    monkeypatch.setattr(launch_module, "create_app", with_csp)

    seen: list[str] = []
    try:
        from playwright.sync_api import Browser, BrowserContext
    except ImportError:  # no browser layer: the httpx tests still run under the policy
        Browser = BrowserContext = None

    if Browser is not None:
        real_new_context = Browser.new_context
        real_new_page = Browser.new_page

        def watch(context: BrowserContext) -> BrowserContext:
            context.add_init_script(_LISTENER)
            context.on(
                "console",
                lambda m: seen.append(m.text) if "INDAH-CSP-VIOLATION" in m.text else None,
            )
            return context

        def new_context(self, *a, **k):
            return watch(real_new_context(self, *a, **k))

        def new_page(self, *a, **k):
            page = real_new_page(self, *a, **k)
            watch(page.context)
            return page

        monkeypatch.setattr(Browser, "new_context", new_context)
        monkeypatch.setattr(Browser, "new_page", new_page)

    yield
    if request.node.get_closest_marker("expects_csp_violation"):
        return
    server_side = [v for app in apps for v in app.state.csp_violations]
    assert not seen and not server_side, f"CSP violations: {seen or server_side}"
