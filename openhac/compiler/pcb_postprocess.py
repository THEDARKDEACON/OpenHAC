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
    except Exception as e:
        logger.debug("GetLayerID(%s) failed: %s", layer_name, e)
    try:
        return int(pcbnew_mod.LayerName(str(layer_name)))
    except Exception as e:
        logger.debug("LayerName(%s) failed: %s", layer_name, e)
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
        # Best-effort: create the net on the PCB so zones can attach even
        # before a full netlist import has populated nets.
        try:
            cls = getattr(type(pcb), "NETINFO_ITEM", None) or getattr(__import__("pcbnew"), "NETINFO_ITEM", None)
        except Exception:
            cls = None
        try:
            if cls is None:
                import pcbnew as _pcbnew  # type: ignore

                cls = getattr(_pcbnew, "NETINFO_ITEM", None)
        except Exception:
            cls = None
        if cls is None:
            return None
        try:
            ni = cls(pcb, str(net_name))
        except Exception:
            try:
                ni = cls(str(net_name))
            except Exception:
                return None
        try:
            pcb.Add(ni)
        except Exception as e:
            logger.debug("pcb_postprocess optional path failed: %s", e)
        try:
            nets = pcb.GetNetsByName()
            return nets[str(net_name)]
        except Exception:
            return ni


def sync_duplicate_pad_nets(pcb, pcbnew_mod) -> int:
    """Assign every pad that shares a pad number the same net (ABC-005 RF thermals).

    Stock RF module footprints often have many PTH pads with the same number
    (thermal vias). Netlist import only nets one of them, leaving siblings as
    ``<no net>`` which then short against the netted pad / copper pour.
    """
    fixed = 0
    try:
        fps = list(pcb.GetFootprints())
    except Exception:
        return 0
    for fp in fps:
        by_num: dict[str, list] = {}
        try:
            pads = list(fp.Pads())
        except Exception:
            continue
        for pad in pads:
            try:
                num = str(pad.GetNumber())
            except Exception:
                continue
            by_num.setdefault(num, []).append(pad)
        for num, group in by_num.items():
            if len(group) < 2:
                continue
            net_code = 0
            net_obj = None
            for pad in group:
                try:
                    nc = int(pad.GetNetCode())
                except Exception:
                    nc = 0
                if nc:
                    net_code = nc
                    try:
                        net_obj = pad.GetNet()
                    except Exception:
                        net_obj = None
                    break
            if not net_code:
                continue
            for pad in group:
                try:
                    if int(pad.GetNetCode()) == net_code:
                        continue
                except Exception:
                    pass
                try:
                    if net_obj is not None and hasattr(pad, "SetNet"):
                        pad.SetNet(net_obj)
                    else:
                        pad.SetNetCode(net_code)
                    fixed += 1
                except Exception:
                    continue
    if fixed:
        logger.info("ABC-005: synced net on %s duplicate-number pad(s) (thermal via handoff).", fixed)
    return fixed


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
            except Exception as e:
                logger.debug("pcb_postprocess optional path failed: %s", e)
        try:
            z.SetLayer(lid)
        except Exception as e:
            logger.debug("pcb_postprocess optional path failed: %s", e)

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
            # ABC-003: thermal relief spokes for pad-to-zone connections (default).
            # Solid pour when OPENHAC_POUR_PAD_CONNECTION=solid — helps FAB-021
            # GetUnconnectedCount see plane nets as connected after fill.
            pad_mode = (os.environ.get("OPENHAC_POUR_PAD_CONNECTION") or "thermal").strip().lower()
            if hasattr(z, "SetPadConnection"):
                if pad_mode in ("solid", "full", "none"):
                    pad_conn = getattr(pcbnew_mod, "ZONE_CONNECTION_FULL", None)
                    if pad_conn is None:
                        pad_conn = getattr(pcbnew_mod, "PAD_ZONE_CONN_FULL", None)
                else:
                    pad_conn = getattr(pcbnew_mod, "ZONE_CONNECTION_THERMAL", None)
                    if pad_conn is None:
                        pad_conn = getattr(pcbnew_mod, "PAD_ZONE_CONN_THERMAL", None)
                if pad_conn is not None:
                    z.SetPadConnection(pad_conn)
            if pad_mode not in ("solid", "full", "none"):
                if hasattr(z, "SetThermalReliefGap"):
                    z.SetThermalReliefGap(int(pcbnew_mod.FromMM(0.2)))
                if hasattr(z, "SetThermalReliefSpokeWidth"):
                    z.SetThermalReliefSpokeWidth(int(pcbnew_mod.FromMM(0.2)))
        except Exception as e:
            logger.debug("ABC-003 thermal relief defaults skipped: %s", e)

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
        try:
            from openhac.compiler.fab_design_settings import fill_copper_zones

            fill_copper_zones(pcb, pcbnew_mod)
        except Exception as e:
            logger.debug("ABC-002 zone fill after pours: %s", e)
    return added


