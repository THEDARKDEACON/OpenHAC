"""ABC-001 / ABC-005: inject fab geometry into pcbnew and audit footprint drills."""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger("openhac.fab_design_settings")


def resolve_fab_geometry_mm(board) -> dict[str, float]:
    """Return min track / clearance / via drill from fab profile + DRC defaults."""
    from openhac.compiler import rule_check as rc

    d = dict(getattr(rc, "_DRC_DEFAULTS", {}) or {})
    try:
        prof = getattr(board, "fab_profile", None)
        if prof:
            data = rc._load_fab_profile_data(str(prof))
            for k in ("min_trace_width_mm", "min_trace_clearance_mm", "min_via_drill_mm", "min_edge_clearance_mm"):
                if k in data and data[k] is not None:
                    d[k] = float(data[k])
    except Exception as e:
        logger.debug("resolve_fab_geometry_mm profile merge: %s", e)
    return {
        "min_trace_width_mm": float(d.get("min_trace_width_mm", 0.15) or 0.15),
        "min_trace_clearance_mm": float(d.get("min_trace_clearance_mm", 0.15) or 0.15),
        "min_via_drill_mm": float(d.get("min_via_drill_mm", 0.3) or 0.3),
        "min_edge_clearance_mm": float(d.get("min_edge_clearance_mm", 0.2) or 0.2),
    }


def apply_fab_design_settings(pcb, board, pcbnew_mod) -> dict[str, float]:
    """ABC-001: push fab min geometry into pcbnew board design settings before routing."""
    geo = resolve_fab_geometry_mm(board)
    try:
        ds = pcb.GetDesignSettings()
    except Exception as e:
        logger.warning("ABC-001: no design settings on board: %s", e)
        return geo

    def _set_mm(setter_names: tuple[str, ...], mm: float) -> None:
        iu = int(pcbnew_mod.FromMM(float(mm)))
        for name in setter_names:
            fn = getattr(ds, name, None)
            if callable(fn):
                try:
                    fn(iu)
                    return
                except Exception:
                    continue

    _set_mm(("SetMinTrackWidth", "m_TrackMinWidth"), geo["min_trace_width_mm"])
    # Some KiCad versions use SetCopperClearance / TrackClearance
    for attr, val in (
        ("m_MinClearance", geo["min_trace_clearance_mm"]),
        ("m_CopperEdgeClearance", geo["min_edge_clearance_mm"]),
        ("m_ViasMinSize", geo["min_via_drill_mm"] + 0.2),
        ("m_ViasMinDrill", geo["min_via_drill_mm"]),
        ("m_HoleToHoleMin", geo["min_via_drill_mm"]),
    ):
        if hasattr(ds, attr):
            try:
                setattr(ds, attr, int(pcbnew_mod.FromMM(float(val))))
            except Exception:
                pass
    for name in ("SetMinThroughDrill", "SetMinHoleToHole", "SetMinViaDrill"):
        fn = getattr(ds, name, None)
        if callable(fn):
            try:
                fn(int(pcbnew_mod.FromMM(geo["min_via_drill_mm"])))
            except Exception:
                pass

    logger.info(
        "ABC-001: fab design settings min_track=%.3fmm clearance=%.3fmm via_drill=%.3fmm",
        geo["min_trace_width_mm"],
        geo["min_trace_clearance_mm"],
        geo["min_via_drill_mm"],
    )
    # ABC-005: stock RF module thermal vias are often 0.2mm; relax board min hole to the
    # smallest plated drill present so KiCad PCB DRC matches the footprint (warn in audit).
    try:
        min_fp_drill = None
        for fp in pcb.GetFootprints():
            for pad in fp.Pads():
                drill = pad.GetDrillSize()
                if hasattr(drill, "x"):
                    d = min(int(drill.x), int(drill.y)) if int(drill.x) and int(drill.y) else max(int(drill.x), int(drill.y))
                else:
                    d = int(drill)
                if d > 0 and (min_fp_drill is None or d < min_fp_drill):
                    min_fp_drill = d
        if min_fp_drill is not None:
            fab_iu = int(pcbnew_mod.FromMM(geo["min_via_drill_mm"]))
            if min_fp_drill < fab_iu:
                mm = float(pcbnew_mod.ToMM(min_fp_drill))
                for attr in ("m_ViasMinDrill", "m_MinThroughDrill", "m_HoleToHoleMin"):
                    if hasattr(ds, attr):
                        try:
                            setattr(ds, attr, int(min_fp_drill))
                        except Exception:
                            pass
                for name in ("SetMinThroughDrill", "SetMinViaDrill", "SetMinHoleToHole"):
                    fn = getattr(ds, name, None)
                    if callable(fn):
                        try:
                            fn(int(min_fp_drill))
                        except Exception:
                            pass
                logger.warning(
                    "ABC-005: relaxed board min hole to %.3fmm to match stock footprint drills "
                    "(fab profile asked for %.3fmm).",
                    mm,
                    geo["min_via_drill_mm"],
                )
                geo["min_via_drill_mm_effective"] = mm
    except Exception as e:
        logger.debug("ABC-005 min-hole relax skipped: %s", e)
    try:
        board._last_fab_design_settings_mm = dict(geo)
    except Exception:
        pass
    return geo


