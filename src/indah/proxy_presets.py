"""Named presets for ``trusted_proxies`` (IND-204, IND-198).

``create_app(trusted_proxies=["fly"])`` is shorthand for a list you could have typed. A preset
expands to explicit IPs and CIDRs before anything else looks at it, so ``parse_trusted`` and the
rest of the proxy handling (ADR-0034) are unchanged. Presets compose with explicit entries
(``["cloudflare", "203.0.113.7"]``) and never turn on by themselves: ``"auto"`` and ``"*"`` are
refused, because guessing which addresses are your proxies would let a client spoof
``X-Forwarded-For``.

==============  ========================================================================
``private``     RFC 1918: ``10.0.0.0/8``, ``172.16.0.0/12``, ``192.168.0.0/16``
``k8s``         ``private`` plus ``100.64.0.0/10`` (CGNAT) and ``fc00::/7`` (unique local)
``cloudflare``  Cloudflare's published edge ranges, vendored in ``indah.cloudflare_ips``
``fly``         ``172.16.0.0/12`` (Fly's proxy connects from there) plus the app's public
                ingress IPs: from ``INDAH_FLY_IPS``, else a DNS lookup of
                ``<FLY_APP_NAME>.fly.dev`` at startup
==============  ========================================================================

A preset trusts every address in it. ``private`` and ``k8s`` trust a whole network, so another
pod or host in it can set ``X-Forwarded-For`` and be believed: narrow them to your ingress when
you know its range.
"""

from __future__ import annotations

import ipaddress
import re
import socket
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from typing import NamedTuple

from . import cloudflare_ips

PRESET_NAMES: tuple[str, ...] = ("cloudflare", "fly", "k8s", "private")

PRIVATE: tuple[str, ...] = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
K8S: tuple[str, ...] = (*PRIVATE, "100.64.0.0/10", "fc00::/7")
FLY_PRIVATE = "172.16.0.0/12"

_DNS_SECONDS = 3.0
_WORD = re.compile(r"[A-Za-z][A-Za-z_\-]*")

Resolver = Callable[[str], Iterable[str]]


class Expanded(NamedTuple):
    """The explicit entries a ``trusted_proxies`` value stands for, and the presets it used."""

    entries: tuple[str, ...]
    presets: tuple[str, ...]


def _valid_presets() -> str:
    return ", ".join(PRESET_NAMES)


def _split(entries: object) -> list[str]:
    if entries is None:
        return []
    if isinstance(entries, str):
        return [part.strip() for part in entries.split(",") if part.strip()]
    return [str(item).strip() for item in entries]  # type: ignore[attr-defined]


def _classify(item: str) -> str | None:
    """The preset name for ``item``, or ``None`` for a plain IP or CIDR; refuses the rest."""
    lowered = item.lower()
    if item == "*":
        raise ValueError(
            "trusted_proxies: '*' is refused, it would make every forwarded header believable. "
            f"Name a preset ({_valid_presets()}) or list your proxies' IPs or CIDRs."
        )
    if lowered == "auto":
        raise ValueError(
            "trusted_proxies: 'auto' is refused on purpose: guessing which addresses are your "
            "proxies would let a client spoof X-Forwarded-For. "
            f"Name a preset ({_valid_presets()}) or list your proxies' IPs or CIDRs."
        )
    if lowered in PRESET_NAMES:
        return lowered
    if _WORD.fullmatch(item):
        raise ValueError(
            f"trusted_proxies: unknown preset {item!r}. Valid presets: {_valid_presets()}. "
            "Or list IPs or CIDRs."
        )
    return None


def _key(entry: str) -> str:
    """``entry`` in a form that makes ``1.2.3.4`` and ``1.2.3.4/32`` equal, for de-duplication."""
    try:
        return str(ipaddress.ip_network(entry, strict=False))
    except ValueError:
        return entry


def _resolve_dns(host: str) -> list[str]:
    """Addresses ``host`` resolves to (IPv4 and IPv6), giving up after a few seconds."""
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="indah-dns")
    try:
        future = pool.submit(socket.getaddrinfo, host, None, 0, socket.SOCK_STREAM)
        infos = future.result(timeout=_DNS_SECONDS)
    finally:
        pool.shutdown(wait=False)
    seen: list[str] = []
    for info in infos:
        address = str(info[4][0]).split("%", 1)[0]
        if address not in seen:
            seen.append(address)
    return seen


