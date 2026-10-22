# ADR-0039: Web-component bridge for custom components

- Status: **Accepted** 2026-10-22 (IND-149). Two open questions are settled by the IND-150 spike; if either fails this ADR is amended.
- Date: 2026-10-22
- Deciders: Jian (owner)
- Amends: ADR-0012 (a registered component may ship a module, not only a render spec)

## Context

ADR-0012 gave `register_component()` a declarative render spec: one allow-listed element tree,
props bound to attributes, one DOM event mapped to an indah event. That covers a colour input or a
meter. It cannot draw a five-dot tier rail, a per-minute activity strip or shaded text, because
there is no drawing, no per-item state and no custom event. semula needs several of these (R2-6),
and each one otherwise waits for an indah release.

ADR-0012 rejected "fetch a user JS bundle the shell `import()`s" on three grounds: it adds a build
step, an external request breaks base-path proxies (Colab, Runpod), and it widens the attack
surface. Since then:

- ADR-0032 added a lazily `import()`ed same-origin module (`/api/editor.js`), and the shell works
  under any mount prefix with relative URLs. A module served by the app itself is already allowed.
- ADR-0038 added a strict CSP with `script-src 'nonce-N' 'self'`, so a same-origin module loads with
  no policy change, and a cross-origin one cannot.
- indah does not need to build anything: the developer supplies a finished ES module. Their build
  tool, if any, is theirs. The wheel stays Node-free at install and runtime.

## Decision

A component may be registered with a **module** instead of a render spec. The shell loads the
module once, defines a custom element from it, and keeps that element in sync with the node.

### Python API

```python
indah.register_component(
    "tier-rail",
    module="static/tier-rail.js",  # a path or bytes, read once at registration
    events=["pick"],  # CustomEvent names forwarded to Python
    two_way={"value": "change"},  # prop -> CustomEvent whose detail.value writes it back
    fallback="steps",  # a prop shown as text if the module cannot run
)

rail = indah.custom("tier-rail", steps=steps_signal, value=picked, on_pick=handle_pick)
```

- Exactly one of `render=` and `module=`. Everything else about `register_component` and
  `custom()` is unchanged, and a spec component behaves as before.
- `module` is a file path (absolute, or relative to the working directory, like `create_app(logo=)`)
  or `bytes`. It is **never a URL**. The file is read at registration and held in memory, so a path
  never reaches the request handler. Limit 1 MB per module; the registry takes a bounded number.
- `on_<event>=fn` takes the event's `detail` (JSON) as its argument. Handlers can be `async` and
  go through `guard()` and the audit hook exactly like a built-in event.
- `two_way` mirrors what `on` does in a render spec: the CustomEvent's `detail.value` is written to
  the bound `Signal`.
- Props that are `Signal`s or `Computed`s are reactive; other props are static, as in ADR-0012.

### The module contract

The module's **default export is a class extending `HTMLElement`**. It does not call
`customElements.define`; the shell does, under the name `indah-x-<type>`, so a module cannot take a
tag name it was not given or redefine a built-in.

- **Props are properties.** The shell sets each prop as `el.<prop> = value` before the element is
  attached, so `connectedCallback` sees initial state. A signal change sets the property again.
  Values are JSON data (strings, numbers, booleans, null, arrays, objects).
- **Events are CustomEvents.** A module reports interaction with `this.dispatchEvent(new
  CustomEvent("pick", {detail: {...}}))`. Only names listed in `events` or `two_way` are forwarded;
  others stay in the browser. `detail` is posted as the payload of the normal `POST api/event`.
- **Theming.** CSS custom properties inherit through shadow roots, so the module styles itself with
  the shell's tokens (`--bg`, `--surface`, `--text`, `--muted`, `--primary`, `--outline`, `--radius`, `--font-body`, `--font-mono`, ADR-0014) and follows the light and
  dark toggle with no code. A module that ignores the tokens is the developer's choice.
- **Styles under the CSP.** `style-src` allows `'nonce-N'` plus `style-src-attr 'unsafe-inline'`. The
  shell exposes the page nonce on the element (`el.cspNonce`) so a module can put it on a `<style>`
  in its shadow root; setting `el.style.x` and `style=` attributes work as for any component.
  Constructable stylesheets (`adoptedStyleSheets`) are the preferred route, subject to the first
  verification item below.

### Wire format (additive, `protocol_version` stays 1)

The node's `type` is the registered type, as with a spec component. A new reserved static prop
`_module`, sent once in the `init` snapshot like `_spec`, replaces it:

```json
{"id": "n7", "type": "tier-rail", "props": {
  "_module": {"url": "api/components/tier-rail.js?v=3f9a1c", "tag": "indah-x-tier-rail",
              "events": ["pick", "change"], "fallback": "steps"},
  "steps": [...], "value": 2}}
```

`url` is relative (works under any base path) and carries a content hash, so it can be cached
forever and a new version is fetched at once. The shell routes a node to the bridge renderer when
`_module` is present, to the spec renderer when `_spec` is, and otherwise to a built-in.

Per ADR-0005's amendment, a new reserved prop and a new route are additive. `docs/protocol.md`
documents `_module` and the route when IND-150 ships.

### Serving

`GET api/components/<type>.js` returns the registered bytes with `text/javascript`, an ETag and
`Cache-Control: public, max-age=31536000, immutable` when the request carries the matching `?v=`
hash, `no-cache` otherwise. `<type>` must match `^[a-z][a-z0-9]*(-[a-z0-9]+)*$` and be in the
registry; anything else is `404`. No client value is ever turned into a file path.

### Lifecycle

1. First render of the type: `import(url)`, once per page, cached. `customElements.define` if the
   tag is free.
