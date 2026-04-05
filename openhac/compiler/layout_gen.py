import logging
import math

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
        
    solver = Solver()
    all_mods = getattr(board, 'all_modules', board.modules)
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
            no_overlap = Or(
                a.z3_x + int(a.width) <= b.z3_x,
                b.z3_x + int(b.width) <= a.z3_x,
                a.z3_y + int(a.height) <= b.z3_y,
                b.z3_y + int(b.height) <= a.z3_y
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

    if solver.check() == sat:
        logger.info("Z3 SAT (Satisfiable)! Optimal layout mathematical coordinates found:")
        model = solver.model()
        for mod in all_mods:
            mod.placed_x = model[mod.z3_x].as_long()
            mod.placed_y = model[mod.z3_y].as_long()
            logger.info(f"  - {mod.name}: ({mod.placed_x}, {mod.placed_y}) [w:{mod.width}, h:{mod.height}]")
        return True
    else:
        logger.error("Z3 UNSAT! Spatial Constraints cannot be mathematically satisfied.")
        return False

def assert_footprint_pin_pad_or_raise(board) -> None:
    """Raise :class:`LayoutGenerationError` if strict PCB-002 checks find pad↔pin mismatches."""
    if not getattr(board, "strict_footprint_pin_pad_match", False):
        return
    from openhac.circuit import get_default_circuit
    from openhac.compiler.pcb_placement import pin_pad_coverage_warnings

    try:
        circuit = get_default_circuit()
    except RuntimeError:
        return
    msgs = pin_pad_coverage_warnings(circuit)
    if msgs:
        raise LayoutGenerationError(
            "PCB-002 strict footprint pin↔pad check failed:\n" + "\n".join(msgs)
        )


def generate_layout(netlist_path: str, output_pcb_path: str, board):
    size_mm = board.size_mm
    logger.info(f"Generating physical layout for {netlist_path} -> {output_pcb_path}")

    assert_footprint_pin_pad_or_raise(board)

    if not solve_placement(board):
        logger.warning("Falling back to unoptimized geometry due to UNSAT.")
    
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

        pcbnew.SaveBoard(output_pcb_path, pcb)
        logger.info("Board outline and footprints generated successfully.")
    except Exception as e:
        logger.error(f"KiCad PCBNew API failed or unavailable: {e}")
        raise LayoutGenerationError(
            "Could not generate KiCad PCB (pcbnew unavailable or failed). "
            "Install KiCad with Python bindings and ensure KICAD_*_SYMBOL_DIR / fp tables are set."
        ) from e
