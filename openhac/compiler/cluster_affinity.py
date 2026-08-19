"""Cluster affinity + hierarchical placement for module AABB floorplanning.

PCB modules used for schematic/DRC clarity (IC + nearby passives) must not
float as independent Z3 rooms. This module:

1. Discovers IC↔passive pairs from explicit ``cluster_with``, then a generic
   ``*LocalCaps`` / ``*Decoupling`` suffix fallback (prefix → parent name).
2. Optionally merges satellites into the parent AABB for Z3 (hierarchical placer).
3. Otherwise injects ``constrain_distance_max`` so centers stay nearby.
4. After Z3, places satellite module origins beside the parent.

Board-specific name tables are not used; designs that need clustering should
call ``Module.cluster_with``.
"""

from __future__ import annotations

import logging
import math
import os
import re
from typing import Any

logger = logging.getLogger("openhac.cluster_affinity")

_PASSIVE_SUFFIX_RE = re.compile(
    r"(?P<head>.+?)(?P<suf>LocalCaps?|Decoupling|Decaps?|Passives?|Bypass|Caps)$",
    re.IGNORECASE,
)


def _truthy(name: str, default: bool = False) -> bool:
    raw = (os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def _env_float(name: str, default: float) -> float:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return float(default)
    try:
        return float(raw)
    except Exception:
        return float(default)


def _module_list(board) -> list[Any]:
    try:
        mods = list(getattr(board, "_get_all_modules", lambda: [])())
    except Exception:
        mods = list(getattr(board, "modules", []) or [])
    return [m for m in mods if m is not None]


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(name or "").lower())


def _find_parent_by_hints(mods: list[Any], satellite: Any, hints: tuple[str, ...]) -> Any | None:
    sat_id = id(satellite)
    scored: list[tuple[int, Any]] = []
    for m in mods:
        if id(m) == sat_id:
            continue
        if getattr(m, "_z3_skip", False):
            continue
        n = str(getattr(m, "name", "") or "")
        nn = _norm(n)
        for i, hint in enumerate(hints):
            h = _norm(hint)
            if h and h in nn:
                scored.append((i, m))
                break
    if not scored:
        return None
    scored.sort(key=lambda t: t[0])
    return scored[0][1]


def discover_cluster_pairs(board) -> list[tuple[Any, Any]]:
    """Return ``(parent, satellite)`` pairs for affinity / merge."""
    mods = _module_list(board)
    pairs: list[tuple[Any, Any]] = []
    seen_sat: set[int] = set()

    # Explicit Module.cluster_with(parent)
    for m in mods:
        parent = getattr(m, "_cluster_parent", None)
        if parent is None:
            continue
        if id(m) in seen_sat:
            continue
        pairs.append((parent, m))
        seen_sat.add(id(m))

    # Generic suffix: FooLocalCaps → a module whose name contains Foo
    for m in mods:
        if id(m) in seen_sat:
            continue
        name = str(getattr(m, "name", "") or "")
        mo = _PASSIVE_SUFFIX_RE.match(name)
        if not mo:
            continue
        head = mo.group("head")
        if not head:
            continue
        parent = _find_parent_by_hints(mods, m, (head, head[:4] if len(head) >= 4 else head))
        if parent is not None:
            pairs.append((parent, m))
            seen_sat.add(id(m))

    return pairs


def _cluster_gap_mm() -> float:
    return max(0.5, _env_float("OPENHAC_CLUSTER_GAP_MM", 2.0))


def _default_max_center_mm(parent, satellite) -> float:
    """Loose L1 center budget so merge/affinity stays SAT-friendly."""
    try:
        pw = float(getattr(parent, "width", 10) or 10)
        ph = float(getattr(parent, "height", 10) or 10)
        sw = float(getattr(satellite, "width", 10) or 10)
        sh = float(getattr(satellite, "height", 10) or 10)
    except Exception:
        return 40.0
    # Diagonal of combined side-by-side pack + slack
    return max(25.0, 0.5 * (pw + sw) + 0.5 * max(ph, sh) + 15.0)


