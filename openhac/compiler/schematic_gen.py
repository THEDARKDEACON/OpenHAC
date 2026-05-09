from __future__ import annotations

import json
import os
from pathlib import Path
import logging
import re
import uuid
from dataclasses import dataclass
from typing import Protocol

from openhac.circuit import get_default_circuit
from openhac.compiler.kicad_sym_pinpos import (
    EmptySymbolPinResolver,
    SymbolPinResolver,
    part_library_name,
)
from openhac.core.base import SchematicGenerationError

logger = logging.getLogger("openhac.schematic")

# `(wire (pts (xy x1 y1) (xy x2 y2))` as emitted by OpenHaC (SCH-001 parse helpers).
_WIRE_PTS_RE = re.compile(
    r"\(wire\s+\(pts\s+\(xy\s+([-\d.]+)\s+([-\d.]+)\)\s+\(xy\s+([-\d.]+)\s+([-\d.]+)\)\)",
    re.MULTILINE,
)
# `(label "..." (at x y 0)` — capture group is escaped KiCad string content.
_LABEL_AT_RE = re.compile(
    r'\(label\s+"((?:[^"\\]|\\.)*)"\s+\(at\s+([-\d.]+)\s+([-\d.]+)',
    re.MULTILINE,
)

def _truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def _det_uuid(key: str) -> str:
    """Deterministic UUID string for stable artifact generation (MFG-ish stretch).

    Uses uuid5 so identical inputs yield identical UUIDs across runs.
    """
    return str(uuid.uuid5(uuid.NAMESPACE_OID, f"openhac:{key}"))


def _uuid_for(key: str) -> str:
    if (
        _truthy_env("OPENHAC_DETERMINISTIC_UUIDS")
        or _truthy_env("OPENHAC_DETERMINISTIC_SCHEMATIC")
        or _truthy_env("OPENHAC_DETERMINISTIC")
    ):
        return _det_uuid(key)
    return str(uuid.uuid4())


class SchematicPinResolver(Protocol):
    def offset_for_pin(self, part, pin) -> tuple[float, float] | None: ...


@dataclass
class PartPlacement:
    part: object
    x: float
    y: float
    uuid: str


def _schematic_layout_params() -> tuple[int, float]:
    """Columns per row and cell spacing (KiCad units) for schematic symbol placement.

    Override with ``OPENHAC_SCHEMATIC_COLS_PER_ROW`` and ``OPENHAC_SCHEMATIC_CELL_SPACING``.
    Defaults are wider than the old 10×10 grid to reduce overlapping symbol bounding boxes.
    """
    try:
        cols = int(os.environ.get("OPENHAC_SCHEMATIC_COLS_PER_ROW", "").strip() or 8)
    except Exception:
        cols = 8
    try:
        spacing = float(os.environ.get("OPENHAC_SCHEMATIC_CELL_SPACING", "").strip() or 16.0)
    except Exception:
        spacing = 16.0
    return max(1, cols), max(1.0, spacing)


def schematic_symbol_lib_key(part) -> str:
    """Symbol name used in generated ``.kicad_sch`` / ``lib_id`` ``OpenHaC:<key>`` (must match ``.kicad_sym``)."""
    name = (getattr(part, "name", None) or "").strip()
    ref = (getattr(part, "ref", None) or "").strip()
    if name and name != "?":
        return name
    if ref and ref != "?":
        return ref
    return "PART"


def _assign_grid_positions(parts) -> dict:
    """Row-major grid assignment; spacing/columns from :func:`_schematic_layout_params`."""
    cols, cell = _schematic_layout_params()
    positions = {}
    for idx, part in enumerate(parts):
        col = idx % cols
        row = idx // cols
        positions[part] = (col * cell, row * cell)
    return positions


def _module_field(part) -> str:
    """Best-effort owning-module tag (set by Module.add / add_part)."""
    try:
        fields = getattr(part, "fields", None)
        if isinstance(fields, dict):
            v = fields.get("OpenHaC_Module")
            if v is not None and str(v).strip():
                return str(v).strip()
    except Exception:
        pass
    return ""

def _module_layer(part) -> int | None:
    try:
        fields = getattr(part, "fields", None)
        if isinstance(fields, dict):
            v = fields.get("OpenHaC_Module_Layer")
            if v is not None:
                return int(v)
    except Exception:
        pass
    return None


