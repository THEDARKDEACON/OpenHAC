"""Footprint-centric PCB placement (constructive packer).

Schematic ``Module`` groups are clustering *hints*, not reserved empty rooms.
The previous path (inflate each module AABB, autosize a slack outline, Z3-SAT)
scatters parts because SAT is happy anywhere inside the outline and Optimize
times out. This engine:

1. Shelf-packs parts using each footprint's real (w, h) — largest first, so
   ICs sit at the cluster origin and passives land beside them.
2. Floorplans modules from the **signal net graph** (shared nets = edges).
   Power/ground are ignored so everything does not collapse onto 3V3.
   Connected modules sit on adjacent sides; disconnected components pack
   separately. No bus-name rooms and no part-specific layout.
3. Enforces ``distance_min`` by pushing pairs apart, then shrink-wraps the
   outline to the packed AABB.

Z3 remains available via ``OPENHAC_PLACEMENT_ENGINE=z3``.
``OPENHAC_PLACEMENT_PACK=shelf`` packs the same connectivity order in a grid
(debug); default is the graph packer.
"""

from __future__ import annotations

import logging
import math
import os
import re
from typing import Any, Hashable, Iterable

logger = logging.getLogger("openhac.placement")

_POWER_NET_RE = re.compile(
    r"^(gnd|dgnd|agnd|pgnd|vss|vdd|vcc|vbat|vbus|vin|3v3|5v|1v8|1v2|nc)(_|$)|"
    r"^(gnd|vss|vdd|vcc|vbus|vin|3v3|5v)\d|"
    r"^(vin_|vbus_|3v3_|5v_|vcc_|vdd_)",
    re.IGNORECASE,
)


def affinity_engine_enabled() -> bool:
    raw = (os.environ.get("OPENHAC_PLACEMENT_ENGINE") or "affinity").strip().lower()
    if raw in ("z3", "smt", "0", "off", "false", "no"):
        return False
    return True


def _env_float(name: str, default: float) -> float:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return float(default)
    try:
        return float(raw)
    except Exception:
        return float(default)


def is_power_or_nc_net(name: str) -> bool:
    n = str(name or "").strip()
    if not n:
        return True
    if n.upper() in ("NC", "UNCONNECTED") or n.startswith("__NOCONNECT"):
        return True
    return bool(_POWER_NET_RE.match(n))


def shelf_pack(
    items: Iterable[tuple[Hashable, float, float]],
    *,
    gap: float,
    cols: int | None = None,
    largest_first: bool = True,
) -> tuple[dict[Hashable, tuple[float, float]], float, float]:
    """Pack ``(key, w, h)`` into a sqrt-column shelf using each item's real size.

    Unlike ``cols * max_w`` grids, a 7 mm IC next to 0603s does not reserve a
    7 mm cell for every passive.
    """
    seq = [(k, float(w or 0.0), float(h or 0.0)) for k, w, h in items]
    seq = [(k, w, h) for k, w, h in seq if w > 0 and h > 0]
    if not seq:
        return {}, 0.0, 0.0
    if largest_first:
        seq = sorted(seq, key=lambda t: (-(t[1] * t[2]), str(t[0])))
    n = len(seq)
    if cols is None or cols <= 0:
        cols = max(1, int(math.ceil(math.sqrt(n))))
    cols = max(1, min(int(cols), n))
    gap = max(0.0, float(gap))
    x = y = 0.0
    col = 0
    row_h = 0.0
    max_r = max_b = 0.0
    pos: dict[Hashable, tuple[float, float]] = {}
    for key, w, h in seq:
        pos[key] = (x, y)
        max_r = max(max_r, x + w)
        max_b = max(max_b, y + h)
        row_h = max(row_h, h)
        col += 1
        x += w + gap
        if col >= cols:
            col = 0
            x = 0.0
            y += row_h + gap
            row_h = 0.0
    return pos, max_r, max_b


def _module_list(board) -> list[Any]:
    try:
        from openhac.compiler.cluster_affinity import z3_modules

        mods = list(z3_modules(board))
        if mods:
            return mods
    except Exception:
        pass
    try:
        return list(getattr(board, "_get_all_modules", lambda: [])() or [])
    except Exception:
        return list(getattr(board, "modules", []) or [])