def merge_cluster_for_z3(parent, satellite, *, gap_mm: float | None = None) -> None:
    """Exclude *satellite* from Z3; expand *parent* AABB; place sat beside parent after solve.

    Always recomputes the parent AABB from current sizes so a later pcbnew pack
    shrink-wrap (compile retry) cannot leave satellites hanging off an IC-only box.
    """
    already = bool(getattr(satellite, "_z3_skip", False) and getattr(satellite, "_placement_anchor", None) is parent)
    g = float(gap_mm if gap_mm is not None else _cluster_gap_mm())
    pw = float(getattr(parent, "width", 10) or 10)
    ph = float(getattr(parent, "height", 10) or 10)
    sw = float(getattr(satellite, "width", 10) or 10)
    sh = float(getattr(satellite, "height", 10) or 10)

    side_w, side_h = pw + g + sw, max(ph, sh)
    below_w, below_h = max(pw, sw), ph + g + sh
    use_below = (below_w * below_h) < (side_w * side_h)
    if use_below:
        parent.width, parent.height = below_w, below_h
        ox, oy = 0.0, ph + g
    else:
        parent.width, parent.height = side_w, side_h
        ox, oy = pw + g, 0.0

    satellite._z3_skip = True
    satellite._placement_anchor = parent
    satellite._placement_offset_mm = (ox, oy)
    satellite._cluster_parent = parent
    if already:
        return
    logger.info(
        "Cluster merge: %s absorbs %s → room %.1fx%.1f (sat offset +%.1f,%.1f)",
        getattr(parent, "name", "?"),
        getattr(satellite, "name", "?"),
        parent.width,
        parent.height,
        ox,
        oy,
    )


def merge_satellites_for_z3(parent, satellites: list, *, gap_mm: float | None = None) -> None:
    """Pack parent core AABB + all satellites once (idempotent across compile retries)."""
    from openhac.compiler.placement_engine import shelf_pack

    sats = [s for s in satellites if s is not None]
    if not sats:
        return
    g = float(gap_mm if gap_mm is not None else _cluster_gap_mm())
    core = getattr(parent, "_cluster_core_wh", None)
    if core is None:
        core = (float(getattr(parent, "width", 10) or 10), float(getattr(parent, "height", 10) or 10))
        parent._cluster_core_wh = core
    pw, ph = float(core[0]), float(core[1])
    items: list[tuple[object, float, float]] = [("__core__", pw, ph)]
    for s in sats:
        items.append((id(s), float(getattr(s, "width", 10) or 10), float(getattr(s, "height", 10) or 10)))
    pos, pack_w, pack_h = shelf_pack(items, gap=g, largest_first=True)
    cx, cy = pos.get("__core__", (0.0, 0.0))
    parent.width, parent.height = pack_w, pack_h
    for s in sats:
        sx, sy = pos.get(id(s), (pw + g, 0.0))
        s._z3_skip = True
        s._placement_anchor = parent
        s._placement_offset_mm = (float(sx) - cx, float(sy) - cy)
        s._cluster_parent = parent
    logger.info(
        "Cluster merge: %s absorbs %s → room %.1fx%.1f",
        getattr(parent, "name", "?"),
        ",".join(str(getattr(s, "name", "?")) for s in sats),
        parent.width,
        parent.height,
    )


def apply_distance_max(board, parent, satellite, max_mm: float | None = None) -> None:
    """Inject ``constrain_distance_max`` if not already present for the pair."""
    cap = max_mm
    if cap is None:
        cap = getattr(satellite, "_cluster_max_mm", None)
    if cap is None:
        cap = _default_max_center_mm(parent, satellite)
    cap = float(cap)

    existing = getattr(board, "constraints", None) or []
    for rule in existing:
        if rule.get("type") != "distance_max":
            continue
        args = rule.get("args") or ()
        if len(args) >= 2 and (
            (args[0] is parent and args[1] is satellite)
            or (args[0] is satellite and args[1] is parent)
        ):
            return
    board.constrain_distance_max(parent, satellite, cap)
    logger.info(
        "Cluster affinity: distance_max(%s, %s, %.1f mm)",
        getattr(parent, "name", "?"),
        getattr(satellite, "name", "?"),
        cap,
    )


def mark_nested_parents_skip_z3(board) -> int:
    """Leaf-only Z3: skip modules that only nest other modules (no leaf parts)."""
    if not _truthy("OPENHAC_Z3_LEAF_ONLY", default=True):
        return 0
    from openhac.core.module import Module

    n = 0
    for mod in _module_list(board):
        kids = list(getattr(mod, "components", []) or [])
        has_nested = any(isinstance(c, Module) for c in kids)
        has_leaf = any(not isinstance(c, Module) for c in kids)
        if has_nested and not has_leaf:
            if not getattr(mod, "_z3_skip", False):
                mod._z3_skip = True
                n += 1
                logger.info("Z3 leaf-only: skipping empty nest parent %s", getattr(mod, "name", "?"))
    return n