def apply_high_current_polygons(pcb, board, pcbnew_mod) -> int:
    """Enterprise Phase D: Post-Route Copper Reinforcement.

    For nets tagged with current above ``OPENHAC_HIGH_CURRENT_ZONE_MIN_A`` (default
    10 A), create a copper zone covering the pad bbox on F.Cu/B.Cu. IPC-2152
    ``set_net_current`` values below that threshold stay as tracks (pouring 1–2 A
    rails as board-wide zones before FreeRouting leaves those nets unrouted).
    """
    nets = getattr(board, "_high_current_nets", {})
    if not nets:
        return 0
    try:
        min_a = float(os.environ.get("OPENHAC_HIGH_CURRENT_ZONE_MIN_A", "10") or 10)
    except Exception:
        min_a = 10.0
    nets = {
        name: info
        for name, info in nets.items()
        if float((info or {}).get("current_a") or 0.0) > min_a
    }
    if not nets:
        return 0

    added = 0
    zone_cls = getattr(pcbnew_mod, "ZONE", None) or getattr(pcbnew_mod, "ZONE_CONTAINER", None)
    if zone_cls is None:
        return 0

    for net_name, info in nets.items():
        ni = _netinfo_for_name(pcb, net_name)
        if ni is None:
            continue
            
        # Find all pads for this net to determine the zone's bounding box
        pads = []
        for fp in pcb.GetFootprints():
            for pad in fp.Pads():
                if int(pad.GetNetCode()) == int(ni.GetNetCode()):
                    pads.append(pad)
        
        if len(pads) < 2:
            continue
            
        # Calculate bounding box of pads
        min_x = min(p.GetPosition().x for p in pads)
        max_x = max(p.GetPosition().x for p in pads)
        min_y = min(p.GetPosition().y for p in pads)
        max_y = max(p.GetPosition().y for p in pads)
        
        # Inflate by 1mm for safety
        margin = int(pcbnew_mod.FromMM(1.0))
        min_x, max_x = min_x - margin, max_x + margin
        min_y, max_y = min_y - margin, max_y + margin
        
        for layer in ["F.Cu", "B.Cu"]:
            lid = _layer_id(pcb, pcbnew_mod, layer)
            if lid is None: continue
            
            z = zone_cls(pcb)
            try:
                z.SetNet(ni)
                z.SetLayer(lid)
            except Exception:
                continue
                
            def _pt(x, y):
                try: return pcbnew_mod.VECTOR2I(int(x), int(y))
                except AttributeError: return pcbnew_mod.wxPoint(int(x), int(y))
                
            pts = [
                _pt(min_x, min_y),
                _pt(max_x, min_y),
                _pt(max_x, max_y),
                _pt(min_x, max_y),
            ]
            chain = None
            try:
                chain = pcbnew_mod.SHAPE_LINE_CHAIN()
                for p in pts: chain.Append(p)
                chain.SetClosed(True)
                z.AddPolygon(chain)
            except Exception as e:
                logger.debug("pcb_postprocess optional path failed: %s", e)
            
            try:
                pcb.Add(z)
                added += 1
            except Exception:
                if chain is not None:
                    try:
                        pcb.AddArea(z, lid, ni.GetNetCode(), chain, True)
                        added += 1
                    except Exception as e:
                        logger.debug("Failed to add high-current zone for %s: %s", net_name, e)
                        continue
                else:
                    continue
                
    if added:
        logger.info("Added %d high-current copper zone(s) for nets: %s", added, list(nets.keys()))
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
    # Use board outline bbox for clamping/insetting (avoid courtyard pushing outside edges).
    edges_bb = None
    try:
        edges_bb = pcb.GetBoardEdgesBoundingBox()
    except Exception:
        edges_bb = None
    try:
        margin_iu = int(pcbnew_mod.FromMM(0.25))
    except Exception:
        margin_iu = 0
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
        except Exception as e:
            logger.debug("pcb_postprocess optional path failed: %s", e)
        try:
            fp.SetValue(fp_name)
        except Exception as e:
            logger.debug("pcb_postprocess optional path failed: %s", e)
        try:
            fp.SetPosition(_to_vec(pcbnew_mod, x_mm, y_mm))
        except Exception as e:
            logger.debug("pcb_postprocess optional path failed: %s", e)

        # Clamp the footprint bbox inside Edge.Cuts bbox (best-effort).
        if edges_bb is not None:
            try:
                fbb = fp.GetBoundingBox()
                left = int(getattr(fbb, "GetLeft")())
                top = int(getattr(fbb, "GetTop")())
                right = int(getattr(fbb, "GetRight")())
                bottom = int(getattr(fbb, "GetBottom")())

                eleft = int(getattr(edges_bb, "GetLeft")()) + margin_iu
                etop = int(getattr(edges_bb, "GetTop")()) + margin_iu
                eright = int(getattr(edges_bb, "GetRight")()) - margin_iu
                ebottom = int(getattr(edges_bb, "GetBottom")()) - margin_iu

                dx = 0
                dy = 0
                if left < eleft:
                    dx = eleft - left
                elif right > eright:
                    dx = eright - right
                if top < etop:
                    dy = etop - top
                elif bottom > ebottom:
                    dy = ebottom - bottom
                if dx or dy:
                    try:
                        pos = fp.GetPosition()
                        fp.SetPosition(pcbnew_mod.VECTOR2I(int(pos.x) + int(dx), int(pos.y) + int(dy)))
                    except Exception:
                        try:
                            pos = fp.GetPosition()
                            fp.SetPosition(pcbnew_mod.wxPoint(int(pos.x) + int(dx), int(pos.y) + int(dy)))
                        except Exception as e:
                            logger.debug("pcb_postprocess optional path failed: %s", e)
            except Exception as e:
                logger.debug("pcb_postprocess optional path failed: %s", e)
        added += 1

    if added:
        logger.info("Added %s mounting hole footprint(s) from intents.", added)
    return added