2. Create the element, set properties, attach. The module runs `connectedCallback`.
3. Patch: the shell sets the changed property. A burst is coalesced to one set per frame.
4. Remove: `disconnectedCallback`. A module must release timers, observers and listeners there.
5. Reconnect and resume (ADR-0002, ADR-0013): a fresh `init` reconciles by node id, so a surviving
   node keeps its element and gets property sets, not a new element. A node that disappears is
   removed.
6. **Focus ownership.** For a `two_way` prop the shell does not set the property while the element
   contains focus, and reapplies the latest value on blur, as the built-in inputs do (ADR-0013).

### Failure

An error in `import()`, a missing default export, a throw in the constructor or `connectedCallback`
is caught per node. The shell logs one console error, renders the `fallback` prop as plain text (or
nothing), and leaves the rest of the tree alone. An uncaught error inside a module's own event
handlers is the module's.

## Threat model

The module is **code that runs in the viewer's page with the app's full origin privileges**: it can
call `POST api/event` as the viewer, read the DOM, read anything not `HttpOnly`. CSP and the tag
allowlist of ADR-0012 do not contain it. It is exactly as trusted as the developer's server code,
and the design keeps it that way:

| Threat | Mitigation |
|--------|-----------|
| A user picks or uploads a module | `module=` is read at registration from a path the developer wrote. There is no runtime path, no URL and no upload route to a module. A hosted app must never call `register_component` with tenant-supplied code. |
| Path traversal on the route | The route takes a type name that matches a strict pattern and is in the registry; it serves bytes held in memory. |
| Third-party script | A URL is not accepted, and `script-src 'self'` would refuse a cross-origin import anyway. Vendor the file. |
| One tenant's module reaches another tenant | The registry is process-wide (as in ADR-0012), so every session can load every registered module. `Policy` does not gate the file. Treat the module source as public and keep secrets out of it; gate what the component *shows* with `Policy` and `ephemeral` props as usual. |
| Props rendered as HTML (XSS) | The shell sets data, not markup. A module that does `innerHTML = prop` creates the hole itself; the guidance and the demo module use `textContent` and DOM APIs. |
| Event flooding | Forwarded events use the existing event path: body cap, rate limit, origin guard, `guard()` and audit. Only declared event names are forwarded. |
| A secret prop in the DOM | Ephemeral props (ADR-0036) work on a bridge component like any other; the audit hook marks a component sensitive on request. The element holds the value in memory, so do not use a bridge component to display a secret that must not be inspectable. |
| Module bloat | 1 MB per module, a bounded count, and a content-hashed URL so it downloads once. |
| Sandboxing | Not provided. An `<iframe sandbox>` would isolate but breaks theming, sizing, focus and accessibility; it is kept open as a later `isolation="iframe"` option. |

## Alternatives considered

| Option | Why not |
|--------|---------|
| Grow the render spec (canvas, loops, per-item state) | Becomes a template language, which ADR-0012 refused; every new visual still needs an indah release. |
| Built-in components for each bespoke visual (tier rail, strip, shaded text) | Right for visuals that prove general (IND-157, 162, 163 stay as promotions), wrong as the only route. |
| A module that calls `customElements.define` itself | It could shadow a built-in or fight another module over a name. The shell owns the namespace. |
| Load from a URL or a CDN | Blocked by the CSP and by ADR-0001's proxy limits; a supply-chain hole. |
| A sandboxed iframe per component | Isolation at the cost of theming, layout and accessibility; deferred, not rejected. |
| Compile user Svelte at install or runtime | Needs Node, which R4 forbids. |

## Consequences

- semula can build its tier rail, activity strip and shaded text without waiting for a release, and
  IND-157, 162 and 163 become promotions of components that already work.
- The public contract gains one reserved prop (`_module`) and one route; `protocol_version` stays 1.
  An ejected or third-party client that ignores `_module` shows the fallback text or nothing.
- The shell grows by one small renderer (an `import()`, `define`, property sets, a fallback).
  Measure it; it must stay well under the editor's weight and load nothing for an app without one.
- Developers take on JavaScript and its testing. indah supplies a demo module and a Studio page.
- A bridge component is not available inside a render-spec `List` row or a table cell until the spec
  can name one. That is the interaction with IND-148 and is left to a follow-up.

## Build plan for IND-150

First, a half-day spike with e2e under `csp="strict"` to settle the two open questions; if either
fails the ADR is amended before the build continues:

1. Do constructable stylesheets and the `el.cspNonce` route both work in a shadow root under the
   strict policy, with no violation?
2. Does the module URL resolve and cache correctly under a mount prefix and through the Colab
   window-buffering proxy used in `tests/e2e/test_proxy_buffering.py`?

Then, tests first:

- Unit: `register_component(module=)` accepts a path and bytes, refuses a URL, both `render` and
  `module`, a bad type name, a missing file and an oversize module; `custom()` wires `on_<event>`
  and `two_way`; `_module` appears in the snapshot and not in patches.
- Integration: the route serves the bytes with the right headers, `304` on a matching ETag, `404`
  for an unregistered or malformed name (including `..` and encoded slashes); a secure app serves
  it the same way; the event round trip reaches the handler and `guard()` applies.
- E2E (strict CSP, fails on any violation): a demo module with props, a signal update and a
  CustomEvent round trip; light and dark themes via tokens; a throwing module shows its fallback
  and the page still works; resume after a dropped stream keeps the element; a two-way component
  keeps typing while a late echo arrives.
- Studio page (`covers=("register_component",)` extends to the new arguments) and a docs section;
  CHANGELOG entry; `docs/protocol.md` gains `_module` and the route.
- Out of scope for IND-150: a bridge component inside a `List` row or table cell, hot reload of a
  module, and iframe isolation.