def apply_cluster_affinity(board) -> dict[str, int]:
    """Apply auto clustering before autosize / Z3.

    Env:
      ``OPENHAC_CLUSTER_AFFINITY`` — default on; ``0`` disables.
      ``OPENHAC_PLACEMENT_MERGE_CLUSTERS`` — default on; merge satellites into parent AABB.
      ``OPENHAC_CLUSTER_GAP_MM`` — gap between parent and satellite when merged (default 2).
      ``OPENHAC_Z3_LEAF_ONLY`` — default on; skip empty nest parents in Z3.
    """
    stats = {"pairs": 0, "merged": 0, "distance_max": 0, "leaf_skip": 0}
    if not _truthy("OPENHAC_CLUSTER_AFFINITY", default=True):
        stats["leaf_skip"] = mark_nested_parents_skip_z3(board)
        return stats

    merge = _truthy("OPENHAC_PLACEMENT_MERGE_CLUSTERS", default=True)
    pairs = discover_cluster_pairs(board)
    stats["pairs"] = len(pairs)
    grouped: dict[int, tuple[Any, list[Any]]] = {}
    for parent, sat in pairs:
        force_max = bool(getattr(sat, "_force_distance_max_only", False))
        if merge and not force_max:
            bucket = grouped.setdefault(id(parent), (parent, []))
            bucket[1].append(sat)
        else:
            apply_distance_max(board, parent, sat)
            stats["distance_max"] += 1
    for parent, sats in grouped.values():
        merge_satellites_for_z3(parent, sats)
        stats["merged"] += len(sats)

    stats["leaf_skip"] = mark_nested_parents_skip_z3(board)
    if stats["pairs"] or stats["leaf_skip"]:
        logger.info(
            "Cluster affinity: pairs=%s merged=%s distance_max=%s leaf_skip=%s",
            stats["pairs"],
            stats["merged"],
            stats["distance_max"],
            stats["leaf_skip"],
        )
    return stats


def z3_modules(board) -> list[Any]:
    """Modules that participate in the Z3 AABB solve."""
    return [m for m in _module_list(board) if not getattr(m, "_z3_skip", False)]


def apply_satellite_offsets_after_z3(board) -> int:
    """Place merged satellites relative to their parent after Z3 assigns parent coords."""
    n = 0
    for mod in _module_list(board):
        parent = getattr(mod, "_placement_anchor", None)
        if parent is None:
            continue
        ox, oy = getattr(mod, "_placement_offset_mm", (0.0, 0.0))
        px = getattr(parent, "placed_x", None)
        py = getattr(parent, "placed_y", None)
        if px is None or py is None:
            continue
        mod.placed_x = float(px) + float(ox)
        mod.placed_y = float(py) + float(oy)
        n += 1
        logger.info(
            "  - %s: (%.1f, %.1f) [cluster satellite of %s]",
            getattr(mod, "name", "?"),
            mod.placed_x,
            mod.placed_y,
            getattr(parent, "name", "?"),
        )
    return n


def apply_grid_fallback_placement(board) -> None:
    """Deterministic non-overlapping grid when Z3 fails — never pile everything at (5,5)."""
    mods = z3_modules(board)
    if not mods:
        mods = _module_list(board)
    try:
        bw = float(board.size_mm[0])
        bh = float(board.size_mm[1])
    except Exception:
        bw, bh = 100.0, 100.0
    margin = 5.0
    x = margin
    y = margin
    row_h = 0.0
    for mod in mods:
        w = float(math.ceil(float(getattr(mod, "width", 10) or 10)))
        h = float(math.ceil(float(getattr(mod, "height", 10) or 10)))
        if x + w > bw - margin and x > margin:
            x = margin
            y += row_h + 2.0
            row_h = 0.0
        if y + h > bh - margin:
            # Overflow: still place; fit gate / repair may enlarge
            pass
        mod.placed_x = int(x)
        mod.placed_y = int(y)
        x += w + 2.0
        row_h = max(row_h, h)
    apply_satellite_offsets_after_z3(board)
    logger.warning(
        "Z3 fallback grid placement for %s module(s) (board %.0fx%.0f).",
        len(mods),
        bw,
        bh,
    )
