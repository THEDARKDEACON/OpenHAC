"""Schematic symbol XY placers (SSO-032…036).

Placement only — SSO-022 connectivity is unchanged. Native affinity packing
(inspired by SKiDL); no SKiDL runtime dependency.
"""

from __future__ import annotations

import math
import os
from typing import Any

from openhac.schematic.util import (
    is_gnd_net_name,
    iter_pins,
    module_field,
    net_name,
    net_openhac_type,
    part_ref,
    part_rotation_deg,
    pin_num,
    snap,
)

# Keep in sync with layout.py column constants (SSO-035 escape).
_COL_PITCH_MM = 152.4
_PART_GAP_MM = 20.32
_MOD_GAP_MM = 38.1
_CELL_H_PAD_MM = 20.32
_MARGIN_MM = 25.4
_GRID_MM = 1.27


def schematic_place_mode() -> str:
    """``affinity`` (default) or ``columns`` (legacy escape, SSO-035)."""
    raw = (os.environ.get("OPENHAC_SCHEMATIC_PLACE") or "affinity").strip().lower()
    if raw in ("columns", "column", "legacy"):
        return "columns"
    return "affinity"


def _flow_from_tag(tag: str) -> int | None:
    t = str(tag or "").strip().lower()
    if t in ("0", "power", "pwr", "left"):
        return 0
    if t in ("2", "io", "right"):
        return 2
    if t in ("1", "compute", "mid", "middle"):
        return 1
    return None


def _flow_column(mod_name: str, board) -> int:
    """0=power/left, 1=compute/mid, 2=IO/right — from module tags / interface kinds."""
    if board is not None:
        for m in getattr(board, "modules", []) or []:
            if str(getattr(m, "name", "")) != mod_name:
                continue
            tagged = _flow_from_tag(getattr(m, "schematic_flow", None) or "")
            if tagged is not None:
                return tagged
            kinds = []
            for d in (
                getattr(m, "required_interfaces", {}) or {},
                getattr(m, "optional_interfaces", {}) or {},
            ):
                for iface in d.values():
                    kinds.append(
                        str(getattr(iface, "kind", "") or getattr(iface, "name", "") or "").lower()
                    )
            blob = " ".join(kinds)
            left = any(t in blob for t in ("pwr", "power", "supply", "vin", "vbat"))
            right = any(t in blob for t in ("uart", "spi", "i2c", "can", "usb", "gpio", "io"))
            if left and not right:
                return 0
            if right and not left:
                return 2
            break
    if os.environ.get("OPENHAC_SCHEMATIC_FLOW_NAME_TOKENS", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    ):
        blob = str(mod_name or "").lower()
        left = any(
            t in blob
            for t in (
                "pwr",
                "power",
                "vcc",
                "3v3",
                "gnd",
                "vbus",
                "vin",
                "ldo",
                "reg",
                "supply",
                "batt",
            )
        )
        right = any(
            t in blob
            for t in (
                "uart",
                "spi",
                "i2c",
                "can",
                "rs485",
                "usb",
                "gpio",
                "jtag",
                "header",
                "conn",
                "eth",
                "io",
            )
        )
        if left and not right:
            return 0
        if right and not left:
            return 2
    return 1


def _part_cell_size(part) -> tuple[float, float]:
    n_pins = max(len(iter_pins(part)), 2)
    h = min(150.0, max(25.4, (n_pins / 2) * 5.08 + _CELL_H_PAD_MM))
    w = min(80.0, max(20.32, 12.7 + (n_pins / 4) * 2.54))
    return w, h


def _apply_overlay(positions: dict, rotations: dict, parts, board, overlay) -> None:
    if overlay is None and board is not None:
        overlay = getattr(board, "_kicad_artwork_overlay", None)
    if overlay is not None:
        from openhac.compiler.kicad_artwork import apply_symbol_overlay

        apply_symbol_overlay(positions, rotations, parts, overlay)


