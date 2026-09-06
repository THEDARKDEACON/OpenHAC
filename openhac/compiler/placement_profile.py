"""Named placement profiles (CODE-004).

Complex-board CI must set ``OPENHAC_PLACEMENT_PROFILE=complex_ci`` (or pass the
name to :func:`apply_named_placement_profile`) instead of silently stuffing
env knobs. ABC-007 repair stays generic (gap + autosize).
"""

from __future__ import annotations

import os

PROFILES: dict[str, dict[str, str]] = {
    "complex_ci": {
        "OPENHAC_MODULE_CLEARANCE_MM": "12.0",
        "OPENHAC_PLACEMENT_FP_GAP_MM": "4.0",
        "OPENHAC_MODULE_PACK_INFLATE": "2.2",
        "OPENHAC_PLACEMENT_GRID_COLS": "2",
        "OPENHAC_AUTO_BOARD_MARGIN_FACTOR": "2.2",
        "OPENHAC_AUTO_BOARD_MIN_EDGE_MARGIN_MM": "15.0",
        "OPENHAC_FP_OVERLAP_CLEARANCE_MM": "0.2",
        "OPENHAC_ZONE_FILL": "safe",
        "OPENHAC_POUR_PAD_CONNECTION": "solid",
    },
}


def apply_named_placement_profile(
    env: dict[str, str] | None = None,
    name: str | None = None,
    *,
    for_route: bool = False,
) -> dict[str, str]:
    """Apply a named profile onto *env* (or ``os.environ``).

    Unknown / empty names are a no-op. Values use ``setdefault`` so explicit
    knobs win.
    """
    target = env if env is not None else os.environ
    prof = (name or target.get("OPENHAC_PLACEMENT_PROFILE") or os.environ.get("OPENHAC_PLACEMENT_PROFILE") or "").strip()
    knobs = dict(PROFILES.get(prof) or {})
    if for_route and prof == "complex_ci":
        knobs["OPENHAC_DEOVERLAP_PASSES"] = "3"
        knobs["OPENHAC_ROUTABILITY_MODE"] = "dense"
        knobs["OPENHAC_DEFER_COPPER_POURS"] = "1"
    for k, v in knobs.items():
        target.setdefault(k, v)
    return target