def fly_help(app: str | None) -> str:
    """What to run and what to set when the Fly public IPs cannot be found (IND-198)."""
    where = (
        f"looking up {app}.fly.dev gave no addresses"
        if app
        else "FLY_APP_NAME is not set, so this does not look like a Fly machine"
    )
    target = app or "<app>"
    return (
        "trusted_proxies preset 'fly' needs the app's public ingress IP addresses, and could not "
        f"find them ({where}). Run `fly ips list -a {target}` and set "
        'INDAH_FLY_IPS=<ipv4>,<ipv6> (then trusted_proxies=["fly"] works), or list them yourself: '
        'trusted_proxies=["172.16.0.0/12", "<ipv4>", "<ipv6>"]. Without the app\'s own public '
        "addresses every visitor resolves to the ingress address and shares one rate-limit bucket."
    )


def _fly_entries(environ: Mapping[str, str], resolve: Resolver) -> tuple[str, ...]:
    configured = (environ.get("INDAH_FLY_IPS") or "").strip()
    if configured:
        ips = [part.strip() for part in configured.split(",") if part.strip()]
        for ip in ips:
            try:
                ipaddress.ip_address(ip)
            except ValueError:
                raise ValueError(
                    f"INDAH_FLY_IPS: {ip!r} is not a single IP address. List the addresses "
                    "from `fly ips list`, comma separated (a network would trust too much)."
                ) from None
    else:
        app = (environ.get("FLY_APP_NAME") or "").strip()
        ips = []
        if app:
            try:
                ips = [ip for ip in resolve(f"{app}.fly.dev") if _is_ip(ip)]
            except Exception:  # noqa: BLE001 - any lookup failure means "could not find them"
                ips = []
        if not ips:
            raise ValueError(fly_help(app or None))
    return (FLY_PRIVATE, *ips)


def _is_ip(text: str) -> bool:
    try:
        ipaddress.ip_address(text)
    except ValueError:
        return False
    return True


def expand_trusted(
    entries: object,
    *,
    environ: Mapping[str, str] | None = None,
    resolve: Resolver | None = None,
) -> Expanded:
    """Expand presets in a ``trusted_proxies`` value to explicit entries.

    ``entries`` is a list (or one string, comma separated). Plain IPs and CIDRs pass through for
    ``parse_trusted`` to validate; a preset name expands in place; duplicates are dropped, first
    one wins. ``"auto"``, ``"*"`` and unknown names raise ``ValueError`` naming the valid presets.
    ``environ`` and ``resolve`` default to the process environment and a DNS lookup; tests pass
    their own.
    """
    import os

    env = os.environ if environ is None else environ
    lookup = _resolve_dns if resolve is None else resolve
    out: list[str] = []
    seen: set[str] = set()
    used: list[str] = []

    def add(entry: str) -> None:
        key = _key(entry)
        if key not in seen:
            seen.add(key)
            out.append(entry)

    for item in _split(entries):
        preset = _classify(item)
        if preset is None:
            add(item)
            continue
        if preset not in used:
            used.append(preset)
        if preset == "private":
            parts: Iterable[str] = PRIVATE
        elif preset == "k8s":
            parts = K8S
        elif preset == "cloudflare":
            parts = (*cloudflare_ips.IPV4, *cloudflare_ips.IPV6)
        else:
            parts = _fly_entries(env, lookup)
        for part in parts:
            add(part)
    return Expanded(tuple(out), tuple(used))


def check_entries(entries: object) -> None:
    """Validate a ``trusted_proxies`` value without expanding or resolving anything.

    For configuration read early (the environment): presets are accepted by name, the rest must
    be a valid IP or CIDR, and ``auto``, ``*`` and unknown names are refused. Raises ``ValueError``.
    """
    from .proxy import parse_trusted

    for item in _split(entries):
        if _classify(item) is None:
            parse_trusted([item])


def fly_gap(
    entries: object,
    *,
    environ: Mapping[str, str] | None = None,
    resolve: Resolver | None = None,
) -> tuple[str, ...]:
    """The app's public IPs that an explicit ``trusted_proxies`` list on Fly does not cover.

    The classic mistake on Fly is trusting only ``172.16.0.0/12``: Fly appends the app's own
    ingress address to ``X-Forwarded-For``, indah stops at it, and every visitor resolves to that
    one address. Returns those addresses (empty when not on Fly, when the list is empty because
    the IND-200 warning covers that, or when the lookup fails: never guess).
    """
    import os

    env = os.environ if environ is None else environ
    app = (env.get("FLY_APP_NAME") or "").strip()
    items = _split(entries)
    if not app or not items:
        return ()
    lookup = _resolve_dns if resolve is None else resolve
    try:
        ips = [ip for ip in lookup(f"{app}.fly.dev") if _is_ip(ip)]
    except Exception:  # noqa: BLE001
        return ()
    networks = []
    for item in items:
        try:
            networks.append(ipaddress.ip_network(item, strict=False))
        except ValueError:
            continue
    return tuple(
        ip
        for ip in ips
        if not any(ipaddress.ip_address(ip) in net for net in networks if net.version == _v(ip))
    )


def _v(ip: str) -> int:
    return ipaddress.ip_address(ip).version
