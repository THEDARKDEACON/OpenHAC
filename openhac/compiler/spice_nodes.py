"""SPICE node naming and ground aliasing (SPS-001, SPS-004)."""

from __future__ import annotations

import re

from openhac.core.base import OpenHaCError

# Primary Kirchhoff reference names (always node 0).
PRIMARY_GROUND_NAMES = frozenset({"GND", "VSS", "PGND", "EARTH", "VSSA"})

# Isolated analog/digital grounds stay named unless merged onto a primary ground.
ISOLATED_GROUND_NAMES = frozenset({"AGND", "DGND"})

_SANITIZE_RE = re.compile(r"[^A-Za-z0-9_]")


def _norm(name: str) -> str:
    return str(name or "").strip().upper()


def ground_alias_set(extra: list[str] | tuple[str, ...] | None = None) -> set[str]:
    """Return uppercase net names that map to SPICE node ``0``."""
    out = {n.upper() for n in PRIMARY_GROUND_NAMES}
    for n in extra or ():
        s = _norm(n)
        if s:
            out.add(s)
    return out


def merge_hint_ground_aliases(merge_hints: list[dict] | None) -> set[str]:
    """Nets merged onto a primary ground also become node ``0`` (SPS-001)."""
    extra: set[str] = set()
    primary = {_norm(n) for n in PRIMARY_GROUND_NAMES}
    for rec in merge_hints or ():
        a = _norm(str(rec.get("net_a") or ""))
        b = _norm(str(rec.get("net_b") or ""))
        if not a or not b:
            continue
        if a in primary and b not in primary:
            extra.add(b)
        if b in primary and a not in primary:
            extra.add(a)
    return extra


def is_ground_net(name: str, *, ground_names: set[str] | None = None) -> bool:
    g = ground_names if ground_names is not None else ground_alias_set()
    return _norm(name) in g


def spice_token(name: str, *, ground_names: set[str] | None = None) -> str:
    """Map a graph net name to a legal SPICE node token.

    Ground aliases become ``0``. Leading-digit names get an ``N_`` prefix (SPS-004).
    """
    raw = str(name or "").strip()
    if not raw:
        return "N_EMPTY"
    g = ground_names if ground_names is not None else ground_alias_set()
    if _norm(raw) in g:
        return "0"
    s = _SANITIZE_RE.sub("_", raw.replace(" ", "_").replace("-", "_").replace("/", "_"))
    s = re.sub(r"_+", "_", s).strip("_")
    if not s:
        s = "N_EMPTY"
    if s[0].isdigit():
        s = "N_" + s
    return s


def assert_no_sanitization_collisions(
    net_names: list[str],
    *,
    ground_names: set[str] | None = None,
) -> dict[str, str]:
    """Return original → token map; fail if two distinct non-ground nets collide (SPS-004)."""
    g = ground_names if ground_names is not None else ground_alias_set()
    mapping: dict[str, str] = {}
    token_owners: dict[str, str] = {}
    for raw in net_names:
        key = str(raw)
        tok = spice_token(key, ground_names=g)
        mapping[key] = tok
        if tok == "0":
            continue
        owner = token_owners.get(tok)
        if owner is not None and owner != key and _norm(owner) != _norm(key):
            raise OpenHaCError(
                f"SPS-004: distinct nets {owner!r} and {key!r} both sanitize to SPICE node {tok!r}."
            )
        token_owners[tok] = key
    return mapping