def _iter_leaf_parts(mod) -> list[Any]:
    from openhac.core.module import Module

    parts: list[Any] = []
    for child in getattr(mod, "components", []) or []:
        if isinstance(child, Module):
            continue
        part = getattr(child, "part", None)
        if part is None and (hasattr(child, "pins") or hasattr(child, "get_pins")):
            part = child
        if part is not None:
            parts.append(part)
    return parts


def _pins_of_part(part) -> list[Any]:
    raw = getattr(part, "pins", None)
    if isinstance(raw, dict):
        return [p for p in raw.values() if not isinstance(p, (str, bytes))]
    if raw is not None:
        try:
            seq = list(raw)
        except TypeError:
            seq = []
        if seq and not isinstance(seq[0], (str, bytes, int)):
            return seq
    if hasattr(part, "get_pins"):
        try:
            return list(part.get_pins())
        except Exception:
            pass
    return []


def _net_name_of_pin(pin) -> str:
    net = getattr(pin, "net", None)
    n = str(getattr(net, "name", "") or "")
    if n:
        return n
    nets = getattr(pin, "nets", None)
    if not nets:
        return ""
    try:
        first = next(iter(nets))
    except Exception:
        return ""
    return str(getattr(first, "name", "") or "")


def module_signal_nets(mod) -> set[str]:
    names: set[str] = set()
    for part in _iter_leaf_parts(mod):
        for pin in _pins_of_part(part):
            n = _net_name_of_pin(pin)
            if n and not is_power_or_nc_net(n):
                names.add(n)
    return names


def shared_signal_count(a, b, netsets: dict[int, set[str]]) -> int:
    """How many signal nets two modules share (0 if either is missing)."""
    return len(netsets.get(id(a), set()) & netsets.get(id(b), set()))


def _area(mod) -> float:
    return float(getattr(mod, "width", 0) or 0) * float(getattr(mod, "height", 0) or 0)


def weighted_degree(mod, mods: list[Any], netsets: dict[int, set[str]]) -> int:
    return sum(shared_signal_count(mod, o, netsets) for o in mods if o is not mod)


def affinity_order(mods: list[Any], netsets: dict[int, set[str]]) -> list[Any]:
    """Largest module first, then greedy by shared signal nets with already placed."""
    remaining = list(mods)
    if not remaining:
        return []
    remaining.sort(key=lambda m: (-_area(m), str(getattr(m, "name", ""))))
    order = [remaining.pop(0)]
    while remaining:

        def score(m) -> tuple[int, float, str]:
            shared = 0
            for p in order:
                shared = max(shared, shared_signal_count(m, p, netsets))
            return (shared, _area(m), str(getattr(m, "name", "")))

        remaining.sort(key=lambda m: (-score(m)[0], -score(m)[1], score(m)[2]))
        order.append(remaining.pop(0))
    return order


def connectivity_order(mods: list[Any], netsets: dict[int, set[str]]) -> list[Any]:
    """Highest signal-graph degree first, then greedy by total weight into the placed set."""
    remaining = list(mods)
    if not remaining:
        return []
    remaining.sort(
        key=lambda m: (
            -weighted_degree(m, mods, netsets),
            -_area(m),
            str(getattr(m, "name", "")),
        )
    )
    order = [remaining.pop(0)]
    while remaining:

        def score(m) -> tuple[int, int, float, str]:
            total = sum(shared_signal_count(m, p, netsets) for p in order)
            strongest = max((shared_signal_count(m, p, netsets) for p in order), default=0)
            return (total, strongest, _area(m), str(getattr(m, "name", "")))

        remaining.sort(key=lambda m: (-score(m)[0], -score(m)[1], -score(m)[2], score(m)[3]))
        order.append(remaining.pop(0))
    return order


def connected_components(mods: list[Any], netsets: dict[int, set[str]]) -> list[list[Any]]:
    """Union-find on modules that share at least one signal net."""
    if not mods:
        return []
    parent = {id(m): id(m) for m in mods}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for i, a in enumerate(mods):
        for b in mods[i + 1 :]:
            if shared_signal_count(a, b, netsets) > 0:
                union(id(a), id(b))
    groups: dict[int, list[Any]] = {}
    for m in mods:
        groups.setdefault(find(id(m)), []).append(m)
    ranked = sorted(
        groups.values(),
        key=lambda g: (-sum(_area(m) for m in g), str(getattr(g[0], "name", ""))),
    )
    return ranked


