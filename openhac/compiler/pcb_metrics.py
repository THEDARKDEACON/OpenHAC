from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger("openhac.pcb_metrics")


def compute_pcb_metrics(pcb_path: str | Path, *, pcbnew_mod=None) -> dict:
    """Compute lightweight post-route PCB metrics from a `.kicad_pcb`.

    Intended for fabrication-mode gates and manifest visibility.
    """
    if pcbnew_mod is None:
        try:
            import pcbnew as pcbnew_mod  # type: ignore
        except Exception:
            return {}

    try:
        pcb = pcbnew_mod.LoadBoard(str(pcb_path))
    except Exception as e:
        logger.warning("PCB metrics: failed to load %s: %s", pcb_path, e)
        return {}

    track_count = 0
    via_count = 0
    try:
        for t in pcb.GetTracks():
            # KiCad has PCB_TRACK and PCB_VIA; vias are also tracks in some APIs.
            cls = t.__class__.__name__
            if "VIA" in cls.upper():
                via_count += 1
            else:
                track_count += 1
    except Exception:
        pass

    fp_count = 0
    try:
        fp_count = len(list(pcb.GetFootprints()))
    except Exception:
        try:
            fp_count = len(list(pcb.Footprints()))
        except Exception:
            fp_count = 0

    net_count = 0
    try:
        net_count = len(pcb.GetNetsByName().keys())
    except Exception:
        try:
            net_count = len(list(pcb.GetNetsByName()))
        except Exception:
            net_count = 0

    # FAB-021: best-effort unrouted connectivity via pcbnew connectivity API.
    unrouted = 0
    try:
        conn = pcb.GetConnectivity()
        # KiCad: GetUnconnectedCount() when available
        if hasattr(conn, "GetUnconnectedCount"):
            unrouted = int(conn.GetUnconnectedCount() or 0)
        elif hasattr(pcb, "GetUnconnectedCount"):
            unrouted = int(pcb.GetUnconnectedCount() or 0)
    except Exception:
        unrouted = 0

    return {
        "track_count": int(track_count),
        "via_count": int(via_count),
        "footprint_count": int(fp_count),
        "net_count": int(net_count),
        "unrouted_net_count": int(unrouted),
    }