def place_columns(parts, resolver, board=None, overlay=None) -> tuple[dict, dict]:
    """Legacy module-grouped left-to-right flow columns (SSO-035 escape)."""
    from openhac.schematic.resolve import pin_offset, schematic_symbol_lib_key
    from openhac.schematic.util import rotate_offset

    groups: dict[str, list] = {}
    for p in parts:
        groups.setdefault(module_field(p), []).append(p)
    names = sorted(groups.keys(), key=lambda s: (not s, s))
    cols: dict[int, list[str]] = {0: [], 1: [], 2: []}
    for m in names:
        cols[_flow_column(m, board)].append(m)
    positions: dict = {}
    rotations: dict = {}
    for col, mod_names in cols.items():
        cur_mod_y = _MARGIN_MM
        px_base = 40.64 + col * _COL_PITCH_MM
        for m in mod_names:
            m_parts = sorted(
                groups[m], key=lambda p: (str(part_ref(p)).upper(), getattr(p, "_part_id", 0))
            )
            cur_y = 0.0
            for p in m_parts:
                rot = part_rotation_deg(p)
                _w, cell_h = _part_cell_size(p)
                px, py = px_base, cur_mod_y + cur_y
                pins = iter_pins(p)
                if pins and resolver is not None:
                    dx, dy, _ = pin_offset(
                        resolver, p, pins[0], symbol_name=schematic_symbol_lib_key(p)
                    )
                    rdx, rdy = rotate_offset(dx, dy, rot)
                    px = snap(px + rdx) - rdx
                    py = snap(py - rdy) + rdy
                positions[p] = (px, py)
                rotations[p] = rot
                cur_y += cell_h + _PART_GAP_MM
            cur_mod_y += cur_y + _MOD_GAP_MM
    _apply_overlay(positions, rotations, parts, board, overlay)
    return positions, rotations


def _signal_edges(parts: list) -> list[tuple[Any, Any, float]]:
    """Undirected edges between parts that share a non-power signal net."""
    net_parts: dict[int, list] = {}
    for p in parts:
        for pin in iter_pins(p):
            net = getattr(pin, "net", None)
            if net is None:
                continue
            nn = net_name(net)
            if not nn or nn.startswith("__"):
                continue
            ntype = net_openhac_type(net)
            if ntype in ("power", "gnd") or is_gnd_net_name(nn):
                continue
            # High fanout rails named like 3V3 without type still collapse layout.
            try:
                from openhac.schematic.util import sorted_net_pins

                n_pins = len(sorted_net_pins(net))
            except Exception:
                n_pins = len(list(getattr(net, "pins", []) or []))
            if n_pins >= 8:
                continue
            net_parts.setdefault(id(net), []).append(p)
    edges: list[tuple[Any, Any, float]] = []
    seen: set[tuple[int, int]] = set()
    for members in net_parts.values():
        uniq = []
        seen_p: set[int] = set()
        for p in members:
            if id(p) in seen_p:
                continue
            seen_p.add(id(p))
            uniq.append(p)
        if len(uniq) < 2 or len(uniq) > 6:
            # Skip huge nets (would pull whole board together); SSO-022 labels them anyway.
            continue
        w = 1.0 / max(1, len(uniq) - 1)
        for i, a in enumerate(uniq):
            for b in uniq[i + 1 :]:
                key = (min(id(a), id(b)), max(id(a), id(b)))
                if key in seen:
                    continue
                seen.add(key)
                edges.append((a, b, w))
    return edges


def _shift_into_margin(positions: dict, sizes: dict[Any, tuple[float, float]]) -> None:
    """SSO-033: keep estimated body bboxes in the positive quadrant with margin."""
    if not positions:
        return
    min_x = min(positions[p][0] - sizes[p][0] * 0.5 for p in positions)
    min_y = min(positions[p][1] - sizes[p][1] * 0.5 for p in positions)
    dx = _MARGIN_MM - min_x
    dy = _MARGIN_MM - min_y
    if abs(dx) < 1e-9 and abs(dy) < 1e-9:
        return
    for p in list(positions.keys()):
        x, y = positions[p]
        positions[p] = (x + dx, y + dy)


