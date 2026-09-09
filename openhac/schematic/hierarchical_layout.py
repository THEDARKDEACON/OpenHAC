"""Subsystem-Driven Hierarchical Multi-Sheet Schematics (Idea 1).

Transforms OpenHaC schematic generation from flat part-count chunking into
true architectural multi-sheet KiCad 8/9 schematics driven by subsystem Module trees
and CircuitIR interface bindings.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from openhac.ir.circuit_ir import CircuitIR
from openhac.schematic.emit_kicad import generate_schematic
from openhac.schematic.ir import HierPin, SchematicIR, SheetBox

logger = logging.getLogger("openhac.schematic.hierarchical")


def generate_hierarchical_schematic(
    output_path: str,
    board: Any = None,
    *,
    circuit: Any = None,
    circuit_ir: Optional[CircuitIR] = None,
    project_name: Optional[str] = None,
    signoff: bool = False,
    symbol_resolver: Any = None,
    pinpos_report_path: Optional[str] = None,
    generated_symbol_lib_path: Optional[str] = None,
    embedded_lib_symbols: Optional[str] = None,
) -> SchematicIR:
    """Generate a KiCad 8/9 hierarchical multi-sheet schematic driven by subsystem modules.

    Creates a top-level architectural diagram on the root sheet with (sheet ...) blocks
    representing each child subsystem module, with typed pins (inputs on the left, outputs
    on the right) and inter-sheet net labels. Emits individual child sheets containing
    the components and hierarchical labels for each subsystem.

    Args:
        output_path: Target root .kicad_sch file path.
        board: Optional Board container with modules.
        circuit: Optional Circuit instance with parts/nets.
        circuit_ir: Optional frozen CircuitIR module tree.
        project_name: Design title for KiCad project files.
        signoff: If True, enforces strict DRC/ERC pinout sign-off.
        symbol_resolver: Custom pin position resolver.
        pinpos_report_path: Output JSON diagnostics report path.
        generated_symbol_lib_path: Project symbol library path.
        embedded_lib_symbols: S-expression symbol definitions.

    Returns:
        Root SchematicIR with populated child_sheets and sheet boxes.
    """
    if board is None and circuit_ir is not None:
        class _BoardProxy:
            project_name = circuit_ir.name
            release_tag = "v1.0"
            modules: list = []
            hierarchical_schematic = True

        board = _BoardProxy()
    elif board is not None:
        board.hierarchical_schematic = True

    return generate_schematic(
        output_path,
        board,
        circuit=circuit,
        circuit_ir=circuit_ir,
        project_name=project_name,
        signoff=signoff,
        symbol_resolver=symbol_resolver,
        pinpos_report_path=pinpos_report_path,
        generated_symbol_lib_path=generated_symbol_lib_path,
        embedded_lib_symbols=embedded_lib_symbols,
        hierarchical=True,
    )


def summarize_hierarchical_schematic(ir: SchematicIR) -> Dict[str, Any]:
    """Inspect and summarize a hierarchical schematic IR."""
    sheets_info = []
    for sh in ir.sheets:
        pins_info = [
            {
                "name": hp.name,
                "type": hp.pin_type,
                "rot": hp.rot,
                "x": hp.x,
                "y": hp.y,
            }
            for hp in sh.pins
        ]
        sheets_info.append({
            "name": sh.name,
            "filename": sh.filename,
            "uuid": sh.uuid,
            "x": sh.x,
            "y": sh.y,
            "w": sh.w,
            "h": sh.h,
            "pin_count": len(sh.pins),
            "pins": pins_info,
        })

    child_info = {}
    for name, child in ir.child_sheets.items():
        hier_labels = [lb.name for lb in child.labels if lb.kind == "hierarchical"]
        child_info[name] = {
            "title": child.title,
            "paper": child.paper,
            "instance_count": len(child.instances),
            "instances": [inst.ref for inst in child.instances],
            "hierarchical_labels": hier_labels,
            "wire_count": len(child.wires),
            "power_port_count": len(child.power_ports),
            "no_connect_count": len(child.no_connects),
        }

    return {
        "title": ir.title,
        "paper": ir.paper,
        "root_instance_count": len(ir.instances),
        "root_instances": [inst.ref for inst in ir.instances],
        "subsystem_sheet_count": len(ir.sheets),
        "sheets": sheets_info,
        "child_sheets": child_info,
        "root_wire_count": len(getattr(ir, "root_wires", []) or []),
        "root_label_count": len(getattr(ir, "root_labels", []) or []),
    }