def _pack_enabled() -> str:
    raw = (os.environ.get("OPENHAC_PLACEMENT_PACK") or "graph").strip().lower()
    if raw in ("shelf", "row", "old"):
        return "shelf"
    return "graph"


def _clearance_mm(board) -> float:
    try:
        g = float(getattr(board, "module_clearance_mm", 0.0) or 0.0)
    except Exception:
        g = 0.0
    if g <= 0:
        g = _env_float("OPENHAC_MODULE_CLEARANCE_MM", 3.0)
    return max(0.5, g)


def _edge_margin_mm() -> float:
    return max(1.0, _env_float("OPENHAC_AUTO_BOARD_MIN_EDGE_MARGIN_MM", 4.0))


def _aabb(mod) -> tuple[float, float, float, float]:
    x = float(getattr(mod, "placed_x", 0) or 0)
    y = float(getattr(mod, "placed_y", 0) or 0)
    w = float(getattr(mod, "width", 0) or 0)
    h = float(getattr(mod, "height", 0) or 0)
    return x, y, w, h


def _edge_gap(a, b) -> float:
    ax, ay, aw, ah = _aabb(a)
    bx, by, bw, bh = _aabb(b)
    dx = max(0.0, max(ax - (bx + bw), bx - (ax + aw)))
    dy = max(0.0, max(ay - (by + bh), by - (ay + ah)))
    if dx > 0 and dy > 0:
        return dx + dy
    return max(dx, dy) if (dx > 0 or dy > 0) else -min(
        (ax + aw) - bx, (bx + bw) - ax, (ay + ah) - by, (by + bh) - ay
    )


def _push_apart(a, b, min_gap: float) -> bool:
    """Move the module further from origin so edge gap is at least *min_gap*."""
    ax, ay, aw, ah = _aabb(a)
    bx, by, bw, bh = _aabb(b)
    gap = _edge_gap(a, b)
    if gap + 1e-9 >= min_gap:
        return False
    a_score = ax + ay
    b_score = bx + by
    mover, stay = (b, a) if b_score >= a_score else (a, b)
    sx, sy, sw, sh = _aabb(stay)
    mx, my, mw, mh = _aabb(mover)
    prefer_x = abs((sx + sw / 2) - (mx + mw / 2)) >= abs((sy + sh / 2) - (my + mh / 2))
    if prefer_x:
        if mx >= sx:
            mover.placed_x = sx + sw + min_gap
        else:
            nx = sx - mw - min_gap
            mover.placed_x = nx if nx >= 0 else sx + sw + min_gap
    else:
        if my >= sy:
            mover.placed_y = sy + sh + min_gap
        else:
            ny = sy - mh - min_gap
            mover.placed_y = ny if ny >= 0 else sy + sh + min_gap
    return True


def _distance_min_rules(board, mods: list[Any]) -> list[tuple[Any, Any, float]]:
    zids = {id(m) for m in mods}
    out: list[tuple[Any, Any, float]] = []
    for rule in getattr(board, "constraints", None) or []:
        if rule.get("type") != "distance_min":
            continue
        args = rule.get("args") or ()
        if len(args) < 3:
            continue
        a, b, g = args[0], args[1], args[2]
        if id(a) not in zids or id(b) not in zids:
            continue
        try:
            out.append((a, b, float(g)))
        except Exception:
            continue
    return out


def _deoverlap_modules(mods: list[Any], gap: float, rounds: int = 24) -> None:
    for _ in range(rounds):
        moved = False
        for i, a in enumerate(mods):
            for b in mods[i + 1 :]:
                if _edge_gap(a, b) + 1e-9 >= gap:
                    continue
                moved = _push_apart(a, b, gap) or moved
        if not moved:
            return


def _wh(mod) -> tuple[float, float]:
    return (
        float(getattr(mod, "width", 10) or 10),
        float(getattr(mod, "height", 10) or 10),
    )


