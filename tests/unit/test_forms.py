"""``Form``: validators, when an error shows, the submit guard and server errors (ADR-0047)."""

import asyncio

import pytest

from indah import Button, Form, Select, TextInput, validators


def _props(component):
    """The wire props a component sends now (static plus each reactive one, read)."""
    out = dict(component.static_props())
    out.update({k: fn() for k, fn in component.reactive_props().items()})
    return out


def _form(**kw):
    seen = []
    form = Form(on_submit=lambda values: seen.append(dict(values)), **kw)
    email = form.text("email", label="Email", validate=[validators.required(), validators.email()])
    role = form.select("role", options=["viewer", "editor"], initial="viewer")
    return form, email, role, form.submit("Send"), seen


def _type(component, text):
    assert component.handle("input", {"value": text}) is True


@pytest.mark.unit
def test_the_form_builds_ordinary_components():
    form, email, role, button, _ = _form()
    assert isinstance(email, TextInput) and isinstance(role, Select) and isinstance(button, Button)


@pytest.mark.unit
def test_the_submit_button_is_disabled_until_the_form_is_valid():
    form, email, _, button, _ = _form()
    assert form.valid.value is False and _props(button)["disabled"] is True
    _type(email, "not-an-email")
    assert _props(button)["disabled"] is True
    _type(email, "ada@example.org")
    assert form.valid.value is True and _props(button)["disabled"] is False


@pytest.mark.unit
def test_an_error_is_silent_on_load_and_shows_once_the_field_changed():
    form, email, _, _, _ = _form()
    assert _props(email)["error"] is None  # empty and required, but untouched
    assert form.errors.value == {"email": "Required"}  # the form still knows
    _type(email, "oops")
    assert _props(email)["error"] == "Enter a valid email address"
    _type(email, "ada@example.org")
    assert _props(email)["error"] is None


@pytest.mark.unit
def test_a_field_changed_and_cleared_again_shows_its_error():
    form, email, _, _, _ = _form()
    _type(email, "a")
    _type(email, "")  # back to its initial value, but the person has been here
    assert _props(email)["error"] == "Required"
    form.reset()
    assert _props(email)["error"] is None


@pytest.mark.unit
def test_a_click_on_an_invalid_form_does_nothing():
    form, email, _, button, seen = _form()
    assert button.handle("click", {}) is True  # ignored, not a 400
    assert seen == []


@pytest.mark.unit
def test_the_submit_handler_itself_refuses_an_invalid_form():
    form, email, _, button, seen = _form()
    asyncio.run(form._click())  # what a click would call, were the button not disabled
    assert seen == []


@pytest.mark.unit
def test_a_valid_click_calls_on_submit_with_the_values():
    form, email, role, button, seen = _form()
    _type(email, "ada@example.org")
    assert role.handle("change", {"value": "editor"}) is True
    asyncio.run(_run(button))
    assert seen == [{"email": "ada@example.org", "role": "editor"}]


async def _run(button):
    result = button.handle("click", {})
    if asyncio.iscoroutine(result):
        await result


@pytest.mark.unit
def test_a_server_error_from_on_submit_shows_beside_the_field_until_it_changes():
    form = Form(on_submit=lambda values: {"email": "Already invited"})
    email = form.text("email", validate=[validators.required()])
    button = form.submit("Send")
    _type(email, "ada@example.org")
    asyncio.run(_run(button))
    assert _props(email)["error"] == "Already invited"
    assert form.valid.value is False  # a server error also blocks another submit
    _type(email, "ada@example.com")
    assert _props(email)["error"] is None and form.valid.value is True


@pytest.mark.unit
def test_an_async_on_submit_is_awaited_and_the_form_is_submitting_meanwhile():
    states = []

    async def slow(values):
        states.append(form.submitting.value)
        await asyncio.sleep(0)
        return {"email": "taken"}

    form = Form(on_submit=slow)
    email = form.text("email")
    button = form.submit("Go")
    _type(email, "a@b.co")
    asyncio.run(_run(button))
    assert states == [True] and form.submitting.value is False
    assert _props(email)["error"] == "taken"


@pytest.mark.unit
def test_submitting_disables_the_button():
    form = Form()
    form.text("a")
    button = form.submit("Go")
    assert _props(button)["disabled"] is False
    form.submitting.set(True)
    assert _props(button)["disabled"] is True


@pytest.mark.unit
def test_set_error_reset_and_values():
    form, email, role, _, _ = _form()
    _type(email, "ada@example.org")
    form.set_error("email", "No such domain")
    assert _props(email)["error"] == "No such domain"
    form.reset()
    assert form.values.value == {"email": "", "role": "viewer"}
    assert _props(email)["error"] is None
    with pytest.raises(KeyError):
        form.set_error("nope", "x")


@pytest.mark.unit
def test_a_validator_that_raises_counts_as_invalid():
    def boom(value):
        raise RuntimeError("bad")

    form = Form()
    form.text("a", validate=[boom])
    assert form.valid.value is False and form.errors.value == {"a": "Invalid"}


@pytest.mark.unit
def test_duplicate_field_names_are_refused():
    form = Form()
    form.text("a")
    with pytest.raises(ValueError):
        form.select("a", options=["x"])


@pytest.mark.unit
def test_the_builtin_validators():
    assert validators.required()("") == "Required"
    assert validators.required()("  ") == "Required"
    assert validators.required()("x") is None
    assert validators.min_length(3)("ab") == "Use at least 3 characters"
    assert validators.min_length(3)("abc") is None
    assert validators.max_length(3)("abcd") == "Use at most 3 characters"
    assert validators.pattern(r"\d+", "Digits only")("a1") == "Digits only"
    assert validators.pattern(r"\d+", "Digits only")("12") is None
    assert validators.email()("a@b.co") is None
    for bad in ("a", "a@b", "@b.co", "a b@c.co", "a@b@c.co"):
        assert validators.email()(bad) == "Enter a valid email address", bad
    assert validators.email()("") is None  # emptiness is `required`'s job


@pytest.mark.unit
def test_standalone_inputs_and_buttons_are_unchanged_on_the_wire():
    from indah import Signal

    assert "error" not in TextInput(Signal("")).reactive_props()
    assert "error" not in Select(Signal("a"), options=["a"]).reactive_props()
    assert "disabled" not in Button("x").reactive_props()
    assert Button("x").handle("click", {}) is False  # no handler: as before


@pytest.mark.unit
def test_a_button_with_a_disabled_source_ignores_a_click_while_disabled():
    from indah import Signal

    off, clicks = Signal(True), []
    button = Button("x", lambda: clicks.append(1), disabled=off)
    assert _props(button)["disabled"] is True
    assert button.handle("click", {}) is True and clicks == []
    off.set(False)
    assert button.handle("click", {}) is True and clicks == [1]
