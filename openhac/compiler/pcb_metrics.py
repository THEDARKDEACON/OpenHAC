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

    # FAB-021 / ABC-006: unrouted connectivity — never silent-zero on API failure under fab.
    unrouted = 0
    unrouted_error: str | None = None
    try:
        conn = pcb.GetConnectivity()
        if hasattr(conn, "GetUnconnectedCount"):
            try:
                # KiCad 9+: GetUnconnectedCount(aVisibileOnly: bool)
                unrouted = int(conn.GetUnconnectedCount(False) or 0)
            except TypeError:
                unrouted = int(conn.GetUnconnectedCount() or 0)
        elif hasattr(pcb, "GetUnconnectedCount"):
            try:
                unrouted = int(pcb.GetUnconnectedCount(False) or 0)
            except TypeError:
                unrouted = int(pcb.GetUnconnectedCount() or 0)
        else:
            unrouted_error = "no GetUnconnectedCount API"
    except Exception as e:
        unrouted_error = str(e)
        unrouted = -1  # sentinel: unknown

    out = {
        "track_count": int(track_count),
        "via_count": int(via_count),
        "footprint_count": int(fp_count),
        "net_count": int(net_count),
        "unrouted_net_count": int(unrouted) if unrouted >= 0 else 0,
    }
    if unrouted_error:
        out["unrouted_net_count_error"] = unrouted_error
        out["unrouted_net_count_unknown"] = True
    return out

