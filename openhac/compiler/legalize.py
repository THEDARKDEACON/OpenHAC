"""Axis-aligned footprint / box legalizer.

Separates overlapping rectangles by the *minimum* displacement that restores
the required edge gap, keeping the incoming pack's neighborhoods. Coincident
piles (same center) are unpacked onto a compact grid around that center — not
shoved away from the origin.

The outline shrink-wraps to the packed AABB plus margin. Boxes already inside
the margin are not pulled toward the origin. Leftover copper is not a reason
to grow or to clamp parts back into each other.

No part names, net prefixes, or board-class tables: only (x, y, w, h) + gap.
"""

from __future__ import annotations

import logging
import math
from typing import Hashable, Iterable

logger = logging.getLogger("openhac.legalize")

# Centers this close are a coincident pile, not a neighborhood that should stay.
_PILE_CENTER_SPAN_MM = 1.0


def _collides(
    ax: float,
    ay: float,
    aw: float,
    ah: float,
    bx: float,
    by: float,
    bw: float,
    bh: float,
    gap: float,
) -> bool:
    g = max(0.0, float(gap))
    return ax < bx + bw + g and ax + aw + g > bx and ay < by + bh + g and ay + ah + g > by


def overlap_pairs(
    boxes: dict[Hashable, tuple[float, float, float, float]],
    gap: float,
) -> int:
    """Count unordered pairs whose expanded AABBs still collide."""
    keys = list(boxes)
    n = 0
    for i, ka in enumerate(keys):
        ax, ay, aw, ah = boxes[ka]
        for kb in keys[i + 1 :]:
            bx, by, bw, bh = boxes[kb]
            if _collides(ax, ay, aw, ah, bx, by, bw, bh, gap):
                n += 1
    return n


def _find(parent: dict, k: Hashable) -> Hashable:
    while parent[k] != k:
        parent[k] = parent[parent[k]]
        k = parent[k]
    return k


def _overlap_components(
    boxes: dict[Hashable, list[float]],
    keys: list[Hashable],
    gap: float,
) -> list[list[Hashable]]:
    parent = {k: k for k in keys}
    for i, ka in enumerate(keys):
        a = boxes[ka]
        for kb in keys[i + 1 :]:
            b = boxes[kb]
            if _collides(a[0], a[1], a[2], a[3], b[0], b[1], b[2], b[3], gap):
                ra, rb = _find(parent, ka), _find(parent, kb)
                if ra != rb:
                    parent[rb] = ra
    groups: dict[Hashable, list[Hashable]] = {}
    for k in keys:
        groups.setdefault(_find(parent, k), []).append(k)
    return list(groups.values())


def _is_pile(boxes: dict[Hashable, list[float]], keys: list[Hashable]) -> bool:
    cxs = [boxes[k][0] + boxes[k][2] / 2.0 for k in keys]
    cys = [boxes[k][1] + boxes[k][3] / 2.0 for k in keys]
    return (max(cxs) - min(cxs)) <= _PILE_CENTER_SPAN_MM and (
        max(cys) - min(cys)
    ) <= _PILE_CENTER_SPAN_MM


def _grid_pack_around_centroid(
    boxes: dict[Hashable, list[float]],
    keys: list[Hashable],
    gap: float,
) -> None:
    """Unpack a coincident pile onto a compact grid about its centroid."""
    n = len(keys)
    if n < 2:
        return
    g = max(0.0, float(gap))
    cols = max(1, int(math.ceil(math.sqrt(n))))
    cell_w = max(boxes[k][2] for k in keys) + g
    cell_h = max(boxes[k][3] for k in keys) + g
    rows = int(math.ceil(n / cols))
    grid_w = cols * cell_w - g
    grid_h = rows * cell_h - g
    cx = sum(boxes[k][0] + boxes[k][2] / 2.0 for k in keys) / n
    cy = sum(boxes[k][1] + boxes[k][3] / 2.0 for k in keys) / n
    x0 = cx - grid_w / 2.0
    y0 = cy - grid_h / 2.0
    ordered = sorted(keys, key=lambda k: (str(type(k).__name__), str(k)))
    for i, k in enumerate(ordered):
        r, c = divmod(i, cols)
        boxes[k][0] = x0 + c * cell_w
        boxes[k][1] = y0 + r * cell_h


