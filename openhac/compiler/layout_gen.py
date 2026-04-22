import logging
import math
import os

from openhac.compiler.layout_constraints import add_bbox_minimum_gap, add_center_l1_max
from openhac.core.base import LayoutGenerationError

logger = logging.getLogger("openhac.layout")

def solve_placement(board):
    logger.info("Running Z3 SMT Spatial Solver...")
    try:
        from z3 import Solver, Int, sat, Or, And
    except ImportError:
        logger.warning("Z3 solver not installed. Skipping algorithmic placement.")
        return False

    all_mods = getattr(board, 'all_modules', board.modules)

    # Debug: Log layout problem details
    logger.info("Layout problem:")
    logger.info(f"  Board: {board.size_mm[0]} x {board.size_mm[1]} mm ({board.layers} layers)")
    logger.info(f"  Modules: {len(all_mods)}")
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
    if g_mm <= 0:
        ev = (os.environ.get("OPENHAC_MODULE_CLEARANCE_MM") or "").strip()
        if ev:
            try:
                g_mm = float(ev)
            except Exception:
                g_mm = 0.0
    g_int = max(0, int(math.ceil(g_mm)))
    if g_mm > 0:
        logger.info("  Z3 module bbox clearance target: >= %s mm (edge-to-edge, int %s)", g_mm, g_int)

    solver = Solver()
    # 1. Bounds Constraints
    for mod in all_mods:
        mod.z3_x = Int(f"{mod.name}_x")
        mod.z3_y = Int(f"{mod.name}_y")
        
        solver.add(mod.z3_x >= 0)
        solver.add(mod.z3_y >= 0)
        solver.add(mod.z3_x + int(mod.width) <= board.size_mm[0])
        solver.add(mod.z3_y + int(mod.height) <= board.size_mm[1])
        
    # 2. Non-overlapping constraints (all logical modules, including nested)
    n = len(all_mods)
    for i in range(n):
        for j in range(i + 1, n):
            a = all_mods[i]
            b = all_mods[j]
            if g_int > 0:
                add_bbox_minimum_gap(
                    solver,
                    a.z3_x,
                    a.z3_y,
                    int(a.width),
                    int(a.height),
                    b.z3_x,
                    b.z3_y,
                    int(b.width),
                    int(b.height),
                    g_int,
                )
            else:
                no_overlap = Or(
                    a.z3_x + int(a.width) <= b.z3_x,
                    b.z3_x + int(b.width) <= a.z3_x,
                    a.z3_y + int(a.height) <= b.z3_y,
                    b.z3_y + int(b.height) <= a.z3_y,
                )
                solver.add(no_overlap)
            
    # 3. User Defined Constraints
    for rule in board.constraints:
        typ = rule['type']
        args = rule['args']
        if typ == 'distance_min':
            mod_a, mod_b, min_mm = args
            g = max(0, int(math.ceil(float(min_mm))))
            add_bbox_minimum_gap(
                solver,
                mod_a.z3_x,
                mod_a.z3_y,
                int(mod_a.width),
                int(mod_a.height),
                mod_b.z3_x,
                mod_b.z3_y,
                int(mod_b.width),
                int(mod_b.height),
                g,
            )
        elif typ == 'distance_max':
            mod_a, mod_b, max_mm = args
            max_sum = max(0, int(math.ceil(float(max_mm))))
            add_center_l1_max(
                solver,
                mod_a.z3_x,
                mod_a.z3_y,
                int(mod_a.width),
                int(mod_a.height),
                mod_b.z3_x,
                mod_b.z3_y,
                int(mod_b.width),
                int(mod_b.height),
                max_sum,
            )
        elif typ == 'edge':
            mod, edge = args
            if edge == 'TOP':
                solver.add(mod.z3_y == 0)
            elif edge == 'BOTTOM':
                solver.add(mod.z3_y + int(mod.height) == board.size_mm[1])
            elif edge == 'LEFT':
                solver.add(mod.z3_x == 0)
            elif edge == 'RIGHT':
                solver.add(mod.z3_x + int(mod.width) == board.size_mm[0])
        elif typ == 'exact_center':
            item = args[0]
            # (x + w/2) == board_w/2  =>  2x + w == board_w
            solver.add(2 * item.z3_x + int(item.width) == int(board.size_mm[0]))
            solver.add(2 * item.z3_y + int(item.height) == int(board.size_mm[1]))

    result = solver.check()
    if result == sat:
        logger.info("Z3 SAT (Satisfiable)! Optimal layout mathematical coordinates found:")
        model = solver.model()
        for mod in all_mods:
            mod.placed_x = model[mod.z3_x].as_long()
            mod.placed_y = model[mod.z3_y].as_long()
            logger.info(f"  - {mod.name}: ({mod.placed_x}, {mod.placed_y}) [w:{mod.width}, h:{mod.height}]")
        return True
    else:
        logger.error("Z3 UNSAT! Spatial Constraints cannot be mathematically satisfied.")

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
            f"Layout constraints unsatisfiable: {len(all_mods)} modules in {board.size_mm[0]}x{board.size_mm[1]}mm board. "
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

    Strict mode is enabled by :attr:`Board.strict_footprint_pin_pad_match` or
    ``OPENHAC_STRICT_FOOTPRINT_PIN_PAD=1``. Uses :func:`openhac.compiler.pcb_placement.pin_pad_coverage_warnings_for_board`
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