def _clamp_to_iso_portrait(
    positions: dict, sizes: dict[Any, tuple[float, float]], paper_w: float = 210.0, paper_h: float = 297.0
) -> None:
    """Prefer fitting A4; if still overflowing, leave coords for larger ISO pick."""
    if not positions:
        return
    max_x = max(positions[p][0] + sizes[p][0] * 0.5 for p in positions) + _MARGIN_MM
    max_y = max(positions[p][1] + sizes[p][1] * 0.5 for p in positions) + _MARGIN_MM
    if max_x <= paper_w and max_y <= paper_h:
        return
    # Scale toward origin (margin) if modestly over A4.
    ox, oy = _MARGIN_MM, _MARGIN_MM
    sx = (paper_w - 2 * _MARGIN_MM) / max(max_x - ox, 1.0)
    sy = (paper_h - 2 * _MARGIN_MM) / max(max_y - oy, 1.0)
    s = min(1.0, sx, sy)
    if s >= 0.999:
        return
    if s < 0.55:
        # Too cramped — keep dense pack; _paper_for_ir will pick A3+.
        return
    for p in list(positions.keys()):
        x, y = positions[p]
        positions[p] = (ox + (x - ox) * s, oy + (y - oy) * s)


def place_affinity(parts, resolver, board=None, overlay=None) -> tuple[dict, dict]:
    """Connectivity-aware force / cluster placer (SSO-034). Deterministic."""
    del resolver  # pin snap alignment is optional; keep API parity with place_columns
    ordered = sorted(parts, key=lambda p: (str(part_ref(p)).upper(), getattr(p, "_part_id", 0)))
    if not ordered:
        return {}, {}

    sizes = {p: _part_cell_size(p) for p in ordered}
    rotations = {p: part_rotation_deg(p) for p in ordered}

    # Seed: compact module stacks (not wide columns) so affinity starts on-sheet.
    groups: dict[str, list] = {}
    for p in ordered:
        groups.setdefault(module_field(p), []).append(p)
    mod_names = sorted(groups.keys(), key=lambda s: (not s, s))
    positions: dict = {}
    # Tile modules in a roughly square packing of stacks.
    n_mod = max(1, len(mod_names))
    cols_m = max(1, int(math.ceil(math.sqrt(n_mod))))
    col_x = [_MARGIN_MM + c * 55.0 for c in range(cols_m)]
    col_y = [_MARGIN_MM] * cols_m
    for i, m in enumerate(mod_names):
        c = i % cols_m
        y = col_y[c]
        for p in sorted(groups[m], key=lambda q: (str(part_ref(q)).upper(), getattr(q, "_part_id", 0))):
            w, h = sizes[p]
            positions[p] = (col_x[c], y)
            y += h + _PART_GAP_MM * 0.55
        col_y[c] = y + _MOD_GAP_MM * 0.4

    edges = _signal_edges(ordered)
    # Module soft springs: pull members toward module centroid each iter.
    mod_of = {p: module_field(p) for p in ordered}

    n_iter = 80 if len(ordered) < 40 else 50
    for it in range(n_iter):
        alpha = 1.0 - (it / max(1, n_iter - 1)) * 0.85
        forces: dict[Any, list[float]] = {p: [0.0, 0.0] for p in ordered}

        for a, b, w in edges:
            ax, ay = positions[a]
            bx, by = positions[b]
            dx, dy = bx - ax, by - ay
            dist = math.hypot(dx, dy) or 0.01
            # Ideal length ~ half sum of sizes.
            ideal = 0.55 * (sizes[a][0] + sizes[b][0] + sizes[a][1] + sizes[b][1]) * 0.25
            ideal = max(18.0, ideal)
            pull = (dist - ideal) * 0.08 * w * alpha
            fx, fy = (dx / dist) * pull, (dy / dist) * pull
            forces[a][0] += fx
            forces[a][1] += fy
            forces[b][0] -= fx
            forces[b][1] -= fy

        # Module centroid attraction.
        centroids: dict[str, list[float]] = {}
        counts: dict[str, int] = {}
        for p in ordered:
            m = mod_of[p]
            x, y = positions[p]
            if m not in centroids:
                centroids[m] = [0.0, 0.0]
                counts[m] = 0
            centroids[m][0] += x
            centroids[m][1] += y
            counts[m] += 1
        for m, c in centroids.items():
            n = max(1, counts[m])
            c[0] /= n
            c[1] /= n
        for p in ordered:
            m = mod_of[p]
            cx, cy = centroids[m]
            x, y = positions[p]
            forces[p][0] += (cx - x) * 0.04 * alpha
            forces[p][1] += (cy - y) * 0.04 * alpha

        # Overlap repulsion (pairwise; OK for schematic-scale part counts).
        for i, a in enumerate(ordered):
            ax, ay = positions[a]
            aw, ah = sizes[a]
            for b in ordered[i + 1 :]:
                bx, by = positions[b]
                bw, bh = sizes[b]
                dx, dy = bx - ax, by - ay
                dist = math.hypot(dx, dy) or 0.01
                min_d = 0.55 * (max(aw, ah) + max(bw, bh))
                if dist < min_d:
                    push = (min_d - dist) * 0.35 * (1.0 + (1.0 - alpha))
                    fx, fy = (dx / dist) * push, (dy / dist) * push
                    forces[a][0] -= fx
                    forces[a][1] -= fy
                    forces[b][0] += fx
                    forces[b][1] += fy

        for p in ordered:
            x, y = positions[p]
            positions[p] = (x + forces[p][0], y + forces[p][1])

    for p in ordered:
        x, y = positions[p]
        positions[p] = (snap(x, _GRID_MM), snap(y, _GRID_MM))

    _shift_into_margin(positions, sizes)
    _clamp_to_iso_portrait(positions, sizes)
    for p in ordered:
        x, y = positions[p]
        positions[p] = (snap(x, _GRID_MM), snap(y, _GRID_MM))
    _shift_into_margin(positions, sizes)

    _apply_overlay(positions, rotations, parts, board, overlay)
    return positions, rotations


