"""
Z3 spatial constraints between axis-aligned module bounding boxes (PCB-005).

``distance_min`` uses a minimum **edge-to-edge** gap (cardinal or diagonal separation).
``distance_max`` uses **L1 distance between rectangle centers** (not origin corners).
"""

from __future__ import annotations


def add_bbox_minimum_gap(solver, ax, ay, aw, ah, bx, by, bw, bh, g) -> None:
    """Require at least *g* integer units between the two closed bounding boxes."""
    from z3 import And, Or

    # Cardinal: separated by at least g along one axis
    c1 = ax + aw + g <= bx
    c2 = bx + bw + g <= ax
    c3 = ay + ah + g <= by
    c4 = by + bh + g <= ay
    # Diagonal corners (four octants) — Manhattan gap between closest corners >= g
    d1 = And(ax + aw <= bx, ay + ah <= by, (bx - ax - aw) + (by - ay - ah) >= g)
    d2 = And(bx + bw <= ax, ay + ah <= by, (ax - bx - bw) + (by - ay - ah) >= g)
    d3 = And(ax + aw <= bx, by + bh <= ay, (bx - ax - aw) + (ay - by - bh) >= g)
    d4 = And(bx + bw <= ax, by + bh <= ay, (ax - bx - bw) + (ay - by - bh) >= g)
    solver.add(Or(c1, c2, c3, c4, d1, d2, d3, d4))


def add_center_l1_max(solver, ax, ay, aw, ah, bx, by, bw, bh, max_sum) -> None:
    """Require Manhattan distance between centers (ax+aw/2, …) at most *max_sum* (integer, mm)."""
    from z3 import Abs

    # Doubled coordinates avoid half-mm: center*2 = 2*x + w
    ca_x = 2 * ax + aw
    cb_x = 2 * bx + bw
    ca_y = 2 * ay + ah
    cb_y = 2 * by + bh
    dx = ca_x - cb_x
    dy = ca_y - cb_y
    solver.add(Abs(dx) + Abs(dy) <= 2 * max_sum)
