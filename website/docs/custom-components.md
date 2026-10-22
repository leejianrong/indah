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
| `text` | A node prop (in a `List`, an item field) whose value becomes the element's text content |
| `literal` | Fixed text content, shown as written, such as `"Remove"` on a button; not together with `text` |
| `bind` | `{attribute: prop}` - the element attribute follows the node prop, patched reactively |
| `on` | `{domEvent: {event, prop}}` - a DOM event posts the indah `event`; `prop` names the signal the value is written into |
| `children` | Nested render specs, for a small composite. A nested spec's `on` round-trips like the top-level one |

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

## A component with its own JavaScript

A render spec is one element tree. When you need a drawing, per-item state or your own events, ship an
ES module instead (ADR-0039). The module is your own finished file; indah needs no Node and does not
build it.

```python
indah.register_component(
    "tier-rail",
    module="modules/tier-rail.js",  # a file or bytes, read once at registration; never a URL
    events=["pick"],  # CustomEvents forwarded to Python
    two_way={"value": "change"},  # detail.value of "change" writes the `value` signal
    fallback="steps",  # shown as text if the module cannot load or run
)

rail = indah.custom(
    "tier-rail",
    steps=["Seed", "Sprout", "Bloom"],  # props arrive as properties
    value=tier,  # a Signal: set from Python, and written by "change"
    on_pick=lambda detail: print(detail["label"]),  # may be async; guard() and audit apply
)
```

The module's default export is a class extending `HTMLElement`. indah defines it as `indah-x-<type>`,
sets each prop as a property (before the element is attached, and again on every change), and forwards
the events you listed. `examples/studio/modules/tier-rail.js` is a complete one.

```js
export default class TierRail extends HTMLElement {
  set steps(v) { /* draw the steps with textContent, not innerHTML */ }
  pick(i) {
    this.dispatchEvent(new CustomEvent("pick", { detail: { index: i } }));
  }
}
```

Things to know:

- **Theming.** CSS variables pass through a shadow root, so use the shell's tokens (`--surface`,
  `--text`, `--muted`, `--primary`, `--outline`, `--radius`, `--font-body`) and the module follows light
  and dark with no code.
- **Styles under a strict CSP.** Use a constructable stylesheet (`adoptedStyleSheets`), or a `<style>`
  carrying `el.cspNonce`, which the shell sets before the element is attached. A bare `<style>` is
  refused by `csp="strict"`.
- **Props are data.** Put them in with `textContent`; assigning one to `innerHTML` is an XSS hole you
  would create yourself.
- **Trust.** The module runs in the viewer's page with your app's origin. Register only files you wrote
  or vendored; never one a user supplied. Every session can load every registered module, so keep
  secrets out of the source.
- **Failure.** If the module cannot load, has no default export, or throws, the shell logs one console
  error and shows the `fallback` prop as plain text; the rest of the page keeps working.
- **Limits.** 1 MB per module and 64 module types per process. The type is lowercase words joined by
  hyphens. A module component cannot yet sit inside a `List` row or a table cell.