def _aabb_collides(
    x: float, y: float, w: float, h: float, boxes: list[tuple[float, float, float, float]], gap: float
) -> bool:
    g = max(0.0, float(gap))
    for px, py, pw, ph in boxes:
        if x < px + pw + g and x + w + g > px and y < py + ph + g and y + h + g > py:
            return True
    return False


def _translate_origin(pos: dict[int, tuple[float, float]]) -> dict[int, tuple[float, float]]:
    if not pos:
        return pos
    min_x = min(x for x, _y in pos.values())
    min_y = min(y for _x, y in pos.values())
    return {k: (x - min_x, y - min_y) for k, (x, y) in pos.items()}


def _component_pack(
    mods: list[Any],
    netsets: dict[int, set[str]],
    *,
    gap: float,
) -> tuple[dict[int, tuple[float, float]], list[Any]]:
    """Place one connected component: hub at origin, neighbors on free sides."""
    order = connectivity_order(mods, netsets)
    if not order:
        return {}, []
    pos: dict[int, tuple[float, float]] = {id(order[0]): (0.0, 0.0)}
    by_id = {id(m): m for m in order}

    def boxes_except(mid: int) -> list[tuple[float, float, float, float]]:
        out: list[tuple[float, float, float, float]] = []
        for k, (x, y) in pos.items():
            if k == mid:
                continue
            m = by_id[k]
            mw, mh = _wh(m)
            out.append((x, y, mw, mh))
        return out

    def manhattan_wire(x: float, y: float, w: float, h: float, mod) -> float:
        cx, cy = x + w / 2.0, y + h / 2.0
        cost = 0.0
        for p in order:
            if p is mod or id(p) not in pos:
                continue
            wgt = shared_signal_count(mod, p, netsets)
            if wgt <= 0:
                continue
            px, py = pos[id(p)]
            pw, ph = _wh(p)
            cost += wgt * (abs(cx - (px + pw / 2.0)) + abs(cy - (py + ph / 2.0)))
        return cost

    for mod in order[1:]:
        w, h = _wh(mod)
        neighbors = sorted(
            (p for p in order if id(p) in pos and shared_signal_count(mod, p, netsets) > 0),
            key=lambda p: (-shared_signal_count(mod, p, netsets), str(getattr(p, "name", ""))),
        )
        occupied: set[int] = set()
        if neighbors:
            nx, ny = pos[id(neighbors[0])]
            nw, nh = _wh(neighbors[0])
            probes = [
                (nx + nw + gap, ny),
                (nx, ny + nh + gap),
                (nx - w - gap, ny),
                (nx, ny - h - gap),
            ]
            for i, (sx, sy) in enumerate(probes):
                if _aabb_collides(sx, sy, w, h, boxes_except(id(mod)), gap):
                    occupied.add(i)
        opposite = {0: 2, 1: 3, 2: 0, 3: 1}
        candidates: list[tuple[float, float]] = []
        if neighbors:
            for n in neighbors:
                nx, ny = pos[id(n)]
                nw, nh = _wh(n)
                step = min(w, h) + gap
                for ring in range(6):
                    extra = ring * step
                    candidates.extend(
                        [
                            (nx + nw + gap + extra, ny),
                            (nx, ny + nh + gap + extra),
                            (nx - w - gap - extra, ny),
                            (nx, ny - h - gap - extra),
                        ]
                    )
        else:
            max_r = max((x + _wh(by_id[k])[0] for k, (x, _y) in pos.items()), default=0.0)
            candidates.append((max_r + gap, 0.0))

        best: tuple[float, float] | None = None
        best_key: tuple[float, int, int] | None = None
        existing = boxes_except(id(mod))
        for i, (sx, sy) in enumerate(candidates):
            if _aabb_collides(sx, sy, w, h, existing, gap):
                continue
            side = i % 4
            spread = 0 if opposite[side] in occupied else 1
            key = (manhattan_wire(sx, sy, w, h, mod), spread, i)
            if best_key is None or key < best_key:
                best_key = key
                best = (sx, sy)
        if best is None:
            max_r = max((x + _wh(by_id[k])[0] for k, (x, _y) in pos.items()), default=0.0)
            best = (max_r + gap, 0.0)
        pos[id(mod)] = best

    return _translate_origin(pos), order