def _assign_positions_grouped_by_module(parts) -> dict:
    """Place parts using a DAG or grid layout based on module tags."""
    try:
        import networkx as nx
        has_nx = True
    except ImportError:
        logger.debug("networkx not installed; falling back to basic grid layout.")
        has_nx = False

    cols, cell = _schematic_layout_params()
    groups: dict[str, list] = {}
    for p in parts:
        groups.setdefault(_module_field(p), []).append(p)

    module_names = sorted(groups.keys(), key=lambda s: (s == "", s))
    
    positions: dict = {}
    
    # Layout each module individually
    mod_positions = {}
    mod_dims = {}
    
    for m in module_names:
        m_parts = groups[m]
        
        # Always use a deterministic grid layout for schematics.
        # Force-directed graphs cluster disconnected components on top of each other.
        # We sort by ref prefix to group ICs (U), Connectors (J/CONN), and Passives (C, R, L)
        def sort_key(p):
            ref = str(getattr(p, "ref", "") or "").upper()
            if ref.startswith("U"): return (0, ref)
            if ref.startswith("J") or ref.startswith("CONN"): return (1, ref)
            if ref.startswith("C"): return (2, ref)
            if ref.startswith("R"): return (3, ref)
            return (4, ref)
            
        sorted_parts = sorted(m_parts, key=sort_key)
        lpos = {}
        for idx, part in enumerate(sorted_parts):
            c = idx % cols
            r = idx // cols
            lpos[part] = (c * cell, r * cell)
            
        mod_positions[m] = lpos
        
        # Calculate bounding box of this module
        if lpos:
            min_x = min(x for x, y in lpos.values())
            max_x = max(x for x, y in lpos.values())
            min_y = min(y for x, y in lpos.values())
            max_y = max(y for x, y in lpos.values())
            mod_dims[m] = (max_x - min_x + cell, max_y - min_y + cell)
        else:
            mod_dims[m] = (cell, cell)
            
    # Determine layers
    mod_layers = {}
    has_layers = False
    for m, m_parts in groups.items():
        layer = None
        for p in m_parts:
            l = _module_layer(p)
            if l is not None:
                layer = l
                has_layers = True
                break
        mod_layers[m] = layer if layer is not None else 0

    if has_layers:
        # Pack by layer (DAG flow left-to-right)
        layer_mods = {}
        for m, l in mod_layers.items():
            layer_mods.setdefault(l, []).append(m)
            
        current_x = 0.0
        for l in sorted(layer_mods.keys()):
            mods_in_layer = sorted(layer_mods[l])
            current_y = 0.0
            max_w = 0.0
            for m in mods_in_layer:
                w, h = mod_dims[m]
                lpos = mod_positions[m]
                min_x = min([x for x, y in lpos.values()] + [0])
                min_y = min([y for x, y in lpos.values()] + [0])
                for part, (lx, ly) in lpos.items():
                    positions[part] = (current_x + (lx - min_x), current_y + (ly - min_y))
                current_y += h + cell * 2
                max_w = max(max_w, w)
            current_x += max_w + cell * 3
    else:
        # Pack the modules into a global grid (e.g. 2 columns of modules)
        global_cols = max(1, cols // 2)
        row_heights = {}
        
        for idx, m in enumerate(module_names):
            r = idx // global_cols
            w, h = mod_dims[m]
            row_heights[r] = max(row_heights.get(r, 0), h)
            
        current_y = 0.0
        for r in sorted(row_heights.keys()):
            current_x = 0.0
            for c in range(global_cols):
                idx = r * global_cols + c
                if idx >= len(module_names):
                    break
                m = module_names[idx]
                w, h = mod_dims[m]
                
                # Translate module parts to global position
                lpos = mod_positions[m]
                min_x = min([x for x, y in lpos.values()] + [0])
                min_y = min([y for x, y in lpos.values()] + [0])
                
                for part, (lx, ly) in lpos.items():
                    positions[part] = (current_x + (lx - min_x), current_y + (ly - min_y))
                    
                current_x += w + cell * 2 # Add generous padding between modules
                
            current_y += row_heights[r] + cell * 2

    return positions


def _part_stable_key(part) -> tuple:
    """Stable ordering for schematic emission/placement (ref then lib_id)."""
    ref = str(getattr(part, "ref", "") or "")
    lib = part_library_name(part)
    name = (getattr(part, "name", None) or "").strip()
    return (ref, lib, name)


def _net_stable_key(net) -> str:
    return str(getattr(net, "name", None) or str(net))


def _fmt_mm(x: float) -> str:
    """Stable numeric formatting for KiCad S-expressions.

    KiCad accepts decimal floats; we emit up to 4 decimals (more than enough for 0.01mm-ish resolution),
    and strip trailing zeros to keep diffs small.
    """
    s = f"{float(x):.4f}".rstrip("0").rstrip(".")
    return s if s else "0"


def _detect_symbol_type(part) -> str:
    """Detect component type from footprint/ref prefix for appropriate symbol shape."""
    fp = str(getattr(part, 'footprint', '') or '').lower()
    ref = str(getattr(part, 'ref', '') or '').lower()
    name = str(getattr(part, 'name', '') or '').lower()

    # Check reference prefix first
    if ref.startswith('r'):
        return 'resistor'
    if ref.startswith('c'):
        return 'capacitor'
    if ref.startswith('l'):
        return 'inductor'
    if ref.startswith('d'):
        return 'diode'
    if ref.startswith('led') or 'led' in name:
        return 'led'
    if ref.startswith('q'):
        return 'transistor'
    if ref.startswith('y') or 'xtal' in name or 'crystal' in fp:
        return 'crystal'
    if ref.startswith('f'):
        return 'fuse'
    if ref.startswith('sw') or 'switch' in name:
        return 'switch'
    if ref.startswith('j') or 'conn' in name or 'header' in fp:
        return 'connector'
    # ICs default to rectangle
    return 'ic'


def _resistor_graphic() -> str:
    """Zig-zag resistor symbol centered at origin."""
    # Standard resistor: 10 segments in zig-zag pattern
    segments = [
        "      (polyline (pts (xy -3.81 0) (xy -3.175 0)) (stroke (width 0.254)))",
        "      (polyline (pts (xy -3.175 0) (xy -2.54 1.016) (xy -1.905 -1.016) (xy -1.27 1.016)) (stroke (width 0.254)))",
        "      (polyline (pts (xy -1.27 1.016) (xy -0.635 -1.016) (xy 0 1.016)) (stroke (width 0.254)))",
        "      (polyline (pts (xy 0 1.016) (xy 0.635 -1.016) (xy 1.27 1.016)) (stroke (width 0.254)))",
        "      (polyline (pts (xy 1.27 1.016) (xy 1.905 -1.016) (xy 2.54 0)) (stroke (width 0.254)))",
        "      (polyline (pts (xy 2.54 0) (xy 3.175 0)) (stroke (width 0.254)))",
    ]
    return "\n".join(segments)


def _capacitor_graphic() -> str:
    """Parallel plate capacitor symbol."""
    return """      (polyline (pts (xy -0.508 -1.27) (xy -0.508 1.27)) (stroke (width 0.254)))
      (polyline (pts (xy 0.508 -1.27) (xy 0.508 1.27)) (stroke (width 0.254)))
      (polyline (pts (xy -3.175 0) (xy -0.508 0)) (stroke (width 0.254)))
      (polyline (pts (xy 0.508 0) (xy 3.175 0)) (stroke (width 0.254)))"""


def _inductor_graphic() -> str:
    """Coil inductor symbol."""
    return """      (arc (start -1.27 0) (mid -0.635 0.635) (end 0 0) (stroke (width 0.254)))
      (arc (start 0 0) (mid 0.635 0.635) (end 1.27 0) (stroke (width 0.254)))
      (arc (start 1.27 0) (mid 1.905 0.635) (end 2.54 0) (stroke (width 0.254)))
      (arc (start 2.54 0) (mid 3.175 0.635) (end 3.81 0) (stroke (width 0.254)))
      (polyline (pts (xy -3.81 0) (xy -1.27 0)) (stroke (width 0.254)))
      (polyline (pts (xy 3.81 0) (xy 5.08 0)) (stroke (width 0.254)))"""


def _diode_graphic() -> str:
    """Diode symbol with triangle and bar."""
    return """      (polyline (pts (xy -1.27 -1.27) (xy -1.27 1.27) (xy 1.27 0) (xy -1.27 -1.27)) (stroke (width 0.254)) (fill (type none)))
      (polyline (pts (xy 1.27 -1.27) (xy 1.27 1.27)) (stroke (width 0.254)))
      (polyline (pts (xy -2.54 0) (xy -1.27 0)) (stroke (width 0.254)))
      (polyline (pts (xy 1.27 0) (xy 2.54 0)) (stroke (width 0.254)))"""


def _led_graphic() -> str:
    """LED symbol (diode with arrows)."""
    return """      (polyline (pts (xy -1.27 -1.27) (xy -1.27 1.27) (xy 1.27 0) (xy -1.27 -1.27)) (stroke (width 0.254)) (fill (type none)))
      (polyline (pts (xy 1.27 -1.27) (xy 1.27 1.27)) (stroke (width 0.254)))
      (polyline (pts (xy -2.54 0) (xy -1.27 0)) (stroke (width 0.254)))
      (polyline (pts (xy 1.27 0) (xy 2.54 0)) (stroke (width 0.254)))
      (polyline (pts (xy 0.508 1.778) (xy 1.27 2.54)) (stroke (width 0.254)))
      (polyline (pts (xy 1.016 2.286) (xy 1.27 2.54) (xy 0.762 2.54)) (stroke (width 0.254)))
      (polyline (pts (xy -0.254 1.016) (xy 0.508 1.778)) (stroke (width 0.254)))
      (polyline (pts (xy 0.254 1.524) (xy 0.508 1.778) (xy 0 1.778)) (stroke (width 0.254)))"""


def _transistor_graphic() -> str:
    """MOSFET symbol."""
    return """      (circle (center 0 0) (radius 2.54) (stroke (width 0.254)) (fill (type none)))
      (polyline (pts (xy -2.54 0) (xy -1.27 0)) (stroke (width 0.254)))
      (polyline (pts (xy -1.27 -1.905) (xy -1.27 1.905)) (stroke (width 0.254)))
      (polyline (pts (xy -1.27 -1.27) (xy 0.635 -1.27)) (stroke (width 0.254)))
      (polyline (pts (xy -1.27 0) (xy 0.635 0)) (stroke (width 0.254)))
      (polyline (pts (xy -1.27 1.27) (xy 0.635 1.27)) (stroke (width 0.254)))
      (polyline (pts (xy 0.635 -1.905) (xy 0.635 1.905)) (stroke (width 0.254)))
      (polyline (pts (xy 0.635 0) (xy 2.54 0)) (stroke (width 0.254)))"""


def _crystal_graphic() -> str:
    """Crystal symbol with two plates."""
    return """      (rectangle (start -1.27 -1.27) (end 1.27 1.27) (stroke (width 0.254)) (fill (type none)))
      (polyline (pts (xy -2.54 -1.27) (xy -2.54 1.27)) (stroke (width 0.254)))
      (polyline (pts (xy 2.54 -1.27) (xy 2.54 1.27)) (stroke (width 0.254)))
      (polyline (pts (xy -3.81 -1.27) (xy -3.81 1.27)) (stroke (width 0.254)))
      (polyline (pts (xy 3.81 -1.27) (xy 3.81 1.27)) (stroke (width 0.254)))
      (polyline (pts (xy -3.81 0) (xy -3.175 0)) (stroke (width 0.254)))
      (polyline (pts (xy 3.175 0) (xy 3.81 0)) (stroke (width 0.254)))"""


def _fuse_graphic() -> str:
    """Fuse symbol (rectangle with leads)."""
    return """      (rectangle (start -1.27 -0.635) (end 1.27 0.635) (stroke (width 0.254)) (fill (type none)))
      (polyline (pts (xy -3.175 0) (xy -1.27 0)) (stroke (width 0.254)))
      (polyline (pts (xy 1.27 0) (xy 3.175 0)) (stroke (width 0.254)))"""


def _ic_graphic(name: str, pin_count: int, w_mm: float = 10.16, h_mm: float = 0) -> str:
    """IC rectangle with appropriate size for pin count."""
    if h_mm == 0:
        height_pins = max(pin_count // 2, 4)
        h_mm = height_pins * 2.54
    w = w_mm / 2
    h = h_mm / 2
    return f'      (rectangle (start -{w:.3f} -{h:.3f}) (end {w:.3f} {h:.3f}) (stroke (width 0.254)) (fill (type background)))'


def _get_graphic_for_type(sym_type: str, name: str, pin_count: int, w_mm: float = 10.16, h_mm: float = 0) -> str:
    """Return appropriate graphic for component type."""
    graphics = {
        'resistor': _resistor_graphic(),
        'capacitor': _capacitor_graphic(),
        'inductor': _inductor_graphic(),
        'diode': _diode_graphic(),
        'led': _led_graphic(),
        'transistor': _transistor_graphic(),
        'crystal': _crystal_graphic(),
        'fuse': _fuse_graphic(),
        'switch': _fuse_graphic(),  # Rectangle for now
        'connector': _ic_graphic(name, pin_count, w_mm, h_mm),
        'ic': _ic_graphic(name, pin_count, w_mm, h_mm),
    }
    return graphics.get(sym_type, _ic_graphic(name, pin_count, w_mm, h_mm))


def write_generated_symbol_library(
    output_path: str, circuit_or_parts, *, nickname: str = "OpenHaC"
) -> tuple[str | None, str | None]:
    """Write a KiCad ``.kicad_sym`` for parts with component-appropriate symbols.

    This prevents KiCad showing '?' placeholders when symbols are not available in system libraries.
    Generates type-appropriate symbols: resistors as zig-zags, capacitors as plates, etc.

    Returns ``(path, lib_symbols_embed)`` where *lib_symbols_embed* is the body to place inside
    a schematic ``(lib_symbols ...)`` block (so symbols resolve even when sym-lib-table is missing).
    Either or both may be ``None`` if nothing was generated or embed is disabled.
    """
    # Accept either a circuit-like object with .parts or an iterable of parts.
    parts = list(getattr(circuit_or_parts, "parts", None) or circuit_or_parts or [])
    if not parts:
        return None, None

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    def _sym_header(outer_key: str, inner_base: str, ref_prefix: str, sym_type: str, pin_count: int, w_mm: float = 10.16, h_mm: float = 0) -> str:
        # Choose appropriate reference prefix and graphic (inner_base drives unit name and IC bbox).
        graphic = _get_graphic_for_type(sym_type, inner_base, pin_count, w_mm, h_mm)
        
        # Position reference slightly above the IC body, and Value below
        h = h_mm / 2 if h_mm > 0 else (max(pin_count // 2, 4) * 1.27)
        
        return (
            f'  (symbol "{outer_key}" (in_bom yes) (on_board yes)\n'
            f'    (property "Reference" "{ref_prefix}" (at 0 {h + 2.54:.3f} 0) (effects (font (size 1.27 1.27))))\n'
            f'    (property "Value" "{inner_base}" (at 0 -{h + 2.54:.3f} 0) (effects (font (size 1.27 1.27))))\n'
            f'    (symbol "{inner_base}_0_1"\n'
            f'{graphic}\n'
        )

    def _sym_footer() -> str:
        return "    )\n  )\n"

    def _pin_block(num: str, pname: str, x: float, y: float, rot: float, explicit_type: str | None = None) -> str:
        # Use pin numbers for SCH-001 resolver (number "N") with (at x y rot).
        safe_name = pname.replace('"', "'")
        
        # Map JSON pin type to KiCad pin type
        kicad_type = "passive"
        t = str(explicit_type or "").lower()
        if t in ("input", "output", "bidirectional", "tri_state", "passive", "unspecified", "power_in", "power_out", "open_collector", "open_emitter", "no_connect"):
            kicad_type = t
        elif t == "power":
            kicad_type = "power_in"
            
        # Fallback heuristic for power pins if type wasn't explicitly power
        if kicad_type in ("passive", "bidirectional", "unspecified") and any(p in pname.upper() for p in ['VCC', 'VDD', '3V3', '5V', 'VBAT', 'GND', 'VSS']):
            kicad_type = "power_in"
            
        return (
            f'      (pin {kicad_type} line (at {_fmt_mm(x)} {_fmt_mm(y)} {_fmt_mm(rot)}) (length 2.54)\n'
            f'        (name "{safe_name}" (effects (font (size 0.8 0.8))))\n'
            f'        (number "{num}" (effects (font (size 0.8 0.8))))\n'
            f"      )\n"
        )

    def _get_ref_prefix(part) -> str:
        """Get appropriate reference prefix for part."""
        ref = str(getattr(part, 'ref', '') or '')
        # Extract prefix (letters before numbers)
        prefix = ''
        for c in ref:
            if c.isalpha():
                prefix += c
            else:
                break
        return prefix.upper() if prefix else 'U'

    names = sorted({schematic_symbol_lib_key(p) for p in parts})
    if not names:
        return None, None

    # Map symbol name -> representative part (for pin list).
    by_name = {}
    for p in parts:
        n = schematic_symbol_lib_key(p)
        if n and n not in by_name:
            by_name[n] = p

    lines = []
    embed_chunks: list[str] = []
    lines.append('(kicad_symbol_lib (version 20231120) (generator openhac)\n')
    for name in names:
        part = by_name[name]
        if hasattr(part, "get_pins"):
            pins = part.get_pins()
        else:
            pins_raw = getattr(part, "pins", []) or []
            if isinstance(pins_raw, dict):
                seen = set()
                pins = []
                for p_ in pins_raw.values():
                    if id(p_) not in seen:
                        seen.add(id(p_))
                        pins.append(p_)
            else:
                pins = list(pins_raw)
        ref_prefix = _get_ref_prefix(part)
        sym_type = _detect_symbol_type(part)

        pin_lines: list[str] = []
        w_mm = 10.16
        h_mm = 0
        
        # Pin placement: left/right for 2-pin components, smart box for ICs
        if sym_type in ('resistor', 'capacitor', 'inductor', 'diode', 'led', 'fuse') and len(pins) == 2:
            # Horizontal: pins on left and right
            for i, pin in enumerate(pins):
                num = str(getattr(pin, "num", "") or str(i + 1))
                pname = str(getattr(pin, "name", "") or num)
                ptype = str(getattr(pin, "pin_type", ""))
                x = -5.08 if i == 0 else 5.08
                rot = 0 if i == 0 else 180
                pin_lines.append(_pin_block(num, pname, x, 0, rot, ptype))
        elif sym_type in ('crystal',) and len(pins) >= 2:
            # Crystal: pins on left/right
            pin_positions = [(-5.08, 0, 0), (5.08, 0, 180)]
            for i, pin in enumerate(pins[:4]):
                num = str(getattr(pin, "num", "") or str(i + 1))
                pname = str(getattr(pin, "name", "") or num)
                ptype = str(getattr(pin, "pin_type", ""))
                if i < len(pin_positions):
                    x, y, rot = pin_positions[i]
                    pin_lines.append(_pin_block(num, pname, x, y, rot, ptype))
        else:
            # IC-style: Smart pin placement
            top_pins = []
            bottom_pins = []
            left_pins = []
            right_pins = []
            
            for pin in pins:
                num = str(getattr(pin, "num", "") or str(getattr(pin, "number", "")))
                pname = str(getattr(pin, "name", "") or num)
                ptype = str(getattr(pin, "pin_type", "")).lower()
                
                pn_upper = pname.upper()
                is_power = ptype in ("power_in", "power_out", "power") or any(x in pn_upper for x in ("VCC", "VDD", "3V3", "5V", "VBAT", "GND", "VSS"))
                
                if is_power:
                    if "GND" in pn_upper or "VSS" in pn_upper:
                        bottom_pins.append((num, pname, ptype))
                    else:
                        top_pins.append((num, pname, ptype))
                elif ptype == "input" or any(x in pn_upper for x in ("CLK", "RST", "EN")):
                    left_pins.append((num, pname, ptype))
                elif ptype == "output":
                    right_pins.append((num, pname, ptype))
                else:
                    if len(left_pins) <= len(right_pins):
                        left_pins.append((num, pname, ptype))
                    else:
                        right_pins.append((num, pname, ptype))
            
            h_pins = max(len(left_pins), len(right_pins))
            w_pins = max(len(top_pins), len(bottom_pins))
            
            h_mm = max((h_pins + 1) * 2.54, 10.16)
            w_mm = max((w_pins + 1) * 2.54, 10.16)
            
            left_x = -(w_mm / 2) - 2.54
            right_x = (w_mm / 2) + 2.54
            top_y = (h_mm / 2) + 2.54
            bottom_y = -(h_mm / 2) - 2.54
            
            def _distribute_pins(pin_list, x_fixed, y_fixed, rot, is_vertical, length_mm):
                lines = []
                if not pin_list: return lines
                spacing = length_mm / (len(pin_list) + 1)
                for i, (num, pname, ptype) in enumerate(pin_list):
                    offset = (length_mm / 2) - ((i + 1) * spacing)
                    if is_vertical:
                        lines.append(_pin_block(num, pname, x_fixed, offset, rot, ptype))
                    else:
                        lines.append(_pin_block(num, pname, -offset, y_fixed, rot, ptype))
                return lines

            pin_lines.extend(_distribute_pins(left_pins, left_x, 0, 0, True, h_mm))
            pin_lines.extend(_distribute_pins(right_pins, right_x, 0, 180, True, h_mm))
            pin_lines.extend(_distribute_pins(top_pins, 0, top_y, 270, False, w_mm))
            pin_lines.extend(_distribute_pins(bottom_pins, 0, bottom_y, 90, False, w_mm))

        lines.append(_sym_header(name, name, ref_prefix, sym_type, len(pins), w_mm, h_mm))
        lines.extend(pin_lines)
        lines.append(_sym_footer())

        # Qualified outer name for (lib_symbols ...) embed in .kicad_sch (matches lib_id OpenHaC:name).
        embed_chunks.append(_sym_header(f"{nickname}:{name}", name, ref_prefix, sym_type, len(pins), w_mm, h_mm))
        embed_chunks.extend(pin_lines)
        embed_chunks.append(_sym_footer())
    lines.append(")\n")

    out.write_text("".join(lines), encoding="utf-8")

    def _nest_for_lib_symbols(body: str) -> str:
        lines_out: list[str] = []
        for line in body.splitlines(True):
            if line.strip():
                lines_out.append("  " + line)
            else:
                lines_out.append(line)
        return "".join(lines_out)

    embed_body = _nest_for_lib_symbols("".join(embed_chunks))
    return str(out), embed_body


def _emit_symbol_instance(f, part, x, y, uuid_str: str) -> None:
    """Write a (symbol ...) S-expression block for a single part."""
    # Use the generated project-local library when present to avoid KiCad '?' placeholders.
    sym_name = schematic_symbol_lib_key(part)
    lib_id = f"OpenHaC:{sym_name}"
    rot = 0.0
    try:
        fields = getattr(part, "fields", None)
        if isinstance(fields, dict) and fields.get("OpenHaC_Rotation_Deg") is not None:
            rot = float(fields.get("OpenHaC_Rotation_Deg"))
    except Exception:
        rot = 0.0
    ref = str(getattr(part, "ref", None) or getattr(part, "refdes", None) or "").strip() or "U?"
    val = str(getattr(part, "value", None) or getattr(part, "name", None) or "").strip() or ref
    fp = str(getattr(part, "footprint", None) or "").strip()

    f.write(f'  (symbol (lib_id "{lib_id}") (at {_fmt_mm(x)} {_fmt_mm(y)} {_fmt_mm(rot)}) (unit 1)\n')
    f.write('    (in_bom yes) (on_board yes) (fields_autoplaced yes)\n')
    f.write(f'    (uuid "{uuid_str}")\n')
    # Minimal properties so KiCad actually renders/annotates the symbol.
    f.write(f'    (property "Reference" "{ref}" (at {_fmt_mm(x)} {_fmt_mm(y - 2.54)} 0)\n')
    f.write('      (effects (font (size 1.27 1.27) (thickness 0.15)))\n')
    f.write('    )\n')
    f.write(f'    (property "Value" "{val}" (at {_fmt_mm(x)} {_fmt_mm(y + 2.54)} 0)\n')
    f.write('      (effects (font (size 1.27 1.27) (thickness 0.15)))\n')
    f.write('    )\n')
    f.write(f'    (property "Footprint" "{fp}" (at {_fmt_mm(x)} {_fmt_mm(y + 5.08)} 0)\n')
    f.write('      (effects (font (size 1.27 1.27) (thickness 0.15)) (hide yes))\n')
    f.write('    )\n')
    f.write(f'    (property "Datasheet" "" (at {_fmt_mm(x)} {_fmt_mm(y + 7.62)} 0)\n')
    f.write('      (effects (font (size 1.27 1.27) (thickness 0.15)) (hide yes))\n')
    f.write('    )\n')
    f.write('  )\n')


def _emit_wire(f, x1, y1, x2, y2) -> None:
    """Write a (wire ...) S-expression block."""
    wire_uuid = _uuid_for(f"wire:{x1:.6f},{y1:.6f}:{x2:.6f},{y2:.6f}")
    f.write(
        f'  (wire (pts (xy {_fmt_mm(x1)} {_fmt_mm(y1)}) (xy {_fmt_mm(x2)} {_fmt_mm(y2)}))\n'
    )
    f.write(f'    (stroke (width 0) (type default))\n')
    f.write(f'    (uuid "{wire_uuid}")\n')
    f.write(f'  )\n')


def _emit_sheet_instances(f, *, sheet_paths: list[tuple[str, str]] | None = None) -> None:
    """Emit minimal (sheet_instances ...) so KiCad can open the schematic reliably.

    KiCad 7+ expects sheet instances even for single-sheet designs.
    """
    f.write("  (sheet_instances\n")
    # Root sheet always exists.
    f.write('    (path "/" (page "1"))\n')
    for p, page in (sheet_paths or []):
        sp = str(p or "").strip()
        if not sp.startswith("/"):
            sp = "/" + sp
        f.write(f'    (path "{kicad_string_escape(sp)}" (page "{kicad_string_escape(str(page))}"))\n')
    f.write("  )\n")


def _emit_symbol_instances(f, *, sym_paths: list[tuple[str, str, str, str]] | None = None) -> None:
    """Emit minimal (symbol_instances ...) for KiCad bookkeeping.

    Each entry: (path, reference, value, footprint).
    """
    f.write("  (symbol_instances\n")
    for path, ref, val, fp in (sym_paths or []):
        p = str(path or "").strip() or "/"
        if not p.startswith("/"):
            p = "/" + p
        f.write(
            f'    (path "{kicad_string_escape(p)}" (reference "{kicad_string_escape(ref)}") '
            f'(unit 1) (value "{kicad_string_escape(val)}") (footprint "{kicad_string_escape(fp)}"))\n'
        )
    f.write("  )\n")


def _pin_world_xy(
    pin,
    part,
    part_xy: tuple[float, float],
    resolver: SymbolPinResolver | None,
) -> tuple[float, float]:
    """Schematic (x, y) for *pin*; uses KiCad library coords when available (SCH-001)."""
    x0, y0 = part_xy
    if resolver is not None:
        off = resolver.offset_for_pin(part, pin)
        if off is not None:
            return x0 + off[0], y0 + off[1]
    idx = _pin_index_on_part(pin)
    return x0, y0 + idx * 2.54


def _pin_index_on_part(pin) -> int:
    """Index of *pin* along its parent part's pin list (for schematic stub placement)."""
    part = getattr(pin, "part", None)
    if part is None:
        return 0
    try:
        pins = part.get_pins() if hasattr(part, "get_pins") else getattr(part, "pins", [])
        for idx, p in enumerate(pins):
            if p is pin:
                return idx
    except Exception:
        pass
    return 0


_PIN_NAT_SPLIT = re.compile(r"(\d+|\D+)")


def _pin_number_natural_key(s: str) -> tuple:
    """Alphanumeric pin order (A2 before A10; 2 before 10) for BGA-style designators."""
    parts: list[tuple[int, int | str]] = []
    for chunk in _PIN_NAT_SPLIT.findall(str(s)):
        if chunk.isdigit():
            parts.append((0, int(chunk)))
        else:
            parts.append((1, chunk.lower()))
    return tuple(parts)


def _pin_sort_key(pin) -> tuple:
    """Stable ordering for pins on a net (SCH-001: deterministic wiring, not net iteration order)."""
    part = getattr(pin, "part", None)
    ref = getattr(part, "ref", "") or ""
    num = getattr(pin, "num", "")
    snum = str(num)
    try:
        nkey = (0, int(snum))
    except ValueError:
        nkey = (1, _pin_number_natural_key(snum))
    return (ref, nkey)


def sorted_net_pins(net) -> list:
    """Return pins on *net* sorted by (reference designator, pin number)."""
    pins = [p for p in net.pins if getattr(p, "part", None) is not None]
    return sorted(pins, key=_pin_sort_key)


def kicad_string_escape(text: str) -> str:
    r"""Escape *text* for KiCad schematic double-quoted strings (\\ and \")."""
    s = text.replace("\\", "\\\\").replace('"', '\\"')
    return s


def net_connectivity_signatures(circuit) -> dict[str, frozenset[tuple[str, str]]]:
    """Map net name → frozenset of (part ref, pin number str) for equivalence checks / tests."""
    out: dict[str, frozenset[tuple[str, str]]] = {}
    for net in circuit.nets:
        pins = list(getattr(net, "pins", []) or [])
        if len(pins) < 2:
            continue
        name = getattr(net, "name", None) or str(net)
        sig = frozenset(
            (getattr(p.part, "ref", "?"), str(getattr(p, "num", "?")))
            for p in pins
            if getattr(p, "part", None) is not None
        )
        out[name] = sig
    return out


def kicad_sch_unescape_label(s: str) -> str:
    r"""Undo ``kicad_string_escape`` for label text parsed from a ``.kicad_sch`` file."""
    out: list[str] = []
    i = 0
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s):
            out.append(s[i + 1])
            i += 2
        else:
            out.append(s[i])
            i += 1
    return "".join(out)


def parse_kicad_sch_wire_segments(sch_text: str) -> list[tuple[float, float, float, float]]:
    """Return ``(x1, y1, x2, y2)`` for each ``(wire (pts ...))`` in file text (SCH-001 golden)."""
    return [tuple(map(float, m.groups())) for m in _WIRE_PTS_RE.finditer(sch_text)]


def parse_kicad_sch_net_labels(sch_text: str) -> list[tuple[str, float, float]]:
    """Return ``(net_name, x, y)`` for each global label in file text."""
    out: list[tuple[str, float, float]] = []
    for m in _LABEL_AT_RE.finditer(sch_text):
        name = kicad_sch_unescape_label(m.group(1))
        out.append((name, float(m.group(2)), float(m.group(3))))
    return out


def schematic_geometry(
    circuit,
    *,
    symbol_resolver: SchematicPinResolver | None = None,
) -> dict:
    """Compute symbol grid, wire segments, and multi-pin net labels (same logic as ``generate_schematic``).

    Used for tests: parsed ``.kicad_sch`` wire/list label sets must match this structure (SCH-001).

    When *symbol_resolver* is None, a default :class:`SymbolPinResolver` is used so wire endpoints
    align with KiCad ``.kicad_sym`` pin positions when libraries are on ``OPENHAC_KICAD_SYMBOL_DIRS``
    or standard ``KICAD*_SYMBOL_DIR`` paths; otherwise placement falls back to pin-index stubs.
    Pass :class:`openhac.compiler.kicad_sym_pinpos.EmptySymbolPinResolver` to force stub layout only.
    """
    if symbol_resolver is not None:
        resolver: SchematicPinResolver = symbol_resolver
    else:
        # Deterministic / debug mode: allow forcing stub-only geometry even when KiCad symbol libs are available.
        # This is useful for bisecting “why did my schematic wire endpoints move?” reports.
        resolver = EmptySymbolPinResolver() if _truthy_env("OPENHAC_SCHEMATIC_STUB_ONLY") else SymbolPinResolver()
    parts = sorted(list(circuit.parts), key=_part_stable_key)
    positions = _assign_positions_grouped_by_module(parts)
    part_placements: dict = {part: positions[part] for part in parts}

    wires: list[tuple[float, float, float, float]] = []
    labels: list[tuple[str, float, float]] = []

    for net in sorted(list(circuit.nets), key=_net_stable_key):
        pins = sorted_net_pins(net)
        if len(pins) < 2:
            continue

        net_name = getattr(net, "name", None) or str(net)
        is_power = any(n in net_name.upper() for n in ["GND", "VCC", "3V3", "5V", "VBAT", "PWR", "VSS", "VDD", "SOURCE"])

        if is_power:
            for pin in pins:
                px, py = part_placements.get(pin.part, (0.0, 0.0))
                pxw, pyw = _pin_world_xy(pin, pin.part, (px, py), resolver)
                
                # Determine outward stub direction relative to component center
                if abs(pxw - px) < 0.1:
                    # Top or bottom edge
                    dy = -5.08 if pyw < py else 5.08
                    wires.append((pxw, pyw, pxw, pyw + dy))
                    labels.append((net_name, pxw, pyw + dy))
                else:
                    # Left or right edge
                    dx = -5.08 if pxw < px else 5.08
                    wires.append((pxw, pyw, pxw + dx, pyw))
                    labels.append((net_name, pxw + dx, pyw))
        else:
            for i in range(len(pins) - 1):
                pin_a = pins[i]
                pin_b = pins[i + 1]
                ax, ay = part_placements.get(pin_a.part, (0.0, 0.0))
                bx, by = part_placements.get(pin_b.part, (0.0, 0.0))
                axw, ayw = _pin_world_xy(pin_a, pin_a.part, (ax, ay), resolver)
                bxw, byw = _pin_world_xy(pin_b, pin_b.part, (bx, by), resolver)
                
                mid_x = round(((axw + bxw) / 2) / 2.54) * 2.54
                for x1, y1, x2, y2 in [
                    (axw, ayw, mid_x, ayw),
                    (mid_x, ayw, mid_x, byw),
                    (mid_x, byw, bxw, byw),
                ]:
                    if abs(x1 - x2) > 0.001 or abs(y1 - y2) > 0.001:
                        wires.append((x1, y1, x2, y2))

            if len(pins) > 2:
                first_pin = pins[0]
                lx, ly = part_placements.get(first_pin.part, (0.0, 0.0))
                lxw, lyw = _pin_world_xy(first_pin, first_pin.part, (lx, ly), resolver)
                labels.append((net_name, lxw, lyw))

    return {"part_placements": part_placements, "wires": wires, "labels": labels}


class _RecordingPinResolver:
    """Wrap another resolver and record how many pin offsets were resolved vs stubbed (SCH-001)."""

    __slots__ = ("_inner", "resolved_pin_count", "stub_pin_count", "by_symbol")

    def __init__(self, inner: SchematicPinResolver):
        self._inner = inner
        self.resolved_pin_count: int = 0
        self.stub_pin_count: int = 0
        # key: "Lib:Symbol" -> {"resolved": int, "stub": int}
        self.by_symbol: dict[str, dict[str, int]] = {}

    def offset_for_pin(self, part, pin) -> tuple[float, float] | None:
        off = self._inner.offset_for_pin(part, pin)
        lib = part_library_name(part)
        name = (getattr(part, "name", None) or "").strip()
        key = f"{lib}:{name}" if lib else (name or "?")
        ent = self.by_symbol.setdefault(key, {"resolved": 0, "stub": 0})
        if off is not None:
            self.resolved_pin_count += 1
            ent["resolved"] += 1
        else:
            self.stub_pin_count += 1
            ent["stub"] += 1
        return off


def schematic_wire_endpoint_pairs(circuit) -> list[frozenset[tuple[str, str]]]:
    """Undirected edges (ref, pin) pairs the schematic generator will wire (chain over sorted pins)."""
    edges: list[frozenset[tuple[str, str]]] = []
    for net in sorted(list(circuit.nets), key=_net_stable_key):
        pins = sorted_net_pins(net)
        if len(pins) < 2:
            continue
        for i in range(len(pins) - 1):
            a, b = pins[i], pins[i + 1]
            edges.append(
                frozenset(
                    {
                        (a.part.ref, str(a.num)),
                        (b.part.ref, str(b.num)),
                    }
                )
            )
    return edges


def _emit_net_label(f, net_name: str, x, y) -> None:
    """Write a (label ...) S-expression block for local nets."""
    label_uuid = _uuid_for(f"label:{net_name}:{x:.6f},{y:.6f}")
    safe = kicad_string_escape(net_name)
    f.write(f'  (label "{safe}" (at {_fmt_mm(x)} {_fmt_mm(y)} 0)\n')
    f.write(f'    (effects (font (size 1.27 1.27)))\n')
    f.write(f'    (uuid "{label_uuid}")\n')
    f.write(f'  )\n')

def _emit_global_label(f, net_name: str, x, y) -> None:
    """Write a (global_label ...) S-expression block for true connectivity."""
    label_uuid = _uuid_for(f"glabel:{net_name}:{x:.6f},{y:.6f}")
    safe = kicad_string_escape(net_name)
    f.write(f'  (global_label "{safe}" (shape input) (at {_fmt_mm(x)} {_fmt_mm(y)} 0)\n')
    f.write(f'    (effects (font (size 1.27 1.27)) (justify left))\n')
    f.write(f'    (uuid "{label_uuid}")\n')
    f.write(f'    (property "Intersheetrefs" "${{INTERSHEET_REFS}}" (at {_fmt_mm(x)} {_fmt_mm(y)} 0)\n')
    f.write(f'      (effects (font (size 1.27 1.27)) (hide yes))\n')
    f.write(f'    )\n')
    f.write(f'  )\n')


def _safe_sheet_filename(stem: str) -> str:
    s = (stem or "").strip()
    s = re.sub(r"[^A-Za-z0-9_.-]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("._")
    return s or "sheet"


def _emit_sheet_symbol(
    f,
    *,
    sheet_name: str,
    sheet_file: str,
    x: float,
    y: float,
    w: float,
    h: float,
    pin_names: list[str] | None = None,
) -> None:
    """Emit a KiCad sheet symbol referencing a subsheet file.

    Uses global labels for cross-sheet connectivity (no sheet pins), so the hierarchy exists for readability
    without requiring a full hierarchical-pin exporter yet.
    """
    su = _uuid_for(f"sheet:{sheet_name}:{sheet_file}:{x:.3f},{y:.3f}")
    safe_name = kicad_string_escape(sheet_name)
    safe_file = kicad_string_escape(sheet_file)
    f.write(f'  (sheet (at {_fmt_mm(x)} {_fmt_mm(y)}) (size {_fmt_mm(w)} {_fmt_mm(h)})\n')
    # Minimal stroke/fill so KiCad treats this as a proper sheet symbol.
    f.write('    (stroke (width 0.1524) (type default) (color 0 0 0 0))\n')
    f.write('    (fill (color 0 0 0 0))\n')
    f.write(f'    (uuid "{su}")\n')
    f.write(
        "    (property \"Sheet name\" \""
        + safe_name
        + "\" (at "
        + _fmt_mm(x + 1.0)
        + " "
        + _fmt_mm(y + 1.0)
        + " 0) (effects (font (size 1.27 1.27))))\n"
    )
    f.write(
        "    (property \"Sheet file\" \""
        + safe_file
        + "\" (at "
        + _fmt_mm(x + 1.0)
        + " "
        + _fmt_mm(y + 3.0)
        + " 0) (effects (font (size 1.27 1.27))))\n"
    )

    # Optional hierarchical pins (must be inside the (sheet ...) block for KiCad to parse).
    if pin_names:
        px = x
        py = y + 5.0
        for j, pname in enumerate(pin_names):
            _emit_sheet_pin(f, name=pname, pin_type="passive", x=px, y=py + j * 2.54, rot=0.0)

    # Instances are optional for KiCad to open, but keep output minimal for determinism.
    f.write("  )\n")


def _emit_sheet_pin(f, *, name: str, pin_type: str, x: float, y: float, rot: float = 0.0) -> None:
    pu = _uuid_for(f"sheet_pin:{name}:{x:.3f},{y:.3f}:{pin_type}")
    safe = kicad_string_escape(name)
    f.write(f'    (pin "{safe}" {pin_type} (at {_fmt_mm(x)} {_fmt_mm(y)} {rot})\n')
    f.write('      (effects (font (size 1.27 1.27)) (justify left))\n')
    f.write(f'      (uuid "{pu}")\n')
    f.write("    )\n")


def _emit_hierarchical_label(f, *, name: str, pin_type: str, x: float, y: float) -> None:
    """Child-sheet hierarchical label matching a parent sheet pin (KiCad S-expression)."""
    lu = _uuid_for(f"hier_label:{name}:{x:.3f},{y:.3f}:{pin_type}")
    safe = kicad_string_escape(name)
    f.write(f'  (hierarchical_label "{safe}" (shape {pin_type}) (at {_fmt_mm(x)} {_fmt_mm(y)} 0)\n')
    f.write('    (effects (font (size 1.27 1.27)) (justify left))\n')
    f.write(f'    (uuid "{lu}")\n')
    f.write("  )\n")


def _interface_nets_for_module(module) -> list:
    """Flatten module.required_interfaces into a stable list of nets for sheet pins."""
    ifaces = getattr(module, "required_interfaces", None) or {}
    out: list = []
    for iname in sorted(ifaces.keys()):
        iface = ifaces[iname]
        for net in getattr(iface, "signals", []) or []:
            out.append(net)
    return out


def _schematic_lint(board, circuit) -> list[str]:
    """Best-effort schematic lint (Phase-1 quality gate)."""
    violations: list[str] = []
    # Require module interface nets to be named.
    for mod in getattr(board, "modules", None) or []:
        for net in _interface_nets_for_module(mod):
            n = str(getattr(net, "name", "") or "").strip()
            if not n or n == "?":
                violations.append(f"Schematic lint: module {getattr(mod,'name','?')!r} interface net has no name.")
    return violations


def _nets_requiring_global_labels(circuit) -> dict:
    """Return net -> set(module_name) for nets that should be connected via global labels in multi-sheet export."""
    out: dict = {}
    for net in sorted(list(circuit.nets), key=_net_stable_key):
        pins = sorted_net_pins(net)
        if len(pins) < 2:
            continue
        mods: set[str] = set()
        for p in pins:
            mods.add(_module_field(p.part))
        if len(mods) > 1 or len(pins) > 2:
            out[net] = mods
    return out


def _labels_for_module_sheet(circuit, module_name: str, placements: dict, resolver: SchematicPinResolver) -> list[tuple[str, float, float]]:
    """Compute global net labels to preserve cross-sheet connectivity in multi-sheet mode."""
    nets_needed = _nets_requiring_global_labels(circuit)
    labels: list[tuple[str, float, float]] = []
    for net, mods in nets_needed.items():
        if module_name not in mods:
            continue
        pins = sorted_net_pins(net)
        pin_here = None
        for p in pins:
            if _module_field(p.part) == module_name:
                pin_here = p
                break
        if pin_here is None:
            continue
        lx, ly = placements.get(pin_here.part, (0.0, 0.0))
        lxw, lyw = _pin_world_xy(pin_here, pin_here.part, (lx, ly), resolver)
        net_name = getattr(net, "name", None) or str(net)
        labels.append((net_name, lxw, lyw))
    return labels


def _sch_embed_enabled() -> bool:
    return os.environ.get("OPENHAC_SCHEMATIC_EMBED_SYMBOLS", "1").strip().lower() not in ("0", "false", "no", "off")


def _write_kicad_sch_header(f, file_uuid: str, embedded_lib_symbols: str | None) -> None:
    f.write('(kicad_sch (version 20231120) (generator openhac)\n')
    f.write(f'  (uuid "{file_uuid}")\n')
    f.write('  (paper "A4")\n')
    emb = embedded_lib_symbols if (_sch_embed_enabled() and embedded_lib_symbols) else None
    if emb:
        f.write("  (lib_symbols\n")
        f.write(emb)
        f.write("  )\n")


def generate_schematic(
    output_path: str,
    board,
    *,
    symbol_resolver: SchematicPinResolver | None = None,
    pinpos_report_path: str | None = None,
    generated_symbol_lib_path: str | None = None,
    embedded_lib_symbols: str | None = None,
) -> None:
    """Generate a KiCad S-expression schematic file from the Board model.

    Historically this function used SKiDL's ``default_circuit`` as the source of truth.
    OpenHaC now supports a native Part/Net model; for schematic generation we derive
    a minimal circuit-like view from ``board.modules`` so KiCad artifacts are emitted
    even when SKiDL is not present or not used to store parts.
    """
    logger.info(f"Synthesizing Logic Graph into 2D Schematic Array -> {output_path}")

    # Build a circuit-like view from Board modules/components.
    class _BoardCircuitView:
        def __init__(self, parts, nets):
            self.parts = parts
            self.nets = nets

    parts: list[object] = []
    seen_parts: set[int] = set()
    for mod in getattr(board, "modules", []) or []:
        for child in getattr(mod, "components", []) or []:
            part = getattr(child, "part", None)
            if part is None:
                continue
            pid = id(part)
            if pid in seen_parts:
                continue
            seen_parts.add(pid)
            parts.append(part)

    # SKiDL-only flows / tests: parts may live on the default circuit without OpenHaC modules.
    if not parts:
        try:
            circ = get_default_circuit()
            for p in getattr(circ, "parts", None) or []:
                pid = id(p)
                if pid in seen_parts:
                    continue
                seen_parts.add(pid)
                parts.append(p)
        except Exception:
            pass

    nets: set[object] = set()
    for part in parts:
        for pin in getattr(part, "pins", {}).values() if isinstance(getattr(part, "pins", None), dict) else getattr(part, "pins", []) or []:
            try:
                n = getattr(pin, "net", None)
            except Exception:
                n = None
            if n is not None:
                nets.add(n)

    circuit = _BoardCircuitView(tuple(parts), tuple(sorted(nets, key=_net_stable_key)))

    # If we generated a project-local .kicad_sym, prepend its directory so SCH-001 pinpos
    # resolver can find it (and wire endpoints land on real pin coordinates).
    prev_sym_dirs = os.environ.get("OPENHAC_KICAD_SYMBOL_DIRS")
    if generated_symbol_lib_path:
        try:
            d = str(Path(generated_symbol_lib_path).resolve().parent)
            if prev_sym_dirs:
                os.environ["OPENHAC_KICAD_SYMBOL_DIRS"] = d + os.pathsep + prev_sym_dirs
            else:
                os.environ["OPENHAC_KICAD_SYMBOL_DIRS"] = d
        except Exception:
            pass

    file_uuid = _uuid_for("schematic:file")
    try:
        from openhac.compiler.kicad_sym_pinpos import SymbolPinResolver, EmptySymbolPinResolver
        
        if symbol_resolver is None:
            symbol_resolver = EmptySymbolPinResolver() if _truthy_env("OPENHAC_SCHEMATIC_STUB_ONLY") else SymbolPinResolver()
            
        if generated_symbol_lib_path and hasattr(symbol_resolver, "add_explicit_library"):
            symbol_resolver.add_explicit_library("OpenHaC", generated_symbol_lib_path)
            
        if pinpos_report_path is not None:
            rec = _RecordingPinResolver(symbol_resolver)
            geom = schematic_geometry(circuit, symbol_resolver=rec)
        else:
            rec = None
            geom = schematic_geometry(circuit, symbol_resolver=symbol_resolver)

        part_placements = geom["part_placements"]
        parts = sorted(list(circuit.parts), key=_part_stable_key)

        # Multi-sheet export:
        # - explicit opt-in via board attr or env
        # - otherwise auto-enable for larger designs (readability)
        if bool(getattr(board, "schematic_multi_sheet", False)) or _truthy_env("OPENHAC_SCHEMATIC_MULTI_SHEET"):
            multi_sheet = True
        elif _truthy_env("OPENHAC_SCHEMATIC_SINGLE_SHEET"):
            multi_sheet = False
        else:
            try:
                thr = int((os.environ.get("OPENHAC_SCHEMATIC_MULTI_SHEET_MIN_PARTS") or "25").strip() or 25)
            except Exception:
                thr = 25
            thr = max(2, min(thr, 5000))
            multi_sheet = len(parts) >= thr
        # Schematic style:
        # - wires: emit explicit wires (can be messy for large designs)
        # - labels: emit only net labels at pins (more readable, KiCad-native)
        style = (os.environ.get("OPENHAC_SCHEMATIC_STYLE") or "").strip().lower()
        if not style:
            style = "labels" if len(parts) >= 25 else "wires"

        # Choose a resolver for label pin world coords in multi-sheet mode.
        if symbol_resolver is not None:
            label_resolver: SchematicPinResolver = symbol_resolver
        else:
            label_resolver = EmptySymbolPinResolver() if _truthy_env("OPENHAC_SCHEMATIC_STUB_ONLY") else SymbolPinResolver()

        # Lint before writing outputs so failures are deterministic.
        lint = _schematic_lint(board, circuit)
        if lint and board.effective_compile_goal() == "fabrication":
            raise SchematicGenerationError("Schematic lint failed (fabrication mode):\n" + "\n".join(f"  • {v}" for v in lint))
        for v in lint:
            logger.warning("%s", v)

        if not multi_sheet:
            with open(output_path, "w", encoding="utf-8") as f:
                _write_kicad_sch_header(f, file_uuid, embedded_lib_symbols)

                sym_instances: list[tuple[str, str, str, str]] = []
                for part in parts:
                    x, y = part_placements[part]
                    ref = str(getattr(part, "ref", "") or "?")
                    part_uuid = _uuid_for(f"symbol:{ref}")
                    _emit_symbol_instance(f, part, x, y, part_uuid)
                    try:
                        val = str(getattr(part, "value", None) or getattr(part, "name", None) or "").strip() or ref
                        fp = str(getattr(part, "footprint", None) or "").strip()
                        sym_instances.append((f"/{file_uuid}/{part_uuid}", ref, val, fp))
                    except Exception:
                        pass

                if style == "wires":
                    for x1, y1, x2, y2 in geom["wires"]:
                        _emit_wire(f, x1, y1, x2, y2)
                else:
                    # Label-driven schematic: place a label at each connected pin.
                    # Do not depend on circuit.nets / net.pins (native + SKiDL variations);
                    # instead scan pins off parts and group by pin.net.
                    by_net: dict[object, list] = {}
                    for part in parts:
                        pins_raw = getattr(part, "pins", None)
                        if isinstance(pins_raw, dict):
                            pins_iter = list({id(p): p for p in pins_raw.values()}.values())
                        else:
                            pins_iter = list(pins_raw or [])
                        for p in pins_iter:
                            n = getattr(p, "net", None)
                            if n is None:
                                continue
                            by_net.setdefault(n, []).append(p)
                    for n in sorted(by_net.keys(), key=_net_stable_key):
                        pins = [p for p in by_net.get(n, []) if getattr(p, "part", None) is not None]
                        if len(pins) < 2:
                            continue
                        net_name = getattr(n, "name", None) or str(n)
                        is_power = any(pw in net_name.upper() for pw in ["GND", "VCC", "3V3", "5V", "VBAT", "PWR", "VSS", "VDD", "SOURCE"])
                        if is_power:
                            continue
                        for p in sorted(pins, key=_pin_sort_key):
                            px, py = part_placements.get(p.part, (0.0, 0.0))
                            lxw, lyw = _pin_world_xy(p, p.part, (px, py), label_resolver)
                            _emit_net_label(f, net_name, lxw + 2.54, lyw)

                for net_name, lx, ly in geom["labels"]:
                    is_power = any(n in net_name.upper() for n in ["GND", "VCC", "3V3", "5V", "VBAT", "PWR", "VSS", "VDD", "SOURCE"])
                    if is_power:
                        _emit_global_label(f, net_name, lx, ly)
                    else:
                        _emit_net_label(f, net_name, lx, ly)

                _emit_sheet_instances(f)
                _emit_symbol_instances(f, sym_paths=sym_instances)

                # Close root S-expression
                f.write(")\n")
        else:
            root_path = Path(output_path)
            stem = root_path.stem
            out_dir = root_path.parent

            # Group parts by owning module tag. Untagged parts stay on root.
            by_mod: dict[str, list] = {}
            for p in parts:
                by_mod.setdefault(_module_field(p), []).append(p)

            # Write root sheet with sheet symbols.
            with open(output_path, "w", encoding="utf-8") as f:
                _write_kicad_sch_header(f, file_uuid, embedded_lib_symbols)

                # Root-level parts (no module tag).
                root_parts = sorted(by_mod.get("", []) or [], key=_part_stable_key)
                for part in root_parts:
                    x, y = part_placements[part]
                    ref = str(getattr(part, "ref", "") or "?")
                    part_uuid = _uuid_for(f"symbol:{ref}")
                    _emit_symbol_instance(f, part, x, y, part_uuid)

                # Root-level wiring stays minimal; multi-sheet connectivity uses global labels.
                for net_name, lx, ly in _labels_for_module_sheet(circuit, "", part_placements, label_resolver):
                    _emit_net_label(f, net_name, lx, ly)

                # Emit sheet symbols (with pins) for each top-level module.
                mods = sorted([m for m in by_mod.keys() if m], key=lambda s: (s == "", s))
                sx, sy = 50.0, 40.0 # Centered-ish start
                sw = 80.0
                gap = 20.0
                sheet_inst: list[tuple[str, str]] = []
                for i, mod_name in enumerate(mods):
                    fname = f"{stem}.{_safe_sheet_filename(mod_name)}.kicad_sch"
                    x0 = sx
                    mod_obj = None
                    for mm in getattr(board, "modules", []) or []:
                        if str(getattr(mm, "name", "")) == mod_name:
                            mod_obj = mm
                            break
                    sheet_pins: list[str] = []
                    if mod_obj is not None:
                        for net in _interface_nets_for_module(mod_obj):
                            nn = str(getattr(net, "name", "") or "").strip()
                            if nn:
                                sheet_pins.append(nn)
                    
                    # Dynamic height based on pin count
                    sh = max(30.0, (len(sheet_pins) + 2) * 5.0)
                    y0 = sy
                    sy += sh + gap # Vertical stacking
                    
                    _emit_sheet_symbol(
                        f,
                        sheet_name=mod_name,
                        sheet_file=fname,
                        x=x0,
                        y=y0,
                        w=sw,
                        h=sh,
                        pin_names=sheet_pins or None,
                    )
                    # Best-effort: record subsheet instance by its schematic uuid key.
                    try:
                        sheet_uuid = _uuid_for(f"schematic:sheet:{mod_name}")
                        sheet_inst.append((f"/{sheet_uuid}", str(i + 2)))
                    except Exception:
                        pass

                _emit_sheet_instances(f, sheet_paths=sheet_inst)
                _emit_symbol_instances(f, sym_paths=[])
                f.write(")\n")

            # Write each subsheet: module’s parts + local wires + hierarchical labels for interface nets.
            for mod_name in mods:
                sheet_file = out_dir / f"{stem}.{_safe_sheet_filename(mod_name)}.kicad_sch"
                sheet_uuid = _uuid_for(f"schematic:sheet:{mod_name}")
                sheet_parts = sorted(by_mod.get(mod_name, []) or [], key=_part_stable_key)

                with open(sheet_file, "w", encoding="utf-8") as sf:
                    _write_kicad_sch_header(sf, sheet_uuid, embedded_lib_symbols)
                    sym_instances: list[tuple[str, str, str, str]] = []
                    for part in sheet_parts:
                        x, y = part_placements[part]
                        ref = str(getattr(part, "ref", "") or "?")
                        part_uuid = _uuid_for(f"symbol:{mod_name}:{ref}")
                        _emit_symbol_instance(sf, part, x, y, part_uuid)
                        try:
                            val = str(getattr(part, "value", None) or getattr(part, "name", None) or "").strip() or ref
                            fp = str(getattr(part, "footprint", None) or "").strip()
                            sym_instances.append((f"/{part_uuid}", ref, val, fp))
                        except Exception:
                            pass

                    # Local wiring: only nets fully contained in this module.
                    for net in sorted(list(circuit.nets), key=_net_stable_key):
                        pins = sorted_net_pins(net)
                        if len(pins) < 2:
                            continue
                        mods_on_net = {_module_field(p.part) for p in pins}
                        if mods_on_net == {mod_name}:
                            for i2 in range(len(pins) - 1):
                                a = pins[i2]
                                b2 = pins[i2 + 1]
                                ax, ay = part_placements.get(a.part, (0.0, 0.0))
                                bx, by = part_placements.get(b2.part, (0.0, 0.0))
                                axw, ayw = _pin_world_xy(a, a.part, (ax, ay), label_resolver)
                                bxw, byw = _pin_world_xy(b2, b2.part, (bx, by), label_resolver)
                                _emit_wire(sf, axw, ayw, bxw, byw)

                    # Hierarchical labels: for interface nets, place a hierarchical_label at first local pin.
                    mod_obj = None
                    for mm in getattr(board, "modules", None) or []:
                        if str(getattr(mm, "name", "")) == mod_name:
                            mod_obj = mm
                            break
                    if mod_obj is not None:
                        iface_net_names = []
                        seen = set()
                        for net in _interface_nets_for_module(mod_obj):
                            nn = str(getattr(net, "name", "") or "").strip()
                            if nn and nn not in seen:
                                seen.add(nn)
                                iface_net_names.append(nn)
                        for nn in iface_net_names[:40]:
                            # Find a pin in this module on that net.
                            net_obj = next((n for n in circuit.nets if (getattr(n, "name", None) or str(n)) == nn), None)
                            if net_obj is None:
                                continue
                            pins = sorted_net_pins(net_obj)
                            local_pin = next((p for p in pins if _module_field(p.part) == mod_name), None)
                            if local_pin is None:
                                continue
                            px, py = part_placements.get(local_pin.part, (0.0, 0.0))
                            lxw, lyw = _pin_world_xy(local_pin, local_pin.part, (px, py), label_resolver)
                            _emit_hierarchical_label(sf, name=nn, pin_type="passive", x=lxw + 2.54, y=lyw)
                            _emit_wire(sf, lxw, lyw, lxw + 2.54, lyw)

                    _emit_sheet_instances(sf)
                    _emit_symbol_instances(sf, sym_paths=sym_instances)
                    sf.write(")\n")

        logger.info("Schematic S-Expression document generated successfully.")

        if pinpos_report_path is not None and rec is not None:
            payload = {
                "schema": "openhac.sch_pinpos_report.v1",
                "resolved_pin_count": int(rec.resolved_pin_count),
                "stub_pin_count": int(rec.stub_pin_count),
                "by_symbol": dict(sorted(rec.by_symbol.items())),
            }
            Path(pinpos_report_path).write_text(
                json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
            )
    finally:
        if generated_symbol_lib_path:
            if prev_sym_dirs is None:
                os.environ.pop("OPENHAC_KICAD_SYMBOL_DIRS", None)
            else:
                os.environ["OPENHAC_KICAD_SYMBOL_DIRS"] = prev_sym_dirs