def generate_layout(netlist_path: str, output_pcb_path: str, board):
    size_mm = board.size_mm
    logger.info(f"Generating physical layout for {netlist_path} -> {output_pcb_path}")

    assert_footprint_pin_pad_or_raise(board)

    try:
        if not solve_placement_with_relaxation(board, max_relaxations=2):
            logger.warning("Falling back to unoptimized geometry due to UNSAT.")
    except LayoutGenerationError:
        logger.warning("Layout constraint satisfaction failed even with relaxation, proceeding with unoptimized placement")
    
    try:
        import pcbnew
        pcb = pcbnew.BOARD()
        
        edge_cuts = pcb.GetLayerID('Edge.Cuts')
        
        def to_vec(x_mm, y_mm):
            """Cross-version helper for VECTOR2I (v7/v8) or wxPoint (v6)."""
            x = int(pcbnew.FromMM(x_mm))
            y = int(pcbnew.FromMM(y_mm))
            try:
                return pcbnew.VECTOR2I(x, y)
            except AttributeError:
                return pcbnew.wxPoint(x, y)

        w, h = size_mm
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
            from openhac.compiler.pcb_postprocess import (
                apply_copper_pour_intents,
                apply_keepout_rect_intents,
                clamp_footprints_inside_edge_cuts,
                apply_mounting_hole_intents,
                apply_net_tie_intents,
                spread_footprints_no_overlap,
            )

            apply_keepout_rect_intents(pcb, board, pcbnew)
            apply_net_tie_intents(pcb, board, pcbnew)
            apply_mounting_hole_intents(pcb, board, pcbnew)
            apply_copper_pour_intents(pcb, board, pcbnew)
            margin_mm = float(getattr(board, "bbox_padding_mm", 0.5) or 0.0)
            max_iters = int(getattr(board, "deoverlap_max_iters", 200) or 200)
            step_mm = float(getattr(board, "deoverlap_step_mm", 0.75) or 0.75)
            clamp_footprints_inside_edge_cuts(pcb, pcbnew, margin_mm=margin_mm)
            # Best-effort de-overlap for handoff/dev readability (repeat passes help dense boards).
            try:
                deo_passes = int((os.environ.get("OPENHAC_DEOVERLAP_PASSES") or "1").strip() or 1)
            except Exception:
                deo_passes = 1
            deo_passes = max(1, min(deo_passes, 20))
            for _ in range(deo_passes):
                spread_footprints_no_overlap(pcb, pcbnew, max_iters=max_iters, step_mm=step_mm, margin_mm=margin_mm)
            try:
                from openhac.compiler.pcb_fit import count_footprint_bbox_overlap_pairs

                n_ovl = count_footprint_bbox_overlap_pairs(pcb, pcbnew, clearance_mm=margin_mm)
                if n_ovl > 0:
                    logger.warning(
                        "After de-overlap: %s approximate footprint bbox overlap pair(s) remain "
                        "(bbox-based; increase --deoverlap-iters / --deoverlap-step-mm or fix placement).",
                        n_ovl,
                    )
            except Exception:
                pass
        except Exception as e:
            logger.warning("PCB post-process helpers failed (continuing): %s", e)

        pcbnew.SaveBoard(output_pcb_path, pcb)
        logger.info("Board outline and footprints generated successfully.")
    except Exception as e:
        logger.error(f"KiCad PCBNew API failed or unavailable: {e}")
        raise LayoutGenerationError(
            "Could not generate KiCad PCB (pcbnew unavailable or failed). "
            "Install KiCad with Python bindings and ensure KICAD_*_SYMBOL_DIR / fp tables are set."
        ) from e
