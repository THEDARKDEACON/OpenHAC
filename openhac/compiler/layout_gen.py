import logging
import math
import os

from openhac.compiler.layout_constraints import add_bbox_minimum_gap, add_center_l1_max
from openhac.core.base import LayoutGenerationError

logger = logging.getLogger("openhac.layout")


def _z3_timeout_ms() -> int | None:
    """Z3 solver timeout in ms. Default 60s; ``0``/``none``/``off`` = unlimited."""
    v = (os.environ.get("OPENHAC_Z3_TIMEOUT_MS") or "").strip().lower()
    if not v:
        return 60_000
    if v in ("0", "none", "off", "unlimited", "inf", "infinity"):
        return None
    try:
        x = int(float(v))
    except ValueError:
        return 60_000
    if x <= 0:
        return None
    return x


def _ceil_mm(v) -> int:
    return int(math.ceil(float(v or 0)))


def _z3_compact_enabled() -> bool:
    return (os.environ.get("OPENHAC_Z3_COMPACT") or "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def _shrink_board_to_placed_aabb(board) -> None:
    """Crop Edge.Cuts to the placed-module AABB so SAT slack is not empty FR copper."""
    try:
        mods = list(getattr(board, "_get_all_modules", lambda: [])() or [])
    except Exception:
        mods = list(getattr(board, "modules", []) or [])
    placed = [
        m
        for m in mods
        if getattr(m, "placed_x", None) is not None and getattr(m, "placed_y", None) is not None
    ]
    if not placed:
        return
    for rule in getattr(board, "constraints", None) or []:
        if rule.get("type") != "edge":
            continue
        raw = rule.get("args")
        args = list(raw) if isinstance(raw, (list, tuple)) else []
        if len(args) >= 2 and str(args[1]).upper() in ("RIGHT", "BOTTOM"):
            return
    max_r = max(float(m.placed_x) + float(getattr(m, "width", 0) or 0) for m in placed)
    max_b = max(float(m.placed_y) + float(getattr(m, "height", 0) or 0) for m in placed)
    try:
        pad = float(os.environ.get("OPENHAC_AUTO_BOARD_MIN_EDGE_MARGIN_MM") or "4")
    except Exception:
        pad = 4.0
    pad = max(1.0, pad)
    w = float(math.ceil(max_r + pad))
    h = float(math.ceil(max_b + pad))
    old_w, old_h = float(board.size_mm[0]), float(board.size_mm[1])
    if w >= old_w - 0.5 and h >= old_h - 0.5:
        return
    board.size_mm = (min(old_w, w), min(old_h, h))
    logger.info(
        "Cropped board outline to %.0fx%.0f mm (was %.0fx%.0f) around packed modules.",
        board.size_mm[0],
        board.size_mm[1],
        old_w,
        old_h,
    )


def _placement_modules(board):
    try:
        from openhac.compiler.cluster_affinity import z3_modules

        mods = list(z3_modules(board))
        if mods:
            return mods
    except Exception:
        pass
    return list(getattr(board, "all_modules", None) or getattr(board, "modules", []) or [])


def solve_placement(board):
    all_mods = _placement_modules(board)

    try:
        from openhac.compiler.placement_engine import affinity_engine_enabled, apply_affinity_floorplan

        if affinity_engine_enabled() and all_mods:
            if apply_affinity_floorplan(board):
                try:
                    from openhac.compiler.cluster_affinity import apply_satellite_offsets_after_z3

                    apply_satellite_offsets_after_z3(board)
                except Exception as e:
                    logger.debug("satellite offset apply skipped: %s", e)
                try:
                    _shrink_board_to_placed_aabb(board)
                except Exception as e:
                    logger.debug("outline crop skipped: %s", e)
                logger.info(
                    "Placement engine: signal-net graph pack "
                    "(OPENHAC_PLACEMENT_PACK=shelf for debug grid; OPENHAC_PLACEMENT_ENGINE=z3 for SMT)."
                )
                return True
    except Exception as e:
        logger.warning("Affinity floorplan failed (%s); falling back to Z3.", e)

    logger.info("Running Z3 SMT Spatial Solver...")
    compact = _z3_compact_enabled()
    try:
        from z3 import Solver, Int, sat, Or, And

        if compact:
            from z3 import Optimize
    except ImportError:
        logger.warning("Z3 solver not installed. Skipping algorithmic placement.")
        return False
    for mod in all_mods:
        if mod.width == 10.0 and mod.height == 10.0:
            area = 0.0
            for child in mod.components:
                from openhac.core.base import Module
                if isinstance(child, Module):
                    continue
                part = getattr(child, "part", None)
                if part:
                    fp = str(getattr(part, "footprint", "")).upper()
                    if "0402" in fp or "0201" in fp: area += 4.0
                    elif "0603" in fp or "0805" in fp: area += 8.0
                    elif "QFN" in fp or "QFP" in fp or "BGA" in fp: area += 100.0
                    elif "CONN" in fp: area += 150.0
                    else: area += 20.0
            if area > 0:
                side = math.sqrt(area) * 1.2
                mod.width = max(10.0, side)
                mod.height = max(10.0, side)

    # Debug: Log layout problem details
    logger.info("Layout problem:")
    logger.info(f"  Board: {board.size_mm[0]} x {board.size_mm[1]} mm ({board.layers} layers)")
    logger.info(f"  Modules: {len(all_mods)} (Z3 participants)")
    total_mod_area = 0.0
    for mod in all_mods:
        mod_area = mod.width * mod.height
        total_mod_area += mod_area
        logger.info(f"    - {mod.name}: {mod.width:.1f} x {mod.height:.1f} mm (area: {mod_area:.1f} mm², components: {len(mod.components)})")
    board_area = board.size_mm[0] * board.size_mm[1]
    utilization = (total_mod_area / board_area) * 100 if board_area > 0 else 0
    logger.info(f"  Total component area: {total_mod_area:.1f} mm²")
    logger.info(f"  Board area: {board_area:.1f} mm²")
    logger.info(f"  Estimated utilization: {utilization:.1f}%")
    if board.constraints:
        logger.info(f"  User constraints: {len(board.constraints)}")
        for rule in board.constraints:
            logger.info(f"    - {rule['type']}: {rule['args']}")

    try:
        g_mm = float(getattr(board, "module_clearance_mm", 0.0) or 0.0)
    except Exception:
        g_mm = 0.0
    clearance_src = "Board.module_clearance_mm / --module-gap-mm"
    if g_mm <= 0:
        ev = (os.environ.get("OPENHAC_MODULE_CLEARANCE_MM") or "").strip()
        if ev:
            try:
                g_mm = float(ev)
                clearance_src = "OPENHAC_MODULE_CLEARANCE_MM (.env / env)"
            except Exception:
                g_mm = 0.0
    g_int = max(0, int(math.ceil(g_mm)))
    if g_mm > 0:
        logger.info(
            "  Z3 module bbox clearance target: >= %s mm (edge-to-edge, int %s) [%s]",
            g_mm,
            g_int,
            clearance_src,
        )

    solver = Optimize() if compact else Solver()
    timeout_ms = _z3_timeout_ms()
    if timeout_ms is not None:
        try:
            solver.set(timeout=timeout_ms)
            logger.info("  Z3 timeout: %s ms", timeout_ms)
        except Exception as e:
            logger.debug("Could not set Z3 timeout: %s", e)
    if compact:
        logger.info("  Z3 compact: minimize used bounding-box extent")

    # 1. Bounds Constraints
    for mod in all_mods:
        mod.z3_x = Int(f"{mod.name}_x")
        mod.z3_y = Int(f"{mod.name}_y")
        
        # Add a safety margin from the board edge to prevent component anchors 
        # (often at footprint center) from causing off-board placement.
        # [Professional Grade] Dynamic scaling for sensitive sensor suites (U26).
        base_margin = float(getattr(board, "bbox_padding_mm", 5.0) or 5.0)
        if "SENSOR" in str(mod.name).upper() or any(getattr(c, "current_a", 0) > 10.0 for c in mod.components):
            edge_margin = int(math.ceil(base_margin * 1.5)) # 50% more margin for power/sensors
        else:
            edge_margin = int(math.ceil(base_margin))
            
        solver.add(mod.z3_x >= edge_margin)
        solver.add(mod.z3_y >= edge_margin)
        
        # Use ceil to prevent float-to-int truncation overflow at board edges
        mw = _ceil_mm(mod.width)
        mh = _ceil_mm(mod.height)
        solver.add(mod.z3_x + mw <= int(math.floor(float(board.size_mm[0]))) - edge_margin)
        solver.add(mod.z3_y + mh <= int(math.floor(float(board.size_mm[1]))) - edge_margin)
        
    # 2. Non-overlapping constraints (Z3 participants only)
    n = len(all_mods)
    for i in range(n):
        for j in range(i + 1, n):
            a = all_mods[i]
            b = all_mods[j]
            aw, ah = _ceil_mm(a.width), _ceil_mm(a.height)
            bw, bh = _ceil_mm(b.width), _ceil_mm(b.height)
            if g_int > 0:
                add_bbox_minimum_gap(
                    solver,
                    a.z3_x,
                    a.z3_y,
                    aw,
                    ah,
                    b.z3_x,
                    b.z3_y,
                    bw,
                    bh,
                    g_int,
                )
            else:
                no_overlap = Or(
                    a.z3_x + aw <= b.z3_x,
                    b.z3_x + bw <= a.z3_x,
                    a.z3_y + ah <= b.z3_y,
                    b.z3_y + bh <= a.z3_y,
                )
                solver.add(no_overlap)
            
    # 3. User Defined Constraints (skip rules whose modules are not in Z3 set)
    z3_ids = {id(m) for m in all_mods}
    for rule in board.constraints:
        typ = rule['type']
        args = rule['args']
        if typ == 'distance_min':
            mod_a, mod_b, min_mm = args
            if id(mod_a) not in z3_ids or id(mod_b) not in z3_ids:
                continue
            g = max(0, int(math.ceil(float(min_mm))))
            add_bbox_minimum_gap(
                solver,
                mod_a.z3_x,
                mod_a.z3_y,
                _ceil_mm(mod_a.width),
                _ceil_mm(mod_a.height),
                mod_b.z3_x,
                mod_b.z3_y,
                _ceil_mm(mod_b.width),
                _ceil_mm(mod_b.height),
                g,
            )
        elif typ == 'distance_max':
            mod_a, mod_b, max_mm = args
            if id(mod_a) not in z3_ids or id(mod_b) not in z3_ids:
                continue
            max_sum = max(0, int(math.ceil(float(max_mm))))
            add_center_l1_max(
                solver,
                mod_a.z3_x,
                mod_a.z3_y,
                _ceil_mm(mod_a.width),
                _ceil_mm(mod_a.height),
                mod_b.z3_x,
                mod_b.z3_y,
                _ceil_mm(mod_b.width),
                _ceil_mm(mod_b.height),
                max_sum,
            )
        elif typ == 'edge':
            mod, edge = args
            if id(mod) not in z3_ids:
                continue
            if edge == 'TOP':
                solver.add(mod.z3_y == 0)
            elif edge == 'BOTTOM':
                solver.add(mod.z3_y + _ceil_mm(mod.height) == board.size_mm[1])
            elif edge == 'LEFT':
                solver.add(mod.z3_x == 0)
            elif edge == 'RIGHT':
                solver.add(mod.z3_x + _ceil_mm(mod.width) == board.size_mm[0])
        elif typ == 'exact_center':
            item = args[0]
            if id(item) not in z3_ids:
                continue
            # (x + w/2) == board_w/2  =>  2x + w == board_w
            solver.add(2 * item.z3_x + _ceil_mm(item.width) == int(board.size_mm[0]))
            solver.add(2 * item.z3_y + _ceil_mm(item.height) == int(board.size_mm[1]))

    if compact:
        max_r = Int("openhac_used_r")
        max_b = Int("openhac_used_b")
        solver.add(max_r >= 0)
        solver.add(max_b >= 0)
        for mod in all_mods:
            solver.add(max_r >= mod.z3_x + _ceil_mm(mod.width))
            solver.add(max_b >= mod.z3_y + _ceil_mm(mod.height))
        try:
            solver.minimize(max_r + max_b)
        except Exception as e:
            logger.debug("Z3 minimize skipped: %s", e)

    result = solver.check()
    model = None
    if result == sat:
        model = solver.model()
    elif compact:
        try:
            model = solver.model()
        except Exception:
            model = None
        if model is not None:
            logger.warning("Z3 compact returned %s; trying affinity pack instead of a slack SAT model.", result)
            try:
                from openhac.compiler.placement_engine import apply_affinity_floorplan

                if apply_affinity_floorplan(board):
                    try:
                        from openhac.compiler.cluster_affinity import apply_satellite_offsets_after_z3

                        apply_satellite_offsets_after_z3(board)
                    except Exception:
                        pass
                    try:
                        _shrink_board_to_placed_aabb(board)
                    except Exception:
                        pass
                    return True
            except Exception as e:
                logger.debug("affinity fallback after Z3 unknown skipped: %s", e)
            logger.warning("Z3 compact returned %s; using feasible model (may be sub-optimal).", result)
    if model is not None:
        logger.info("Z3 SAT: packed module coordinates (compact=%s):", compact)
        for mod in all_mods:
            mod.placed_x = model[mod.z3_x].as_long()
            mod.placed_y = model[mod.z3_y].as_long()
            logger.info(f"  - {mod.name}: ({mod.placed_x}, {mod.placed_y}) [w:{mod.width}, h:{mod.height}]")
        try:
            from openhac.compiler.cluster_affinity import apply_satellite_offsets_after_z3

            apply_satellite_offsets_after_z3(board)
        except Exception as e:
            logger.debug("satellite offset apply skipped: %s", e)
        try:
            _shrink_board_to_placed_aabb(board)
        except Exception as e:
            logger.debug("outline crop skipped: %s", e)
        return True
    else:
        reason = str(result)
        logger.error("Z3 %s! Spatial constraints not satisfied.", reason)

        # Extract unsatisfiable core if available
        try:
            unsat_core = solver.unsat_core()
            if unsat_core:
                logger.error("Unsatisfiable core (failing constraints):")
                for constraint in unsat_core:
                    logger.error(f"  - {constraint}")
        except Exception as e:
            logger.debug(f"Could not extract unsat_core: {e}")

        # Check if board is too small
        board_area = board.size_mm[0] * board.size_mm[1]
        total_mod_area = sum(m.width * m.height for m in all_mods)
        if total_mod_area > board_area * 0.7:  # 70% utilization threshold
            suggested_w = (total_mod_area * 1.5) ** 0.5 * 1.2
            suggested_h = (total_mod_area * 1.5) ** 0.5
            logger.error(f"Board appears too small: {total_mod_area:.1f} mm² components in {board_area:.1f} mm² board")
            logger.error(f"Suggested board size: ~{suggested_w:.0f} x {suggested_h:.0f} mm")

        raise LayoutGenerationError(
            f"Layout constraints unsatisfiable ({reason}): {len(all_mods)} modules in "
            f"{board.size_mm[0]}x{board.size_mm[1]}mm board. "
            f"Component area: {total_mod_area:.1f} mm², Board area: {board_area:.1f} mm². "
            f"Try increasing board size or relaxing constraints."
        )

def solve_placement_with_relaxation(board, max_relaxations: int = 2) -> bool:
    """Attempt layout with automatic constraint relaxation on failure.

    Retries with progressively relaxed distance constraints (20% reduction per attempt)
    to handle overly aggressive user constraints.
    """
    # Store original constraints for restoration.
    # NOTE: board.constraints contains Module objects; deepcopy can recurse via Component.__getattr__.
    original_constraints = [dict(r) for r in (board.constraints or [])]

    for attempt in range(max_relaxations + 1):
        if attempt > 0:
            logger.warning(f"Layout attempt {attempt} failed, relaxing distance constraints by 20%...")
            # Relax distance constraints
            for rule in board.constraints:
                if rule['type'] in ('distance_min', 'distance_max'):
                    args = list(rule['args'])
                    args[2] = args[2] * 0.8  # Reduce distance requirement by 20%
                    rule['args'] = tuple(args)

        try:
            result = solve_placement(board)
            if result:
                if attempt > 0:
                    logger.info(f"Layout succeeded after {attempt} relaxation(s)")
                return True
        except LayoutGenerationError:
            if attempt == max_relaxations:
                # Restore original constraints before final raise
                board.constraints = original_constraints
                raise
            # Continue to next relaxation attempt

    # Restore original constraints
    board.constraints = original_constraints
    return False


def assert_footprint_pin_pad_or_raise(board) -> None:
    """Raise :class:`LayoutGenerationError` if strict PCB-002 checks find pad↔pin mismatches.

    Strict mode is enabled by :attr:`Board.strict_footprint_pin_pad_match`,
    ``OPENHAC_STRICT_FOOTPRINT_PIN_PAD=1``, or ``compile_goal=fabrication`` (FAB-002).
    Uses :func:`openhac.compiler.pcb_placement.pin_pad_coverage_warnings_for_board`
    so the check matches **OpenHaC board modules** (not only SKiDL's default circuit).
    """
    import os

    strict = bool(getattr(board, "strict_footprint_pin_pad_match", False))
    if not strict:
        strict = os.environ.get("OPENHAC_STRICT_FOOTPRINT_PIN_PAD", "").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
    if not strict:
        try:
            goal = str(getattr(board, "effective_compile_goal", lambda: "")()).strip().lower()
        except Exception:
            goal = (os.environ.get("OPENHAC_COMPILE_GOAL") or "").strip().lower()
        if goal == "fabrication":
            strict = True
    if not strict:
        return
    from openhac.compiler.pcb_placement import pin_pad_coverage_warnings_for_board

    msgs = pin_pad_coverage_warnings_for_board(board)
    if msgs:
        hint = ""
        try:
            from openhac.database.catalog_overlay import pcb002_failure_hint

            hint = "\n\n" + pcb002_failure_hint()
        except Exception:
            pass
        raise LayoutGenerationError(
            "PCB-002 strict footprint pin↔pad check failed:\n" + "\n".join(msgs) + hint
        )


def _enlarge_board_once(board, factor: float = 1.25) -> None:
    w, h = board.size_mm
    nw = float(math.ceil(float(w) * factor))
    nh = float(math.ceil(float(h) * factor))
    board.size_mm = (nw, nh)
    try:
        board._size_mm_unspecified = False
    except Exception:
        pass
    logger.warning("Enlarge-on-UNSAT: board resized to %.0fx%.0f mm (×%.2f).", nw, nh, factor)


def _hard_fail_unsat(board) -> bool:
    """Whether UNSAT should raise after enlarge/fallback attempts."""
    v = (os.environ.get("OPENHAC_LAYOUT_HARD_FAIL_UNSAT") or "").strip().lower()
    if v in ("1", "true", "yes", "on"):
        return True
    if v in ("0", "false", "no", "off"):
        return False
    try:
        goal = str(getattr(board, "effective_compile_goal", lambda: "")()).strip().lower()
    except Exception:
        goal = (os.environ.get("OPENHAC_COMPILE_GOAL") or "").strip().lower()
    return goal == "fabrication"


def generate_layout(netlist_path: str, output_pcb_path: str, board):
    size_mm = board.size_mm
    logger.info(f"Generating physical layout for {netlist_path} -> {output_pcb_path}")

    assert_footprint_pin_pad_or_raise(board)

    overlay = getattr(board, "_kicad_artwork_overlay", None)
    skip_z3 = False
    try:
        from openhac.compiler.kicad_artwork import overlay_covers_all_footprints

        skip_z3 = overlay_covers_all_footprints(overlay, board)
    except Exception:
        skip_z3 = False

    placed = False
    if skip_z3:
        logger.info("LIVE-003: skipping Z3; all footprints have overlay coordinates.")
        placed = True
    else:
        try:
            placed = bool(solve_placement_with_relaxation(board, max_relaxations=2))
        except LayoutGenerationError as e:
            enlarge = (os.environ.get("OPENHAC_LAYOUT_ENLARGE_ON_UNSAT") or "1").strip().lower() not in (
                "0",
                "false",
                "no",
                "off",
            )
            if enlarge:
                try:
                    factor = float(os.environ.get("OPENHAC_LAYOUT_ENLARGE_FACTOR") or "1.25")
                except Exception:
                    factor = 1.25
                factor = min(max(factor, 1.05), 2.0)
                _enlarge_board_once(board, factor=factor)
                size_mm = board.size_mm
                try:
                    placed = bool(solve_placement_with_relaxation(board, max_relaxations=1))
                except LayoutGenerationError as e2:
                    e = e2
                    placed = False
            if not placed:
                if _hard_fail_unsat(board):
                    raise LayoutGenerationError(
                        f"{e} (hard-fail after enlarge; set OPENHAC_LAYOUT_HARD_FAIL_UNSAT=0 for grid fallback)"
                    ) from e
                logger.warning(
                    "Layout UNSAT after enlarge; using grid fallback (never pile at 5,5). Original: %s",
                    e,
                )
                from openhac.compiler.cluster_affinity import apply_grid_fallback_placement

                apply_grid_fallback_placement(board)
                placed = True

    if not placed:
        logger.warning("Z3 unavailable or empty; using grid fallback placement.")
        from openhac.compiler.cluster_affinity import apply_grid_fallback_placement

        apply_grid_fallback_placement(board)
    
    try:
        import pcbnew
        pcb = pcbnew.BOARD()
        try:
            from openhac.compiler.pcb_postprocess import enable_copper_layers

            enable_copper_layers(pcb, pcbnew, int(getattr(board, "layers", 2) or 2))
        except Exception as e:
            logger.warning("PCB-003: could not enable inner copper layers: %s", e)
        
        edge_cuts = pcb.GetLayerID('Edge.Cuts')
        
        def to_vec(x_mm, y_mm):
            """Cross-version helper for VECTOR2I (v7/v8) or wxPoint (v6)."""
            x = int(pcbnew.FromMM(x_mm))
            y = int(pcbnew.FromMM(y_mm))
            try:
                return pcbnew.VECTOR2I(x, y)
            except AttributeError:
                return pcbnew.wxPoint(x, y)

        w, h = board.size_mm
        pts = [to_vec(0, 0), to_vec(w, 0), to_vec(w, h), to_vec(0, h)]
        
        for i in range(4):
            seg = pcbnew.PCB_SHAPE(pcb)
            seg.SetShape(pcbnew.SHAPE_T_SEGMENT)
            seg.SetStart(pts[i])
            seg.SetEnd(pts[(i+1)%4])
            seg.SetLayer(edge_cuts)
            seg.SetWidth(int(pcbnew.FromMM(0.1)))
            pcb.Add(seg)

        from openhac.compiler.pcb_placement import place_circuit_on_board

        place_circuit_on_board(pcb, board, pcbnew)

        # Stretch: emit copper pours + mounting holes when declared on the Board.
        try:
            from openhac.compiler.pcb_physics import apply_physics_net_classes

            try:
                apply_physics_net_classes(pcb, board, pcbnew)
            except Exception as e:
                try:
                    goal = str(getattr(board, "effective_compile_goal", lambda: "")()).strip().lower()
                except Exception:
                    goal = (os.environ.get("OPENHAC_COMPILE_GOAL") or "").strip().lower()
                if goal in ("fabrication", "fab"):
                    raise
                logger.warning("apply_physics_net_classes failed (continuing): %s", e)
            from openhac.compiler.pcb_postprocess import (
                apply_copper_pour_intents,
                apply_keepout_rect_intents,
                apply_mounting_hole_intents,
                apply_net_tie_intents,
                legalize_placed_footprints,
                sync_duplicate_pad_nets,
            )
            sync_duplicate_pad_nets(pcb, pcbnew)
            apply_keepout_rect_intents(pcb, board, pcbnew)
            apply_net_tie_intents(pcb, board, pcbnew)
            # Min-displacement courtyard separate, then shrink-wrap Edge.Cuts.
            # Do not clamp into a too-small outline while parts still overlap.
            try:
                gap_mm = float(os.environ.get("OPENHAC_PLACEMENT_FP_GAP_MM", "").strip() or 0.5)
            except Exception:
                gap_mm = 0.5
            margin_mm = float(getattr(board, "bbox_padding_mm", 0.5) or 0.5)
            try:
                edge_margin = float(os.environ.get("OPENHAC_AUTO_BOARD_MIN_EDGE_MARGIN_MM") or "4")
            except Exception:
                edge_margin = 4.0
            legalize_placed_footprints(
                pcb,
                pcbnew,
                board,
                gap_mm=max(0.4, gap_mm),
                margin_mm=max(margin_mm, min(edge_margin, 4.0)),
                frozen_refs=set((getattr(overlay, "footprints", None) or {})),
            )
            apply_mounting_hole_intents(pcb, board, pcbnew)
            # ABC-002: defer pours until after FreeRouting when requested so plane nets
            # get tracks (FreeRouting often skips nets that already have copper zones).
            defer_pours = (os.environ.get("OPENHAC_DEFER_COPPER_POURS") or "").strip().lower() in (
                "1",
                "true",
                "yes",
                "on",
            )
            if not defer_pours:
                apply_copper_pour_intents(pcb, board, pcbnew)
            else:
                logger.info("ABC-002: deferring copper pour intents until after autoroute.")
            # Do not clamp-to-outline after legalize: silk-inflated bboxes would
            # shove parts back together (the failure mode of the old de-overlap).
        except Exception as e:
            logger.warning("PCB post-process helpers failed (continuing): %s", e)

        pcbnew.SaveBoard(output_pcb_path, pcb)
        try:
            from openhac.compiler.kicad_artwork import graph_net_names_from_board, splice_pcb_artwork_file

            splice_pcb_artwork_file(output_pcb_path, overlay, graph_net_names_from_board(board))
        except Exception as e:
            logger.warning("LIVE-004: PCB copper overlay splice failed (continuing): %s", e)
        try:
            from openhac.compiler.fab_design_settings import fill_copper_zones_file

            fill_copper_zones_file(str(output_pcb_path))
        except Exception as e:
            logger.debug("ABC-002 post-save zone fill: %s", e)
        try:
            from openhac.compiler.pcb_postprocess import inject_kicad_stackup
            inject_kicad_stackup(output_pcb_path, board.layers)
        except Exception as e:
            logger.warning("Failed to inject physical stackup (PCB-003): %s", e)
            
        logger.info("Board outline and footprints generated successfully.")
        return pcb
    except Exception as e:
        logger.error(f"KiCad PCBNew API failed or unavailable: {e}")
        raise LayoutGenerationError(
            "Could not generate KiCad PCB (pcbnew unavailable or failed). "
            "Install KiCad with Python bindings and ensure KICAD_*_SYMBOL_DIR / fp tables are set."
        ) from e
