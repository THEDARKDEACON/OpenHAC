"""PLC-001: overlay footprint pose vs board outline / catastrophic courtyard overlap."""

from __future__ import annotations

import logging
import math
import re
from typing import Any

from openhac.compiler.kicad_artwork import FpPose
from openhac.core.exceptions import PlacementIntentError

logger = logging.getLogger("openhac.placement_intent")

_START_RE = re.compile(r"\(start\s+([-0-9.]+)\s+([-0-9.]+)\)")
_END_RE = re.compile(r"\(end\s+([-0-9.]+)\s+([-0-9.]+)\)")


def _outline_mm(board) -> tuple[float, float]:
    size = getattr(board, "size_mm", None) or (0.0, 0.0)
    return float(size[0]), float(size[1])


def pose_outside_outline(pose: FpPose, width: float, height: float, *, margin_mm: float = 0.1) -> bool:
    if width <= 0 or height <= 0:
        return False
    return (
        pose.x < -margin_mm
        or pose.y < -margin_mm
        or pose.x > width + margin_mm
        or pose.y > height + margin_mm
    )


def courtyard_bbox_world(pose: FpPose) -> tuple[float, float, float, float]:
    """Axis-aligned bbox in board space. Missing courtyard → 1 mm pad around origin."""
    local = getattr(pose, "crtyd_local", None)
    if local and len(local) == 4:
        xmin, ymin, xmax, ymax = (float(x) for x in local)
    else:
        xmin = ymin = -0.5
        xmax = ymax = 0.5
    rot = math.radians(float(pose.rot or 0.0))
    c, s = math.cos(rot), math.sin(rot)
    corners = [(xmin, ymin), (xmin, ymax), (xmax, ymin), (xmax, ymax)]
    xs: list[float] = []
    ys: list[float] = []
    for x, y in corners:
        xs.append(pose.x + x * c - y * s)
        ys.append(pose.y + x * s + y * c)
    return (min(xs), min(ys), max(xs), max(ys))


def _overlap_area(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    dx = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    dy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    return dx * dy


def _area(box: tuple[float, float, float, float]) -> float:
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def catastrophic_overlap(a: FpPose, b: FpPose) -> bool:
    """True when courtyards share most of the smaller footprint, or centers are stacked."""
    dist = math.hypot(a.x - b.x, a.y - b.y)
    if dist < 0.25:
        return True
    ba, bb = courtyard_bbox_world(a), courtyard_bbox_world(b)
    ov = _overlap_area(ba, bb)
    smaller = min(_area(ba), _area(bb))
    if smaller <= 0:
        return False
    return ov / smaller >= 0.5


def check_overlay_placement(
    overlay,
    board,
    *,
    fail: bool = True,
) -> list[str]:
    fps: dict[str, FpPose] = dict(getattr(overlay, "footprints", None) or {})
    if not fps:
        return []
    w, h = _outline_mm(board)
    viols: list[str] = []
    for ref, pose in fps.items():
        if pose_outside_outline(pose, w, h):
            viols.append(
                f"PLC-001: overlay footprint {ref} at ({pose.x:.3f},{pose.y:.3f}) "
                f"is outside board outline {w:.3f}x{h:.3f} mm"
            )
    refs = list(fps.items())
    for i, (ra, pa) in enumerate(refs):
        for rb, pb in refs[i + 1 :]:
            if catastrophic_overlap(pa, pb):
                viols.append(
                    f"PLC-001: overlay footprints {ra} and {rb} have catastrophic courtyard overlap"
                )
    if viols and fail:
        raise PlacementIntentError("\n".join(viols))
    for v in viols:
        logger.warning("%s", v)
    return viols


def parse_courtyard_local(footprint_block: str) -> tuple[float, float, float, float] | None:
    """Best-effort CrtYd bbox in footprint-local mm from a ``(footprint …)`` sexp."""
    from openhac.compiler.kicad_artwork import _courtyard_local_from_fp_block

    return _courtyard_local_from_fp_block(footprint_block)
