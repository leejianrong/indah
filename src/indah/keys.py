"""Key-spec parsing for ``Shortcuts`` (ADR-0030).

A spec is one or more space-separated steps (a sequence, ``"g l"``); a step is optional
modifiers joined by ``+`` then one key: ``"a"``, ``"?"``, ``"escape"``, ``"mod+k"``.
``mod`` is Ctrl or Cmd (``ctrl``/``cmd``/``meta`` are aliases). The canonical form is
lower-case with modifiers ordered ``mod+alt+shift``; the shell uses the same rule, so
the wire carries canonical specs and a ``press`` event names one back.
"""

from __future__ import annotations

_ALIASES = {"ctrl": "mod", "control": "mod", "cmd": "mod", "meta": "mod", "option": "alt"}
_ORDER = ("mod", "alt", "shift")


def _step(step: str) -> str:
    if step.endswith("++"):  # the key is "+" itself
        mods, key = step[:-2].split("+") if step[:-2] else [], "+"
    else:
        *mods, key = step.split("+")
    if not key or any(not m for m in mods):
        raise ValueError(f"bad key step {step!r}")
    seen: set[str] = set()
    for raw in mods:
        mod = _ALIASES.get(raw, raw)
        if mod not in _ORDER:
            raise ValueError(f"unknown modifier {raw!r} in {step!r}")
        seen.add(mod)
    if key in _ORDER or key in _ALIASES:
        raise ValueError(f"key step {step!r} has only modifiers")
    return "+".join([m for m in _ORDER if m in seen] + [key])


def normalize_keys(spec: str) -> str:
    """The canonical form of ``spec``; raises ``ValueError`` if it is malformed."""
    steps = spec.lower().split()
    if not steps:
        raise ValueError("empty key spec")
    return " ".join(_step(s) for s in steps)