def audit_footprint_min_drills(pcb, board, pcbnew_mod) -> list[str]:
    """ABC-005: list pads whose drill is below fab min via/hole drill."""
    geo = resolve_fab_geometry_mm(board)
    min_iu = int(pcbnew_mod.FromMM(geo["min_via_drill_mm"]))
    viols: list[str] = []
    try:
        fps = list(pcb.GetFootprints())
    except Exception:
        return viols
    for fp in fps:
        try:
            ref = str(fp.GetReference())
        except Exception:
            ref = "?"
        try:
            pads = list(fp.Pads())
        except Exception:
            continue
        for pad in pads:
            try:
                drill = pad.GetDrillSize()
                # VECTOR2I or size
                if hasattr(drill, "x"):
                    d = min(int(drill.x), int(drill.y)) if int(drill.x) and int(drill.y) else max(int(drill.x), int(drill.y))
                else:
                    d = int(drill)
                if d > 0 and d < min_iu:
                    viols.append(
                        f"ABC-005: footprint {ref} pad drill {pcbnew_mod.ToMM(d):.3f}mm "
                        f"< fab min_via_drill_mm={geo['min_via_drill_mm']}"
                    )
            except Exception:
                continue
    return viols


def fill_copper_zones(pcb, pcbnew_mod) -> int:
    """ABC-002: run ZONE_FILLER on the board.

    KiCad 9's in-process ``ZONE_FILLER.Fill`` can SIGSEGV on large pours when
    invoked mid-layout; skip unless explicitly enabled, or fill via a child
    process after the board is on disk (see ``fill_copper_zones_file``).
    """
    mode = (os.environ.get("OPENHAC_ZONE_FILL") or "safe").strip().lower()
    if mode in ("0", "off", "false", "no", "skip"):
        logger.debug("ABC-002: zone fill skipped (OPENHAC_ZONE_FILL=%s)", mode)
        return 0
    if mode in ("safe", "", "defer"):
        # In-process Fill is crash-prone; mark intent only. Callers that need
        # filled copper should use fill_copper_zones_file after SaveBoard.
        logger.info("ABC-002: deferring ZONE_FILLER to post-save safe fill (set OPENHAC_ZONE_FILL=force to fill in-process).")
        try:
            pcb._openhac_zones_need_fill = True  # type: ignore[attr-defined]
        except Exception:
            pass
        return 0
    return _fill_copper_zones_inplace(pcb, pcbnew_mod)


def _fill_copper_zones_inplace(pcb, pcbnew_mod) -> int:
    filler_cls = getattr(pcbnew_mod, "ZONE_FILLER", None)
    if filler_cls is None:
        logger.debug("ABC-002: ZONE_FILLER unavailable")
        return 0
    try:
        filler = filler_cls(pcb)
        # Prefer the native ZONE_LIST / Zones() proxy — list() copies can crash Fill.
        zones = pcb.Zones() if hasattr(pcb, "Zones") else None
        if zones is None and hasattr(pcb, "GetAreaCount"):
            zones = [pcb.GetArea(i) for i in range(int(pcb.GetAreaCount()))]
        try:
            n = len(zones) if zones is not None else 0
        except Exception:
            n = 0
        if not n:
            return 0
        if hasattr(filler, "Fill"):
            filler.Fill(zones)
        elif hasattr(filler, "FillZones"):
            filler.FillZones(zones)
        else:
            return 0
        logger.info("ABC-002: filled %d copper zone(s).", n)
        return int(n)
    except Exception as e:
        logger.warning("ABC-002: zone fill failed: %s", e)
        return 0


def fill_copper_zones_file(pcb_path: str) -> int:
    """ABC-002: fill zones in a child process so a KiCad segfault cannot kill compile."""
    import subprocess
    import sys

    path = str(pcb_path)
    if not path or not os.path.isfile(path):
        return 0
    mode = (os.environ.get("OPENHAC_ZONE_FILL") or "safe").strip().lower()
    if mode in ("0", "off", "false", "no", "skip"):
        return 0
    code = (
        "import sys\n"
        "import pcbnew\n"
        "from openhac.compiler.fab_design_settings import _fill_copper_zones_inplace\n"
        f"p = {path!r}\n"
        "b = pcbnew.LoadBoard(p)\n"
        "n = _fill_copper_zones_inplace(b, pcbnew)\n"
        "pcbnew.SaveBoard(p, b)\n"
        "print(n)\n"
    )
    env = dict(os.environ)
    env["OPENHAC_ZONE_FILL"] = "force"  # child uses in-process fill
    try:
        r = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=float(os.environ.get("OPENHAC_ZONE_FILL_TIMEOUT_S") or "120"),
            env=env,
            check=False,
        )
    except Exception as e:
        logger.warning("ABC-002: safe zone-fill subprocess failed to start: %s", e)
        return 0
    if r.returncode != 0:
        logger.warning(
            "ABC-002: safe zone-fill subprocess rc=%s stderr=%s",
            r.returncode,
            (r.stderr or "")[:400],
        )
        return 0
    try:
        n = int((r.stdout or "").strip().splitlines()[-1])
    except Exception:
        n = 0
    if n:
        logger.info("ABC-002: safe-filled %d copper zone(s) via child process.", n)
    return n


def apply_routability_env_defaults() -> None:
    """ABC-004: optional denser pack when OPENHAC_ROUTABILITY_MODE=dense."""
    mode = (os.environ.get("OPENHAC_ROUTABILITY_MODE") or "").strip().lower()
    if mode not in ("dense", "signal", "1", "true", "yes"):
        return
    # Milder defaults — heavy inflate caused huge boards + FreeRouting thrash.
    os.environ.setdefault("OPENHAC_MODULE_CLEARANCE_MM", "4.0")
    os.environ.setdefault("OPENHAC_PLACEMENT_FP_GAP_MM", "2.5")
    os.environ.setdefault("OPENHAC_MODULE_PACK_INFLATE", "1.45")
    os.environ.setdefault("OPENHAC_AUTO_BOARD_MARGIN_FACTOR", "1.40")
    os.environ.setdefault("OPENHAC_AUTO_BOARD_MIN_EDGE_MARGIN_MM", "6.0")
