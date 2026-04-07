"""
pcb_postprocess.py

Best-effort pcbnew post-processing after footprint placement.

These helpers intentionally have a very small surface area so they can be unit-tested
with a stub pcbnew module in CI (where KiCad may not be installed).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from openhac.compiler.pcb_placement import resolve_pretty_directory

logger = logging.getLogger("openhac.pcb_postprocess")


def _layer_id(pcb, pcbnew_mod, layer_name: str) -> int | None:
    """Return KiCad internal layer ID for a name like 'F.Cu'."""
    try:
        return int(pcb.GetLayerID(str(layer_name)))
    except Exception:
        pass
    try:
        return int(pcbnew_mod.LayerName(str(layer_name)))
    except Exception:
        return None


def _to_vec(pcbnew_mod, x_mm: float, y_mm: float):
    x = int(pcbnew_mod.FromMM(float(x_mm)))
    y = int(pcbnew_mod.FromMM(float(y_mm)))
    try:
        return pcbnew_mod.VECTOR2I(x, y)
    except AttributeError:
        return pcbnew_mod.wxPoint(x, y)


def _netinfo_for_name(pcb, net_name: str):
    """Return a pcbnew NETINFO_ITEM for *net_name*, or None."""
    try:
        nets = pcb.GetNetsByName()
    except Exception:
        return None
    try:
        return nets[str(net_name)]
    except Exception:
        return None


def apply_copper_pour_intents(pcb, board, pcbnew_mod) -> int:
    """Emit pcbnew copper zones for any declared copper pour intents (PCB-009 stretch).

    Returns number of zones added.
    """
    intents = list(getattr(board, "_copper_pour_intents", None) or [])
    if not intents:
        return 0

    added = 0
    w_mm, h_mm = getattr(board, "size_mm", (0, 0))
    if not w_mm or not h_mm:
        return 0

    zone_cls = getattr(pcbnew_mod, "ZONE", None) or getattr(pcbnew_mod, "ZONE_CONTAINER", None)
    if zone_cls is None:
        logger.warning("pcbnew has no ZONE class; skipping copper pour emission.")
        return 0

    for rec in intents:
        net_name = str(rec.get("net") or "").strip()
        layer = str(rec.get("layer") or "F.Cu").strip() or "F.Cu"
        if not net_name:
            continue

        ni = _netinfo_for_name(pcb, net_name)
        if ni is None:
            logger.warning("Copper pour intent net %r not present on PCB; skipping zone.", net_name)
            continue
        lid = _layer_id(pcb, pcbnew_mod, layer)
        if lid is None:
            logger.warning("Copper pour intent layer %r not recognized; skipping zone.", layer)
            continue

        z = zone_cls(pcb)
        try:
            z.SetNet(ni)
        except Exception:
            try:
                z.SetNetCode(int(ni.GetNetCode()))
            except Exception:
                pass
        try:
            z.SetLayer(lid)
        except Exception:
            pass

        # Simple "board outline" rectangle zone. This does not do keepouts or stitching.
        # KiCad 9 expects a SHAPE_LINE_CHAIN for AddPolygon().
        pts = [
            _to_vec(pcbnew_mod, 0.5, 0.5),
            _to_vec(pcbnew_mod, float(w_mm) - 0.5, 0.5),
            _to_vec(pcbnew_mod, float(w_mm) - 0.5, float(h_mm) - 0.5),
            _to_vec(pcbnew_mod, 0.5, float(h_mm) - 0.5),
        ]
        try:
            chain = pcbnew_mod.SHAPE_LINE_CHAIN()
            for p in pts:
                chain.Append(p)
            chain.SetClosed(True)
            z.AddPolygon(chain)
        except Exception:
            logger.warning("Failed to define zone polygon for net %r on %s.", net_name, layer)
            continue

        try:
            pcb.Add(z)
        except Exception:
            try:
                pcb.AddArea(z, lid, ni.GetNetCode(), poly, True)
            except Exception:
                logger.warning("Failed to add zone object for net %r on %s.", net_name, layer)
                continue

        added += 1

    if added:
        logger.info("Added %s copper zone(s) from pour intents.", added)
    return added


@dataclass(frozen=True)
class MountingHoleFootprintChoice:
    lib_name: str
    fp_name: str


def _choose_mounting_hole_fp(pretty_dir: str, diameter_mm: float) -> str:
    """Choose a mounting hole footprint name from a pretty directory."""
    d = float(diameter_mm)
    # Common exact names shipped in KiCad's MountingHole.pretty.
    candidates = [
        f"MountingHole_{d:.1f}mm",
        f"MountingHole_{d:.2f}mm",
        f"MountingHole_{d:.1f}mm_M{int(round(d))}",
        "MountingHole_3.2mm_M3",
        "MountingHole_2.2mm_M2_DIN965",
        "MountingHole_2.2mm_M2_ISO14580",
        "MountingHole_2.1mm",
    ]
    try:
        files = set(os.listdir(pretty_dir))
    except Exception:
        files = set()

    for base in candidates:
        if f"{base}.kicad_mod" in files:
            return base
    # As a last resort, just return the fallback (load may still fail; caller will handle).
    return "MountingHole_3.2mm_M3"


def apply_mounting_hole_intents(pcb, board, pcbnew_mod) -> int:
    """Emit mounting hole footprints for declared mounting hole intents (PCB-010 stretch).

    Returns number of footprints added.
    """
    intents = list(getattr(board, "_mounting_hole_intents", None) or [])
    if not intents:
        return 0

    pretty_dir = resolve_pretty_directory("MountingHole")
    if not pretty_dir:
        logger.warning("MountingHole.pretty not found in footprint search paths; skipping mounting holes.")
        return 0

    added = 0
    for i, rec in enumerate(intents, start=1):
        try:
            x_mm = float(rec.get("x_mm"))
            y_mm = float(rec.get("y_mm"))
            d_mm = float(rec.get("diameter_mm"))
        except Exception:
            continue

        fp_name = _choose_mounting_hole_fp(pretty_dir, d_mm)
        try:
            fp = pcbnew_mod.FootprintLoad(pretty_dir, fp_name)
        except Exception:
            fp = None
        if fp is None:
            logger.warning("Failed to load mounting hole footprint %r from %s.", fp_name, pretty_dir)
            continue

        try:
            pcb.Add(fp)
        except Exception:
            continue

        try:
            fp.SetReference(f"H{i}")
        except Exception:
            pass
        try:
            fp.SetValue(fp_name)
        except Exception:
            pass
        try:
            fp.SetPosition(_to_vec(pcbnew_mod, x_mm, y_mm))
        except Exception:
            pass
        added += 1

    if added:
        logger.info("Added %s mounting hole footprint(s) from intents.", added)
    return added


def apply_keepout_rect_intents(pcb, board, pcbnew_mod) -> int:
    """Emit pcbnew rule-area keepout rectangles (stretch).

    Returns number of keepout zones added.
    """
    intents = list(getattr(board, "_keepout_rect_intents", None) or [])
    if not intents:
        return 0

    zone_cls = getattr(pcbnew_mod, "ZONE", None) or getattr(pcbnew_mod, "ZONE_CONTAINER", None)
    if zone_cls is None:
        logger.warning("pcbnew has no ZONE class; skipping keepout emission.")
        return 0

    added = 0
    for rec in intents:
        try:
            x = float(rec.get("x_mm"))
            y = float(rec.get("y_mm"))
            w = float(rec.get("w_mm"))
            h = float(rec.get("h_mm"))
        except Exception:
            continue
        layers = rec.get("layers") or ["F.Cu", "B.Cu"]
        purpose = str(rec.get("purpose") or "copper_tracks_vias").strip().lower()
        for layer in layers:
            lid = _layer_id(pcb, pcbnew_mod, str(layer))
            if lid is None:
                continue
            z = zone_cls(pcb)
            try:
                z.SetLayer(lid)
            except Exception:
                pass
            # Mark as rule area / keepout.
            try:
                z.SetIsRuleArea(True)
            except Exception:
                pass
            # Defaults: keepout tracks+vias+pour.
            try:
                z.SetDoNotAllowTracks(True)
                z.SetDoNotAllowVias(True)
                z.SetDoNotAllowCopperPour(True)
            except Exception:
                pass
            if purpose == "placement":
                try:
                    z.SetDoNotAllowFootprints(True)
                except Exception:
                    pass
            pts = [
                _to_vec(pcbnew_mod, x, y),
                _to_vec(pcbnew_mod, x + w, y),
                _to_vec(pcbnew_mod, x + w, y + h),
                _to_vec(pcbnew_mod, x, y + h),
            ]
            try:
                chain = pcbnew_mod.SHAPE_LINE_CHAIN()
                for p in pts:
                    chain.Append(p)
                chain.SetClosed(True)
                z.AddPolygon(chain)
            except Exception:
                continue
            try:
                pcb.Add(z)
            except Exception:
                continue
            added += 1

    if added:
        logger.info("Added %s keepout zone(s) from keepout intents.", added)
    return added


def _parse_fp_id(fp: str) -> tuple[str, str] | None:
    s = str(fp or "").strip()
    if ":" not in s:
        return None
    lib, name = s.split(":", 1)
    lib, name = lib.strip(), name.strip()
    if not lib or not name:
        return None
    return lib, name


def apply_net_tie_intents(pcb, board, pcbnew_mod) -> int:
    """Emit net-tie footprints and assign pad nets (stretch)."""
    intents = list(getattr(board, "_net_tie_intents", None) or [])
    if not intents:
        return 0

    added = 0
    fallback_i = 0
    for rec in intents:
        net_a = str(rec.get("net_a") or "").strip()
        net_b = str(rec.get("net_b") or "").strip()
        fp_id = _parse_fp_id(rec.get("footprint"))
        if not net_a or not net_b or fp_id is None:
            continue

        ni_a = _netinfo_for_name(pcb, net_a)
        ni_b = _netinfo_for_name(pcb, net_b)
        if ni_a is None or ni_b is None:
            continue

        pretty_dir = resolve_pretty_directory(fp_id[0])
        if not pretty_dir:
            continue
        try:
            fp = pcbnew_mod.FootprintLoad(pretty_dir, fp_id[1])
        except Exception:
            fp = None
        if fp is None:
            continue

        try:
            pcb.Add(fp)
        except Exception:
            continue

        # Position.
        x_mm = rec.get("x_mm")
        y_mm = rec.get("y_mm")
        try:
            if x_mm is not None and y_mm is not None:
                x = float(x_mm)
                y = float(y_mm)
            else:
                # Fallback: place near top-left grid so it is visible.
                col = fallback_i % 6
                row = fallback_i // 6
                x, y = 3.0 + col * 4.0, 3.0 + row * 4.0
                fallback_i += 1
            fp.SetPosition(_to_vec(pcbnew_mod, x, y))
        except Exception:
            pass

        # Reference / value.
        try:
            fp.SetReference(f"NT{added + 1}")
        except Exception:
            pass
        try:
            fp.SetValue("NET_TIE")
        except Exception:
            pass

        # Assign pad 1 -> net_a, pad 2 -> net_b when possible.
        try:
            pads = list(fp.Pads())
        except Exception:
            pads = []
        for pad in pads:
            try:
                pn = str(pad.GetPadName() or pad.GetNumber())
            except Exception:
                pn = ""
            try:
                if pn == "1":
                    pad.SetNet(ni_a)
                elif pn == "2":
                    pad.SetNet(ni_b)
            except Exception:
                pass

        added += 1

    if added:
        logger.info("Added %s net-tie footprint(s) from intents.", added)
    return added