def graph_pack_positions(
    mods: list[Any],
    netsets: dict[int, set[str]],
    *,
    gap: float,
) -> tuple[dict[int, tuple[float, float]], list[Any]]:
    """Pack modules from the signal-net graph.

    Each connected component is packed around its highest-degree module.
    Components (including isolates) are then shelf-packed so disconnected
    islands do not interleave. Returns (id→(x, y), placement order).
    """
    if not mods:
        return {}, []
    comps = connected_components(mods, netsets)
    local: list[tuple[int, dict[int, tuple[float, float]], list[Any], float, float]] = []
    for i, group in enumerate(comps):
        loc, order = _component_pack(group, netsets, gap=gap)
        if not loc:
            continue
        by_id = {id(m): m for m in group}
        max_r = max(x + _wh(by_id[k])[0] for k, (x, _y) in loc.items())
        max_b = max(y + _wh(by_id[k])[1] for k, (_x, y) in loc.items())
        local.append((i, loc, order, max_r, max_b))
    if not local:
        return {}, []
    if len(local) == 1:
        _i, loc, order, _rw, _rh = local[0]
        return loc, order
    items = [(i, rw, rh) for i, _loc, _order, rw, rh in local]
    comp_xy, _bw, _bh = shelf_pack(items, gap=gap, cols=2, largest_first=False)
    out: dict[int, tuple[float, float]] = {}
    order: list[Any] = []
    for i, loc, grp_order, _rw, _rh in local:
        ox, oy = comp_xy.get(i, (0.0, 0.0))
        for mid, (x, y) in loc.items():
            out[mid] = (ox + x, oy + y)
        order.extend(grp_order)
    return out, order


def apply_affinity_floorplan(board) -> bool:
    """Place Z3-participant modules from the signal net graph (or a debug shelf)."""
    mods = [m for m in _module_list(board) if m is not None]
    if not mods:
        return False
    gap = _clearance_mm(board)
    netsets = {id(m): module_signal_nets(m) for m in mods}
    if _pack_enabled() == "shelf":
        order = connectivity_order(mods, netsets)
        items = [(id(m), *_wh(m)) for m in order]
        pos, pack_w, pack_h = shelf_pack(items, gap=gap, largest_first=False)
        if pack_w <= 0 or pack_h <= 0 or not pos:
            return False
    else:
        pos, order = graph_pack_positions(mods, netsets, gap=gap)
        if not pos:
            return False
    margin = _edge_margin_mm()
    by_id = {id(m): m for m in order}
    for key, (x, y) in pos.items():
        m = by_id.get(key)
        if m is None:
            continue
        m.placed_x = float(x) + margin
        m.placed_y = float(y) + margin

    for a, b, g in _distance_min_rules(board, mods):
        _push_apart(a, b, max(g, gap))
    _deoverlap_modules(mods, gap, rounds=80)

    max_r = max(float(m.placed_x) + float(m.width) for m in mods)
    max_b = max(float(m.placed_y) + float(m.height) for m in mods)
    w = float(math.ceil(max_r + margin))
    h = float(math.ceil(max_b + margin))
    old = getattr(board, "size_mm", (w, h))
    try:
        ow, oh = float(old[0]), float(old[1])
    except Exception:
        ow, oh = w, h
    board.size_mm = (w, h)
    mode = _pack_enabled()
    logger.info(
        "Affinity floorplan (%s): %s modules, pack %.0fx%.0f mm (was %.0fx%.0f), gap %.1f mm.",
        mode,
        len(mods),
        w,
        h,
        ow,
        oh,
        gap,
    )
    for m in order:
        deg = weighted_degree(m, mods, netsets)
        logger.info(
            "  - %s: (%.1f, %.1f) [w:%.1f, h:%.1f] degree=%s nets=%s",
            getattr(m, "name", "?"),
            float(m.placed_x),
            float(m.placed_y),
            float(m.width),
            float(m.height),
            deg,
            ",".join(sorted(netsets.get(id(m), set()))[:8]) or "-",
        )
    return True