def assign_positions(parts, resolver, board=None, overlay=None) -> tuple[dict, dict]:
    """SSO-032 dispatcher: affinity (default) or columns escape."""
    if schematic_place_mode() == "columns":
        return place_columns(parts, resolver, board, overlay=overlay)
    return place_affinity(parts, resolver, board, overlay=overlay)


def instance_bboxes_outside_paper(
    positions: dict,
    sizes: dict[Any, tuple[float, float]] | None = None,
    paper: str = "A4",
) -> list[Any]:
    """Parts whose estimated body bbox exits the named ISO portrait sheet (SSO-033)."""
    papers = {
        "A4": (210.0, 297.0),
        "A3": (297.0, 420.0),
        "A2": (420.0, 594.0),
        "A1": (594.0, 841.0),
        "A0": (841.0, 1189.0),
    }
    w, h = papers.get(paper, papers["A4"])
    if sizes is None:
        sizes = {p: _part_cell_size(p) for p in positions}
    bad = []
    for p, (x, y) in positions.items():
        pw, ph = sizes[p]
        if x - pw * 0.5 < 0 or y - ph * 0.5 < 0:
            bad.append(p)
            continue
        if x + pw * 0.5 > w or y + ph * 0.5 > h:
            bad.append(p)
    return bad


def mean_signal_pair_distance(positions: dict, parts: list) -> float:
    """Mean Euclidean distance between parts sharing a signal edge (SSO-036)."""
    edges = _signal_edges(parts)
    if not edges:
        return 0.0
    total = 0.0
    n = 0
    for a, b, _w in edges:
        if a not in positions or b not in positions:
            continue
        ax, ay = positions[a]
        bx, by = positions[b]
        total += math.hypot(bx - ax, by - ay)
        n += 1
    return total / n if n else 0.0