def _nudge_apart(a: list[float], b: list[float], gap: float) -> bool:
    """Split a colliding pair by the cheaper axis, half the extra each way.

    Does not teleport a box to the far side of the other — only the millimetres
    still needed so expanded edges no longer overlap.
    """
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    acx, acy = ax + aw / 2.0, ay + ah / 2.0
    bcx, bcy = bx + bw / 2.0, by + bh / 2.0
    need_x = (aw + bw) / 2.0 + gap
    need_y = (ah + bh) / 2.0 + gap
    dx = bcx - acx
    dy = bcy - acy
    extra_x = need_x - abs(dx)
    extra_y = need_y - abs(dy)
    if extra_x <= 1e-12 and extra_y <= 1e-12:
        return False

    use_x: bool
    if extra_x <= 1e-12:
        use_x = False
    elif extra_y <= 1e-12:
        use_x = True
    else:
        use_x = extra_x <= extra_y

    if use_x:
        sign = 1.0 if dx > 1e-12 else (-1.0 if dx < -1e-12 else 1.0)
        half = extra_x / 2.0
        a[0] -= sign * half
        b[0] += sign * half
    else:
        sign = 1.0 if dy > 1e-12 else (-1.0 if dy < -1e-12 else 1.0)
        half = extra_y / 2.0
        a[1] -= sign * half
        b[1] += sign * half
    return True


def legalize_aabbs(
    items: Iterable[tuple[Hashable, float, float, float, float]],
    *,
    gap: float,
    margin: float = 0.0,
    rounds: int = 400,
) -> tuple[dict[Hashable, tuple[float, float]], float, float]:
    """Separate ``(key, x, y, w, h)`` so edge gap is at least *gap*.

    Overlaps are resolved with minimum-axis nudges so the incoming layout
    stays put except where boxes actually collide. Returns
    ``(key → (x, y), board_w, board_h)`` shrink-wrapped to the pack plus margin.
    """
    boxes: dict[Hashable, list[float]] = {}
    for key, x, y, w, h in items:
        ww, hh = float(w or 0.0), float(h or 0.0)
        if ww <= 0 or hh <= 0:
            continue
        boxes[key] = [float(x), float(y), ww, hh]
    if not boxes:
        return {}, 0.0, 0.0

    g = max(0.0, float(gap))
    keys = list(boxes)

    for group in _overlap_components(boxes, keys, g):
        if len(group) >= 2 and _is_pile(boxes, group):
            _grid_pack_around_centroid(boxes, group, g)

    for _ in range(max(1, int(rounds))):
        moved = False
        for i, ka in enumerate(keys):
            a = boxes[ka]
            for kb in keys[i + 1 :]:
                b = boxes[kb]
                if not _collides(a[0], a[1], a[2], a[3], b[0], b[1], b[2], b[3], g):
                    continue
                if _nudge_apart(a, b, g):
                    moved = True
        if not moved:
            break

    min_x = min(v[0] for v in boxes.values())
    min_y = min(v[1] for v in boxes.values())
    m = max(0.0, float(margin))
    # Push out of the margin strip; never pull a legal pack toward the origin.
    dx = max(0.0, m - min_x)
    dy = max(0.0, m - min_y)
    pos: dict[Hashable, tuple[float, float]] = {}
    max_r = max_b = 0.0
    for key, (x, y, w, h) in boxes.items():
        nx, ny = x + dx, y + dy
        pos[key] = (nx, ny)
        max_r = max(max_r, nx + w)
        max_b = max(max_b, ny + h)
    bw = float(math.ceil(max_r + m))
    bh = float(math.ceil(max_b + m))
    return pos, bw, bh
