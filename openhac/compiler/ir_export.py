"""Hardware Intermediate Representation (IR) Exporter.

This module serializes the compiled OpenHaC hardware graph into a strict JSON 
schema (the IR). This decouples the Python frontend from backend layout engines.
"""

import json
from pathlib import Path
from typing import Any

from openhac.core.board import Board
import openhac.core.circuit


def _serialize_part(part: Any) -> dict[str, Any]:
    """Serialize a single SKiDL-like Part into the IR schema."""
    pins_data = []
    
    # Extract pins safely
    pins = getattr(part, "get_pins", lambda: [])()
    if not pins and hasattr(part, "pins"):
        pins_raw = part.pins
        if isinstance(pins_raw, dict):
            # deduplicate by ID in case they are mapped by name and number
            seen = set()
            for p in pins_raw.values():
                if id(p) not in seen:
                    pins.append(p)
                    seen.add(id(p))
        elif isinstance(pins_raw, list):
            pins = pins_raw
            
    for pin in pins:
        net = getattr(pin, "net", None)
        pins_data.append({
            "number": str(getattr(pin, "num", getattr(pin, "number", "?"))),
            "name": str(getattr(pin, "name", "?")),
            "type": str(getattr(pin, "pin_type", getattr(pin, "func", "passive"))),
            "net": str(getattr(net, "name", "NC")) if net else "NC",
            "logic_level": getattr(pin, "logic_level", None),
            "voltage_rating": getattr(pin, "voltage_rating", None),
            "current_limit": getattr(pin, "current_limit", None)
        })
        
    return {
        "refdes": getattr(part, "refdes", getattr(part, "ref", "?")),
        "footprint": getattr(part, "footprint", ""),
        "value": getattr(part, "value", ""),
        "fields": getattr(part, "fields", {}),
        "pins": pins_data
    }


def export_hardware_ir(board: Board, output_path: str | Path | None = None) -> str:
    """Export the compiled hardware graph to a JSON Intermediate Representation (IR).
    
    Args:
        board: The compiled Board object.
        output_path: Optional path to write the JSON file.
        
    Returns:
        The JSON string representation of the hardware.
    """
    circuit = openhac.core.circuit.default_circuit
    
    # 1. Gather all components
    components_ir = []
    
    # Try global SKiDL circuit first
    parts = getattr(circuit, "parts", [])
    if parts:
        for p in parts:
            components_ir.append(_serialize_part(p))
    else:
        # Fallback to native module tree (useful for testing or bypassed compilers)
        all_mods = board._get_all_modules() if hasattr(board, "_get_all_modules") else getattr(board, "modules", [])
        for mod in all_mods:
            for item in getattr(mod, "components", []):
                # Only serialize actual parts, skip nested modules
                from openhac.core.base import Module
                if not isinstance(item, Module):
                    components_ir.append(_serialize_part(item))
        
    # 2. Gather all nets
    nets_ir = []
    nets = getattr(circuit, "nets", [])
    for n in nets:
        net_name = str(getattr(n, "name", "Unnamed"))
        pins = getattr(n, "pins", [])
        pin_refs = []
        for pin in pins:
            ref = getattr(pin.part, "refdes", getattr(pin.part, "ref", "?")) if hasattr(pin, "part") else "?"
            num = getattr(pin, "num", getattr(pin, "number", "?"))
            pin_refs.append(f"{ref}.{num}")
            
        nets_ir.append({
            "name": net_name,
            "pins": pin_refs
        })
        
    # 3. Gather board constraints
    constraints_ir = {
        "size_mm": board.size_mm,
        "layers": board.layers,
        "board_class": board.board_class,
        "fab_profile": board.fab_profile,
        "quality_gates": board.quality_gates,
        "keepouts": board._keepout_rect_intents,
        "net_roles": board._net_roles,
    }
    
    # 4. Construct final IR envelope
    ir_envelope = {
        "schema_version": "1.0",
        "project": {
            "name": getattr(board, "project_name", "OpenHaC_Board"),
            "constraints": constraints_ir
        },
        "components": components_ir,
        "nets": nets_ir
    }
    
    json_data = json.dumps(ir_envelope, indent=2)
    
    if output_path:
        out_path = Path(output_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json_data, encoding="utf-8")
        
    return json_data