def clamp_footprints_inside_edge_cuts(pcb, pcbnew_mod, *, margin_mm: float = 0.25) -> int:
    """Clamp all footprints' bounding boxes inside the Edge.Cuts bounding box (best-effort).

    This prevents "out of bounds" placements when solver coordinates or footprint bboxes
    drift outside the board outline. Intended for handoff/dev; fabrication should still
    be reviewed in KiCad.
    """
    try:
        edges_bb = pcb.GetBoardEdgesBoundingBox()
    except Exception:
        return 0
    if edges_bb is None:
        return 0
    try:
        margin_iu = int(pcbnew_mod.FromMM(float(margin_mm)))
    except Exception:
        margin_iu = 0

    try:
        e_left = int(edges_bb.GetLeft()) + margin_iu
        e_right = int(edges_bb.GetRight()) - margin_iu
        e_top = int(edges_bb.GetTop()) + margin_iu
        e_bottom = int(edges_bb.GetBottom()) - margin_iu
    except Exception:
        return 0

    moved = 0
    try:
        fps = list(pcb.GetFootprints())
    except Exception:
        try:
            fps = list(pcb.Footprints())
        except Exception:
            return 0

    for fp in fps:
        try:
            fbb = fp.GetBoundingBox()
            left = int(fbb.GetLeft())
            right = int(fbb.GetRight())
            top = int(fbb.GetTop())
            bottom = int(fbb.GetBottom())
        except Exception:
            continue

        dx = 0
        dy = 0
        if left < e_left:
            dx = e_left - left
        elif right > e_right:
            dx = e_right - right
        if top < e_top:
            dy = e_top - top
        elif bottom > e_bottom:
            dy = e_bottom - bottom
        if not dx and not dy:
            continue
        try:
            pos = fp.GetPosition()
            new_pos = pcbnew_mod.VECTOR2I(int(pos.x + dx), int(pos.y + dy))
            fp.SetPosition(new_pos)
            moved += 1
        except Exception:
            try:
                fp.Move(pcbnew_mod.VECTOR2I(int(dx), int(dy)))
                moved += 1
            except Exception:
                continue
    if moved:
        logger.info("Clamped %s footprint(s) inside Edge.Cuts bbox.", moved)
    return moved


