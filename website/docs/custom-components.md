# Custom components

When the starter set does not cover what you need, register a custom component. It
works without forking the framework and without a Node build, because the shell
ships pre-built: a custom type ships a **declarative render spec** the shell's
generic renderer interprets at runtime, not new Svelte code.

## A worked example: a colour picker

```python
import indah

indah.register_component(
    "colorpicker",
    render={
        "tag": "input",  # one allowlisted HTML element
        "attrs": {"type": "color"},  # static attributes
        "bind": {"value": "value"},  # element attribute <- node prop
        "on": {"input": {"event": "input", "prop": "value"}},  # UI change -> signal
    },
)

colour = indah.Signal("#ff8800")
picker = indah.custom("colorpicker", value=colour)  # two-way bound, like a built-in
```

`register_component()` validates the spec once; `custom(type, **props)` builds
value-bearing instances that round-trip exactly like a built-in component. Read the
current value with `colour.value` - it follows what the user picked.

## The render spec

| Field | Meaning |
|-------|---------|
| `tag` | The HTML element to create, from a safe allowlist (no `script` / `iframe` / `style`) |
| `attrs` | Static attributes `{name: value}` |
| `class` | A static class string |
| `text` | A node prop whose value becomes the element's text content |
| `bind` | `{attribute: prop}` - the element attribute follows the node prop, patched reactively |
| `on` | `{domEvent: {event, prop}}` - a DOM event posts the indah `event`; `prop` names the signal the value is written into |
| `children` | Nested render specs, for a small composite |

## What the spec can and cannot do

The spec is data, not code, and the tag set is inert, so a custom component cannot
inject a script or fetch remote code. That keeps indah's dev-tool threat model
intact - registering a component never widens the attack surface.

!!! warning "No loops or conditionals, by design"
    The spec deliberately cannot express loops or conditionals. A component that
    needs those is the signal to reach for a hand-written frontend against the
    [protocol](protocol.md), not a larger spec language.

Validation is strict: a disallowed tag, a type that collides with a built-in, an
empty type, or a malformed spec is rejected with a `ValueError` at registration
time, not at render time.

## How it travels

The spec rides on the wire as a reserved `_spec` prop, so it is part of the public
[protocol](protocol.md). The shell's generic renderer reads `_spec`, builds the
element, binds its attributes to node props, and wires its DOM events back to your
signals - all at runtime, with no rebuild.
