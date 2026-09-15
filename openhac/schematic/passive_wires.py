"""SSO-023 — local wires for nearby passives (schematic emit only).

Extends SSO-022: keep labels on IC / long nets; draw short orthogonal wires
from 2-pin passives to a nearby mate so fewer orphan stub+label islands.
"""

from __future__ import annotations

import os
from typing import Any

from openhac.schematic.ir import NetLabel, SchematicIR, WireSeg
from openhac.schematic.resolve import looks_like_device_passive
from openhac.schematic.util import (
    is_gnd_net_name,
    iter_pins,
    net_name,
    net_openhac_type,
    part_ref,
    pin_num,
    sheet_field,
    snap,
    sorted_net_pins,
)

# IC / connector-class refs — even if the graph uses Device:R as a stand-in body.
_ANCHOR_REF_PREFIXES = frozenset(
    {"U", "IC", "J", "P", "CN", "X", "SW", "Q", "T", "Y", "FB", "VR"}
)


def passive_wires_enabled() -> bool:
    raw = (os.environ.get("OPENHAC_SCHEMATIC_PASSIVE_WIRES") or "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def _max_local_mm() -> float:
    try:
        return float(os.environ.get("OPENHAC_SCHEMATIC_PASSIVE_WIRE_MM") or "45.72")
    except ValueError:
        return 45.72


def _ref_alpha_prefix(part) -> str:
    ref = part_ref(part).upper()
    return "".join(c for c in ref if c.isalpha())


def _is_passive_part(part) -> bool:
    if _ref_alpha_prefix(part) in _ANCHOR_REF_PREFIXES:
        return False
    if not looks_like_device_passive(part):
        return False
    return len(iter_pins(part)) <= 4


def _is_anchor_part(part) -> bool:
    """IC / connector-class: prefer as the label-bearing end of a local wire."""
    if _ref_alpha_prefix(part) in _ANCHOR_REF_PREFIXES:
        return True
    if _is_passive_part(part):
        return False
    return len(iter_pins(part)) >= 3 or not looks_like_device_passive(part)


def _dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def _on_segment(px: float, py: float, ax: float, ay: float, bx: float, by: float, eps: float = 0.2) -> bool:
    if abs(px - ax) < eps and abs(py - ay) < eps:
        return False
    if abs(px - bx) < eps and abs(py - by) < eps:
        return False
    if abs(ax - bx) < eps:
        if abs(px - ax) > eps:
            return False
        return min(ay, by) - eps <= py <= max(ay, by) + eps
    if abs(ay - by) < eps:
        if abs(py - ay) > eps:
            return False
        return min(ax, bx) - eps <= px <= max(ax, bx) + eps
    return False


def _through_hits(ir: SchematicIR, ax: float, ay: float, bx: float, by: float) -> bool:
    for xy in ir.pin_xy.values():
        if _on_segment(xy[0], xy[1], ax, ay, bx, by):
            return True
    return False


def _add_ortho_wire(
    ir: SchematicIR,
    ax: float,
    ay: float,
    bx: float,
    by: float,
    *,
    sheet: str,
    net: str,
) -> bool:
    """One segment if aligned; else L-bend (or jogged L if a through-pin blocks)."""
    ax, ay, bx, by = snap(ax), snap(ay), snap(bx), snap(by)
    if abs(ax - bx) < 0.01 and abs(ay - by) < 0.01:
        return False

    def _try_path(*pts: tuple[float, float]) -> bool:
        for i in range(len(pts) - 1):
            x1, y1 = pts[i]
            x2, y2 = pts[i + 1]
            if abs(x1 - x2) < 0.01 and abs(y1 - y2) < 0.01:
                continue
            if _through_hits(ir, x1, y1, x2, y2):
                return False
        for i in range(len(pts) - 1):
            x1, y1 = pts[i]
            x2, y2 = pts[i + 1]
            if abs(x1 - x2) < 0.01 and abs(y1 - y2) < 0.01:
                continue
            ir.wires.append(WireSeg(x1, y1, x2, y2, sheet=sheet, net=net))
        return True

    # Direct axis-aligned when clear.
    if abs(ax - bx) < 0.01 or abs(ay - by) < 0.01:
        if _try_path((ax, ay), (bx, by)):
            return True

    # Standard L-bends.
    for mx, my in ((bx, ay), (ax, by)):
        if _try_path((ax, ay), (mx, my), (bx, by)):
            return True

    # Jog around stacked pins on the same column/row (affinity often packs this way).
    jog = 2.54
    for j in (jog, -jog, 2 * jog, -2 * jog):
        if abs(ax - bx) < 0.01:
            # Vertical intent → dogleg via x±jog.
            mid_x = snap(ax + j)
            if _try_path((ax, ay), (mid_x, ay), (mid_x, by), (bx, by)):
                return True
        elif abs(ay - by) < 0.01:
            mid_y = snap(ay + j)
            if _try_path((ax, ay), (ax, mid_y), (bx, mid_y), (bx, by)):
                return True
        else:
            mid_x = snap(ax + j)
            if _try_path((ax, ay), (mid_x, ay), (mid_x, by), (bx, by)):
                return True
            mid_y = snap(ay + j)
            if _try_path((ax, ay), (ax, mid_y), (bx, mid_y), (bx, by)):
                return True
    return False


def _remove_stub_label_at(
    ir: SchematicIR,
    *,
    ref: str,
    net: str,
    wx: float,
    wy: float,
    eps: float = 3.0,
) -> None:
    """Drop local label (+ short stub wire) owned by ref near this pin for ``net``."""
    keep_labels: list[NetLabel] = []
    removed_pts: list[tuple[float, float]] = []
    for lb in ir.labels:
        if lb.name != net or lb.kind not in ("local", ""):
            keep_labels.append(lb)
            continue
        owner = str(getattr(lb, "owner_ref", "") or "")
        near = abs(lb.x - wx) <= eps and abs(lb.y - wy) <= eps
        if owner == ref or near:
            removed_pts.append((lb.x, lb.y))
            continue
        keep_labels.append(lb)
    ir.labels = keep_labels

    keep_wires: list[WireSeg] = []
    for w in ir.wires:
        if w.net != net:
            keep_wires.append(w)
            continue
        # Drop short stubs from pin toward a removed label.
        ends = ((w.x1, w.y1), (w.x2, w.y2))
        touches_pin = any(abs(ex - wx) < 0.05 and abs(ey - wy) < 0.05 for ex, ey in ends)
        touches_lbl = any(
            abs(ex - lx) < 0.05 and abs(ey - ly) < 0.05
            for ex, ey in ends
            for lx, ly in removed_pts
        )
        length = abs(w.x1 - w.x2) + abs(w.y1 - w.y2)
        if touches_pin and (touches_lbl or length <= eps + 0.1):
            continue
        keep_wires.append(w)
    ir.wires = keep_wires


def _best_mate(
    pin,
    xy: tuple[float, float],
    candidates: list[tuple[Any, tuple[float, float]]],
    *,
    max_mm: float,
) -> tuple[Any, tuple[float, float]] | None:
    best = None
    best_d = max_mm
    pref_sheet = sheet_field(pin.part)
    for other, oxy in candidates:
        if other is pin or other.part is pin.part:
            continue
        if sheet_field(other.part) != pref_sheet:
            continue
        d = _dist(xy, oxy)
        if d < best_d and d > 0.05:
            best_d = d
            best = (other, oxy)
    return best


def _pins_already_wired(
    ir: SchematicIR,
    nn: str,
    a: tuple[float, float],
    b: tuple[float, float],
) -> bool:
    """True if same-net wire segments already form a path between the two pins."""
    adj: dict[tuple[float, float], set[tuple[float, float]]] = {}
    for w in ir.wires:
        if w.net != nn:
            continue
        p1 = (snap(w.x1), snap(w.y1))
        p2 = (snap(w.x2), snap(w.y2))
        adj.setdefault(p1, set()).add(p2)
        adj.setdefault(p2, set()).add(p1)
    start = (snap(a[0]), snap(a[1]))
    goal = (snap(b[0]), snap(b[1]))
    if start not in adj or goal not in adj:
        return False
    seen = {start}
    stack = [start]
    while stack:
        cur = stack.pop()
        if cur == goal:
            return True
        for nxt in adj.get(cur, ()):
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return False


def apply_passive_local_wires(ir: SchematicIR, nets: list) -> int:
    """Wire nearby passives to an IC/anchor on the same signal net. Returns wire count added."""
    if not passive_wires_enabled():
        return 0
    max_mm = _max_local_mm()
    added = 0
    for net in nets:
        nn = net_name(net)
        ntype = net_openhac_type(net)
        if not nn or ntype in ("power", "gnd") or is_gnd_net_name(nn):
            continue
        pins = [
            p
            for p in sorted_net_pins(net)
            if ir.pin_xy.get((part_ref(p.part), pin_num(p)))
        ]
        if len(pins) < 2:
            continue

        anchors = []
        passives = []
        for p in pins:
            xy = ir.pin_xy[(part_ref(p.part), pin_num(p))]
            if _is_anchor_part(p.part):
                anchors.append((p, xy))
            elif _is_passive_part(p.part):
                passives.append((p, xy))

        if not passives:
            continue
        # Need an IC/anchor to hang onto (fanout≥3 all-R stays SSO-022 labels).
        # Exception: fanout-2 series passives may wire to each other.
        if anchors:
            mate_pool = anchors
        elif len(pins) == 2 and len(passives) == 2:
            mate_pool = passives
        else:
            continue
        two_pin = len(pins) == 2

        for p, xy in passives:
            mate = _best_mate(p, xy, mate_pool, max_mm=max_mm)
            if mate is None:
                continue
            q, qxy = mate
            if _pins_already_wired(ir, nn, xy, qxy):
                continue
            sh = sheet_field(p.part)
            if not _add_ortho_wire(ir, xy[0], xy[1], qxy[0], qxy[1], sheet=sh, net=nn):
                continue
            _remove_stub_label_at(ir, ref=part_ref(p.part), net=nn, wx=xy[0], wy=xy[1])
            # Fanout-2: wire alone is enough — drop mate stub/label too.
            # Fanout≥3: keep IC labels (SSO-022); only clear other passives.
            if two_pin or _is_passive_part(q.part):
                _remove_stub_label_at(ir, ref=part_ref(q.part), net=nn, wx=qxy[0], wy=qxy[1])
            added += 1
    return added


def apply_decoupling_wires(ir: SchematicIR, nets: list, parts: list) -> int:
    """Wire nearby decoupling C (rail↔GND) toward an IC that shares both nets."""
    if not passive_wires_enabled():
        return 0
    max_mm = _max_local_mm()
    net_by_name: dict[str, Any] = {}
    for net in nets:
        nn = net_name(net)
        if nn:
            net_by_name[nn] = net

    added = 0
    for part in parts:
        if not _is_passive_part(part):
            continue
        pins = list(iter_pins(part))
        if len(pins) != 2:
            continue
        n0 = getattr(pins[0], "net", None)
        n1 = getattr(pins[1], "net", None)
        if n0 is None or n1 is None:
            continue
        nn0, nn1 = net_name(n0), net_name(n1)
        t0, t1 = net_openhac_type(n0), net_openhac_type(n1)
        g0, g1 = is_gnd_net_name(nn0), is_gnd_net_name(nn1)
        powerish0 = t0 in ("power", "gnd") or g0
        powerish1 = t1 in ("power", "gnd") or g1
        if not (powerish0 and powerish1):
            continue
        if g0 == g1:
            continue  # need one rail + one gnd
        rail_pin, gnd_pin = (pins[0], pins[1]) if not g0 else (pins[1], pins[0])
        rail_nn, gnd_nn = net_name(rail_pin.net), net_name(gnd_pin.net)
        rxy = ir.pin_xy.get((part_ref(part), pin_num(rail_pin)))
        gxy = ir.pin_xy.get((part_ref(part), pin_num(gnd_pin)))
        if not rxy or not gxy:
            continue

        rail_net = net_by_name.get(rail_nn)
        gnd_net = net_by_name.get(gnd_nn)
        if rail_net is None or gnd_net is None:
            continue
        ic_rail = None
        ic_gnd = None
        best = max_mm
        for rp in sorted_net_pins(rail_net):
            if rp.part is part or _is_passive_part(rp.part):
                continue
            if not _is_anchor_part(rp.part):
                continue
            if sheet_field(rp.part) != sheet_field(part):
                continue
            rxy_ic = ir.pin_xy.get((part_ref(rp.part), pin_num(rp)))
            if not rxy_ic:
                continue
            g_pin = None
            gxy_ic = None
            for gp in sorted_net_pins(gnd_net):
                if gp.part is rp.part:
                    gxy_ic = ir.pin_xy.get((part_ref(gp.part), pin_num(gp)))
                    if gxy_ic:
                        g_pin = gp
                        break
            if g_pin is None or gxy_ic is None:
                continue
            d = _dist(rxy, rxy_ic)
            if d < best:
                best = d
                ic_rail, ic_gnd = (rp, rxy_ic), (g_pin, gxy_ic)

        if ic_rail is None or ic_gnd is None:
            continue
        sh = sheet_field(part)
        ok_r = False
        ok_g = False
        if not _pins_already_wired(ir, rail_nn, rxy, ic_rail[1]):
            ok_r = _add_ortho_wire(
                ir, rxy[0], rxy[1], ic_rail[1][0], ic_rail[1][1], sheet=sh, net=rail_nn
            )
        if not _pins_already_wired(ir, gnd_nn, gxy, ic_gnd[1]):
            ok_g = _add_ortho_wire(
                ir, gxy[0], gxy[1], ic_gnd[1][0], ic_gnd[1][1], sheet=sh, net=gnd_nn
            )
        if ok_r or ok_g:
            added += int(ok_r) + int(ok_g)
    return added