def spread_footprints_no_overlap(
    pcb,
    pcbnew_mod,
    *,
    max_iters: int = 200,
    step_mm: float = 0.5,
    margin_mm: float = 0.25,
) -> int:
    """Best-effort de-overlap pass using footprint bounding boxes.

    Iteratively pushes overlapping footprints apart by a small step while keeping them
    inside Edge.Cuts. This is intended for handoff/dev visualization, not final placement.
    """
    try:
        edges_bb = pcb.GetBoardEdgesBoundingBox()
    except Exception:
        return 0
    if edges_bb is None:
        return 0
    try:
        margin_iu = int(pcbnew_mod.FromMM(float(margin_mm)))
        step_iu = int(pcbnew_mod.FromMM(float(step_mm)))
    except Exception:
        return 0

    try:
        e_left = int(edges_bb.GetLeft()) + margin_iu
        e_right = int(edges_bb.GetRight()) - margin_iu
        e_top = int(edges_bb.GetTop()) + margin_iu
        e_bottom = int(edges_bb.GetBottom()) - margin_iu
    except Exception:
        return 0

    try:
        fps = list(pcb.GetFootprints())
    except Exception:
        try:
            fps = list(pcb.Footprints())
        except Exception:
            return 0

    # Stable order (reference) for determinism.
    def _ref(fp) -> str:
        try:
            return str(fp.GetReference() or "")
        except Exception:
            return ""

    fps = sorted(fps, key=_ref)

    def _is_locked(fp) -> bool:
        try:
            return bool(fp.IsLocked())
        except Exception:
            return False

    def _bb(fp):
        # Courtyard-scale box: default GetBoundingBox() includes Value/Ref silk
        # (~15 mm for a 0603) and de-overlap then shoves parts across the board.
        try:
            from openhac.compiler.pcb_placement import _footprint_pack_bbox

            b = _footprint_pack_bbox(fp)
        except Exception:
            b = fp.GetBoundingBox()
        return (
            int(b.GetLeft()) - margin_iu,
            int(b.GetTop()) - margin_iu,
            int(b.GetRight()) + margin_iu,
            int(b.GetBottom()) + margin_iu,
        )

    def _overlap(a, b) -> bool:
        al, at, ar, ab = a
        bl, bt, br, bb = b
        return not (ar <= bl or br <= al or ab <= bt or bb <= at)

    moved_fps: set[str] = set()
    it = 0
    while it < int(max_iters):
        it += 1
        any_moved = False
        # Compute bboxes each pass (pcbnew bboxes change with moves).
        bbs = []
        for fp in fps:
            try:
                bbs.append(_bb(fp))
            except Exception:
                bbs.append(None)

        for i, fp in enumerate(fps):
            if _is_locked(fp):
                continue
            bb_i = bbs[i]
            if bb_i is None:
                continue
            # Find first overlap to resolve (greedy).
            hit_j = None
            bb_j = None
            for j in range(i + 1, len(fps)):
                if _is_locked(fps[j]):
                    continue
                b = bbs[j]
                if b is None:
                    continue
                if _overlap(bb_i, b):
                    hit_j = j
                    bb_j = b
                    break
            if hit_j is None or bb_j is None:
                continue

            # Push fp away from the other footprint’s bbox center.
            il, itop, ir, ibot = bb_i
            jl, jtop, jr, jbot = bb_j
            
            # Proportional repulsion: move by a fraction of the overlap to ensure convergence.
            overlap_x = min(ir, jr) - max(il, jl)
            overlap_y = min(ibot, jbot) - max(itop, jtop)
            
            # Ensure move is at least 0.1mm if there is an overlap.
            min_push_iu = int(pcbnew_mod.FromMM(0.1))
            
            icx = (il + ir) // 2
            icy = (itop + ibot) // 2
            jcx = (jl + jr) // 2
            jcy = (jtop + jbot) // 2
            
            dx = 0
            dy = 0
            if overlap_x > overlap_y:
                # Vertical overlap is smaller, push vertically
                push = max(overlap_y // 2 + 1, min_push_iu)
                dy = push if icy >= jcy else -push
            else:
                # Horizontal overlap is smaller, push horizontally
                push = max(overlap_x // 2 + 1, min_push_iu)
                dx = push if icx >= jcx else -push

            # Apply move.
            try:
                pos = fp.GetPosition()
                newx = int(pos.x + dx)
                newy = int(pos.y + dy)
                fp.SetPosition(type(pos)(newx, newy))
            except Exception:
                try:
                    fp.Move(type(fp.GetPosition())(dx, dy))
                except Exception:
                    continue

            # Clamp inside edges immediately.
            try:
                l2, t2, r2, b2 = _bb(fp)
            except Exception:
                continue
            cdx = 0
            cdy = 0
            if l2 < e_left:
                cdx = e_left - l2
            elif r2 > e_right:
                cdx = e_right - r2
            if t2 < e_top:
                cdy = e_top - t2
            elif b2 > e_bottom:
                cdy = e_bottom - b2
            if cdx or cdy:
                try:
                    pos = fp.GetPosition()
                    fp.SetPosition(type(pos)(int(pos.x + cdx), int(pos.y + cdy)))
                except Exception:
                    try:
                        fp.Move(type(fp.GetPosition())(cdx, cdy))
                    except Exception as e:
                        logger.debug("pcb_postprocess optional path failed: %s", e)

            moved_fps.add(_ref(fp))
            any_moved = True

        if not any_moved:
            break

    if moved_fps:
        logger.info("De-overlap moved %s footprint(s) (iters=%s).", len(moved_fps), it)
    return len(moved_fps)


def replace_rectangular_edge_cuts(pcb, pcbnew_mod, w_mm: float, h_mm: float) -> bool:
    """Replace Edge.Cuts with a rectangle (0,0)–(w_mm, h_mm)."""
    try:
        edge = pcb.GetLayerID("Edge.Cuts")
    except Exception:
        return False
    drawings = []
    for getter in ("GetDrawings", "Drawings"):
        try:
            drawings = list(getattr(pcb, getter)())
            break
        except Exception:
            continue
    for d in drawings:
        try:
            if int(d.GetLayer()) != int(edge):
                continue
        except Exception:
            continue
        for rm in ("Remove", "Delete"):
            try:
                getattr(pcb, rm)(d)
                break
            except Exception:
                continue
    w_mm = max(1.0, float(w_mm))
    h_mm = max(1.0, float(h_mm))
    pts = [
        _to_vec(pcbnew_mod, 0.0, 0.0),
        _to_vec(pcbnew_mod, w_mm, 0.0),
        _to_vec(pcbnew_mod, w_mm, h_mm),
        _to_vec(pcbnew_mod, 0.0, h_mm),
    ]
    shape_cls = getattr(pcbnew_mod, "PCB_SHAPE", None)
    if shape_cls is None:
        return False
    for i in range(4):
        try:
            seg = shape_cls(pcb)
            if hasattr(pcbnew_mod, "SHAPE_T_SEGMENT"):
                seg.SetShape(pcbnew_mod.SHAPE_T_SEGMENT)
            seg.SetStart(pts[i])
            seg.SetEnd(pts[(i + 1) % 4])
            seg.SetLayer(edge)
            seg.SetWidth(int(pcbnew_mod.FromMM(0.1)))
            pcb.Add(seg)
        except Exception:
            return False
    return True


def legalize_placed_footprints(
    pcb,
    pcbnew_mod,
    board=None,
    *,
    gap_mm: float = 0.5,
    margin_mm: float = 1.0,
    rounds: int = 400,
) -> dict:
    """Separate overlapping footprints with min-displacement, then shrink-wrap.

    Does not clamp to the current Edge.Cuts while overlapping, and does not
    grow a sparse outline to chase leftover nets. Returns a small stats dict.
    """
    from openhac.compiler.legalize import legalize_aabbs, overlap_pairs
    from openhac.compiler.pcb_placement import _footprint_pack_bbox

    try:
        fps = list(pcb.GetFootprints())
    except Exception:
        try:
            fps = list(pcb.Footprints())
        except Exception:
            return {"moved": 0, "width_mm": 0.0, "height_mm": 0.0, "overlaps": -1}

    items: list[tuple[object, float, float, float, float]] = []
    for fp in fps:
        try:
            bb = _footprint_pack_bbox(fp)
            left = float(pcbnew_mod.ToMM(int(bb.GetLeft())))
            top = float(pcbnew_mod.ToMM(int(bb.GetTop())))
            if hasattr(bb, "GetWidth") and hasattr(bb, "GetHeight"):
                w = abs(float(pcbnew_mod.ToMM(int(bb.GetWidth()))))
                h = abs(float(pcbnew_mod.ToMM(int(bb.GetHeight()))))
            else:
                w = abs(float(pcbnew_mod.ToMM(int(bb.GetRight()) - int(bb.GetLeft()))))
                h = abs(float(pcbnew_mod.ToMM(int(bb.GetBottom()) - int(bb.GetTop()))))
        except Exception:
            continue
        if w < 0.05 or h < 0.05:
            continue
        items.append((fp, left, top, max(w, 0.4), max(h, 0.4)))

    if len(items) < 2:
        return {"moved": 0, "width_mm": 0.0, "height_mm": 0.0, "overlaps": 0}

    pos, bw, bh = legalize_aabbs(
        [(id(fp), x, y, w, h) for fp, x, y, w, h in items],
        gap=float(gap_mm),
        margin=float(margin_mm),
        rounds=int(rounds),
    )
    moved = 0
    for fp, x0, y0, _w, _h in items:
        xy = pos.get(id(fp))
        if xy is None:
            continue
        nx, ny = xy
        dx = float(nx) - float(x0)
        dy = float(ny) - float(y0)
        if abs(dx) < 1e-6 and abs(dy) < 1e-6:
            continue
        try:
            p = fp.GetPosition()
            newx = int(p.x + pcbnew_mod.FromMM(dx))
            newy = int(p.y + pcbnew_mod.FromMM(dy))
            fp.SetPosition(type(p)(newx, newy) if not isinstance(p, tuple) else (newx, newy))
        except Exception:
            try:
                fp.Move(_to_vec(pcbnew_mod, dx, dy))
            except Exception:
                continue
        moved += 1

    after: dict[int, tuple[float, float, float, float]] = {}
    for fp, x0, y0, w, h in items:
        xy = pos.get(id(fp), (x0, y0))
        after[id(fp)] = (xy[0], xy[1], w, h)
    n_ovl = overlap_pairs(after, float(gap_mm))

    if board is not None:
        try:
            board.size_mm = (float(bw), float(bh))
        except Exception as e:
            logger.debug("legalize: could not write board.size_mm: %s", e)
    outline_ok = replace_rectangular_edge_cuts(pcb, pcbnew_mod, bw, bh)
    logger.info(
        "Footprint legalizer: moved %s, outline %.0fx%.0f mm (edge_cuts=%s), overlaps remaining=%s.",
        moved,
        bw,
        bh,
        "ok" if outline_ok else "skip",
        n_ovl,
    )
    return {"moved": moved, "width_mm": bw, "height_mm": bh, "overlaps": n_ovl}


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
            except Exception as e:
                logger.debug("pcb_postprocess optional path failed: %s", e)
            # Mark as rule area / keepout.
            try:
                z.SetIsRuleArea(True)
            except Exception as e:
                logger.debug("pcb_postprocess optional path failed: %s", e)
            # Defaults: keepout tracks+vias+pour.
            try:
                z.SetDoNotAllowTracks(True)
                z.SetDoNotAllowVias(True)
                z.SetDoNotAllowCopperPour(True)
            except Exception as e:
                logger.debug("pcb_postprocess optional path failed: %s", e)
            if purpose == "placement":
                try:
                    z.SetDoNotAllowFootprints(True)
                except Exception as e:
                    logger.debug("pcb_postprocess optional path failed: %s", e)
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
        except Exception as e:
            logger.debug("pcb_postprocess optional path failed: %s", e)

        # Reference / value.
        try:
            fp.SetReference(f"NT{added + 1}")
        except Exception as e:
            logger.debug("pcb_postprocess optional path failed: %s", e)
        try:
            fp.SetValue("NET_TIE")
        except Exception as e:
            logger.debug("pcb_postprocess optional path failed: %s", e)

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
            except Exception as e:
                logger.debug("pcb_postprocess optional path failed: %s", e)

        added += 1

    if added:
        logger.info("Added %s net-tie footprint(s) from intents.", added)
    return added


def enable_copper_layers(pcb, pcbnew_mod, n_layers: int) -> int:
    """Honor ``Board.layers`` by enabling that many copper layers on the PCB.

    KiCad ``BOARD()`` defaults to 2 layers (F.Cu / B.Cu). A stackup comment
    without ``SetCopperLayerCount`` still exports a 2-layer Specctra DSN, so
    FreeRouting never sees In1/In2.
    """
    try:
        n = int(n_layers)
    except Exception:
        return 0
    n = max(2, min(n, 16))
    if n <= 2:
        return 2
    try:
        pcb.SetCopperLayerCount(n)
    except Exception as e:
        logger.warning("PCB-003: SetCopperLayerCount(%s) failed: %s", n, e)
        return 0
    logger.info("PCB-003: enabled %s copper layers (F.Cu + inner + B.Cu).", n)
    return n


def inject_kicad_stackup(pcb_path: str, layers: int) -> None:
    """Inject a physical layer stackup into the generated KiCad PCB."""
    try:
        layers = int(layers)
    except Exception:
        return
    if layers <= 2:
        return
    try:
        with open(pcb_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return

    # If it already has a stackup, do nothing
    if "(stackup" in content:
        return

    copper_layers = ["F.Cu"]
    for i in range(1, layers - 1):
        copper_layers.append(f"In{i}.Cu")
    copper_layers.append("B.Cu")

    stackup_lines = ["    (stackup"]
    for i, layer in enumerate(copper_layers):
        stackup_lines.append(f'      (layer "{layer}" (type "copper") (thickness 0.035))')
        if i < len(copper_layers) - 1:
            stackup_lines.append(f'      (layer "dielectric {i+1}" (type "core") (thickness 0.2) (material "FR4") (epsilon_r 4.5) (loss_tangent 0.02))')
    stackup_lines.append("    )")

    stackup_block = "\n".join(stackup_lines)
    
    if "(setup" in content:
        content = content.replace("(setup", "(setup\n" + stackup_block, 1)
        try:
            with open(pcb_path, "w", encoding="utf-8") as f:
                f.write(content)
            logger.info("Successfully injected %d-layer physical stackup definition.", layers)
        except Exception as e:
            logger.debug("pcb_postprocess optional path failed: %s", e)

