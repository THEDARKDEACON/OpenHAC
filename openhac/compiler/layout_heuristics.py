from __future__ import annotations

import logging
import re

logger = logging.getLogger("openhac.layout_heuristics")


def apply_layout_heuristics(board) -> dict:
    """Apply best-effort layout heuristics by mutating board constraints/settings.

    This is intentionally conservative and module-level (Phase 2 foundation):
    - tries to pin obvious connector modules to an edge
    - tries to separate obvious power modules from RF/analog by minimum distances

    Returns a small summary dict for debugging/tests.
    """
    mods = getattr(board, "all_modules", None) or getattr(board, "modules", None) or []
    if not mods:
        return {"applied": 0}

    applied = 0

    def name(m) -> str:
        return str(getattr(m, "name", "") or "")

    # Heuristic 1: connectors tend to belong on an edge.
    for m in mods:
        n = name(m).lower()
        if re.search(r"(conn|connector|xt60|usb|header|jtag|uart)", n):
            try:
                board.constrain_edge(m, "TOP")
                applied += 1
            except Exception:
                pass

    # Heuristic 2: keep power modules away from RF/analog modules (noise).
    power_mods = [m for m in mods if re.search(r"\b(power|reg|ldo|buck|dc[-_]?dc)\b", name(m).lower())]
    quiet_mods = [m for m in mods if re.search(r"\b(rf|analog|adc|dac|lna)\b", name(m).lower())]
    for pm in power_mods:
        for qm in quiet_mods:
            try:
                board.constrain_distance_min(pm, qm, 8)
                applied += 1
            except Exception:
                pass

    return {"applied": applied}

