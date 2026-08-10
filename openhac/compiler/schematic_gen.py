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
    # Default to deterministic for schematic stability (MFG-003)
    return _det_uuid(key)


class SchematicPinResolver(Protocol):
    def offset_for_pin(self, part, pin, symbol_name: str | None = None) -> tuple[float, float, float] | None: ...


@dataclass
class PartPlacement:
    part: object
    x: float
    y: float
    uuid: str


# KiCad A4 schematic usable area constants (mm).
# Actual A4 is 297x210; we leave margins for the title block and sheet border.
_SCH_MARGIN_MM: float = 25.0          # left/top margin before first component
_SCH_PAGE_W_MM: float = 260.0         # usable width on A4
_SCH_PAGE_H_MM: float = 170.0         # usable height on A4 (title block ~40mm at bottom)


def _schematic_layout_params() -> tuple[int, float]:
    """Columns per row and cell spacing (KiCad units) for schematic symbol placement.

    We use a single column (cols=1) so all components in a module stack vertically.
    This completely prevents horizontal text overflow between adjacent component labels.
    Cell spacing is pin-count-aware via _cell_spacing_for_part(), so large ICs
    automatically get more vertical room.
    Override with ``OPENHAC_SCHEMATIC_COLS_PER_ROW`` and ``OPENHAC_SCHEMATIC_CELL_SPACING``.
    """
    try:
        cols = int(os.environ.get("OPENHAC_SCHEMATIC_COLS_PER_ROW", "").strip() or 1)
    except Exception:
        cols = 1
    try:
        # Increased default spacing to 50.8 (2 inches) to prevent overlap in dense boards
        spacing = float(os.environ.get("OPENHAC_SCHEMATIC_CELL_SPACING", "").strip() or 60.96)
    except Exception:
        spacing = 60.96
    return max(1, cols), max(1.0, spacing)


def _cell_spacing_for_part(part, default: float = 30.0) -> float:
    """Return a per-part cell height that accounts for the number of pins."""
    pins = getattr(part, "pins", None)
    if pins is None:
        try:
            pins = part.get_pins()
        except Exception:
            pins = []
    
    # Correct pin count: handles list or dict (if indexed by both name/num)
    if isinstance(pins, dict):
        # Deduplicate pins if it's a dict (e.g. SKiDL Part.pins)
        n_pins = len(set(id(p) for p in pins.values()))
    else:
        n_pins = len(pins)

    # Rule: IC symbols grow vertically with pin count.
    # 40-pin RPi header is ~100mm; we need ~110mm cell to avoid stacking.
    # New Scaling: (n_pins / 2) * 5.08 + 15mm base
    h = max(default, (n_pins / 2) * 5.08 + 15.0)
    return min(h, 150.0) # Clamp to 150mm for extreme parts


def schematic_symbol_lib_key(part) -> str:
    """Symbol name used in generated ``.kicad_sch`` / ``lib_id`` (must match ``.kicad_sym``)."""
    # Check for custom symbol override from DB (e.g. jlc2kicad_generated:C1234)
    sym = getattr(part, "kicad_symbol", "") or ""
    if ":" in str(sym):
        return str(sym).split(":")[1]

    name = (getattr(part, "name", None) or "").strip()
    value = (getattr(part, "value", None) or "").strip()
    ref = (getattr(part, "refdes", None) or getattr(part, "ref", None) or "").strip()
    
    if name and name != "?":
        return name
    if value and value != "?" and not (len(value) <= 3 and value[0].isdigit()):
        # Use value if it looks like a part name, not just a small number/value like "10K"
        return value
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


def _assign_positions_grouped_by_module(parts, resolver: SchematicPinResolver | None = None) -> dict:
    """Place parts using a Topological Flow analysis to mimic professional EE signal flow."""
    try:
        import networkx as nx
        has_nx = True
    except ImportError:
        logger.debug("networkx not installed; falling back to stage-based BFS ranking.")
        has_nx = False

    cols, cell = _schematic_layout_params()
    groups: dict[str, list] = {}
    for p in parts:
        groups.setdefault(_module_field(p), []).append(p)

    module_names = sorted(groups.keys(), key=lambda s: (not s, s))
    positions: dict = {}
    
    # 50mil Snap Utility (1.27mm)
    def _snap(val: float) -> float:
        return round(val / 1.27) * 1.27

    cur_mod_y = 0.0
    for m in module_names:
        m_parts = groups[m]
        if not m_parts: continue

        # Identify Sources and Sinks for Topological Ranking
        sources = [p for p in m_parts if (str(getattr(p, "ref", "")).upper().startswith("J") or "CONN" in str(getattr(p, "name", "")).upper())]
        if not sources: sources = [m_parts[0]]

        from collections import deque
        ranks = {id(p): 0 for p in m_parts}
        queue = deque([(p, 0) for p in sources])
        visited = set()
        
        while queue:
            curr, r = queue.popleft()
            if id(curr) in visited: continue
            visited.add(id(curr))
            ranks[id(curr)] = max(ranks[id(curr)], r)
            
            pins = []
            if hasattr(curr, "get_pins"): pins = curr.get_pins()
            elif isinstance(getattr(curr, "pins", None), dict): pins = curr.pins.values()
            else: pins = getattr(curr, "pins", []) or []

            for pin in pins:
                net = getattr(pin, "net", None)
                if net is None: continue
                other_pins = []
                if hasattr(net, "get_pins"): other_pins = net.get_pins()
                elif isinstance(getattr(net, "pins", None), dict): other_pins = net.pins.values()
                else: other_pins = getattr(net, "pins", []) or []

                for other_pin in other_pins:
                    other_p = getattr(other_pin, "part", None)
                    if other_p and other_p in m_parts and id(other_p) not in visited:
                        queue.append((other_p, r + 1))

        stages = {}
        for p in m_parts:
            r = ranks.get(id(p), 0)
            stages.setdefault(r, []).append(p)
        
        sorted_stages = sorted(stages.keys())

        # SCH-002 / BUG-004: When no real connector sources exist, the BFS fallback
        # assigns sequential ranks to each part, spreading them across multiple horizontal
        # stages.  Parts that share a net then have different X positions, making every
        # wire an L-shaped 3-segment path even for simple 2-part circuits.  Collapse
        # into a single vertical column so connected parts with symmetric pin offsets are
        # axis-aligned and produce a single wire segment.
        has_real_sources = any(
            str(getattr(p, "ref", "")).upper().startswith("J") or
            "CONN" in str(getattr(p, "name", "")).upper()
            for p in m_parts
        )
        if not has_real_sources:
            all_parts_flat: list = []
            for s in sorted_stages:
                all_parts_flat.extend(stages[s])
            stages = {0: all_parts_flat}
            sorted_stages = [0]

        lpos = {}
        cur_x = 0.0
        
        max_mod_y = 0.0
        for stage_idx in sorted_stages:
            stage_parts = stages[stage_idx]
            # Use stable part ID for sorting within stage to keep order deterministic
            stage_parts.sort(key=lambda p: (str(getattr(p, "ref", "")).upper(), getattr(p, "_part_id", 0)))
            
            cur_y = 0.0
            for p in stage_parts:
                ph = _cell_spacing_for_part(p, cell)
                
                # PIN-FIRST ALIGNMENT (SCH-002)
                # Adjust part origin so its primary pin lands on the 1.27mm grid.
                px, py = cur_x, cur_y
                if resolver:
                    pins = p.get_pins() if hasattr(p, "get_pins") else (p.pins.values() if isinstance(getattr(p, "pins", None), dict) else getattr(p, "pins", []))
                    if pins:
                        # Logic: Use the first pin as the anchor for grid alignment
                        off = resolver.offset_for_pin(p, list(pins)[0])
                        if off:
                            # x_pin = x_origin + dx_pin => x_origin = x_pin_snapped - dx_pin
                            px = _snap(cur_x + off[0]) - off[0]
                            py = _snap(cur_y + off[1]) - off[1]
                
                lpos[p] = (px, py)
                # Rule: 12.7mm (0.5 inch) padding between parts vertically for native symbols
                cur_y += ph + 12.7
            
            max_mod_y = max(max_mod_y, cur_y)
            # Rule: 50.8mm (2 inch) gap between stages horizontally
            cur_x += 50.8

        for p, (lx, ly) in lpos.items():
            positions[p] = (lx, ly + cur_mod_y)
        
        # Rule: Advance the module vertical offset to prevent block overlap
        cur_mod_y += max_mod_y + 50.8

    return positions

def _part_stable_key(p) -> str:
    """Unique, deterministic key for sorting parts (refdes or object ID)."""
    ref = str(getattr(p, "refdes", None) or getattr(p, "ref", None) or "").strip()
    if not ref or ref == "?":
        return f"Z{getattr(p, '_part_id', 0):08d}"
    return ref


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
        'switch': _fuse_graphic(),  # TODO: implement a dedicated switch graphic (STYLE-004)
        'connector': _ic_graphic(name, pin_count, w_mm, h_mm),
        'ic': _ic_graphic(name, pin_count, w_mm, h_mm),
    }
    return graphics.get(sym_type, _ic_graphic(name, pin_count, w_mm, h_mm))


def write_generated_symbol_library(
    output_path: str, circuit_or_parts, *, nickname: str = "OpenHaC"
) -> tuple[str | None, str | None]:
    """Enterprise Phase B: Professional Symbol Library Generator."""
    parts = list(getattr(circuit_or_parts, "parts", None) or circuit_or_parts or [])
    if not parts:
        return None, None

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    def _get_ref_prefix(part) -> str:
        ref = str(getattr(part, 'refdes', '') or getattr(part, 'ref', '') or 'U')
        prefix = ''
        for c in ref:
            if c.isalpha(): prefix += c
            else: break
        return prefix.upper() if prefix else 'U'

    def _sym_header(outer_key: str, inner_base: str, ref_prefix: str, sym_type: str, pins: list) -> str:
        # Professional IC Synthesis: Bin pins by function
        # Professional IC Synthesis: Balanced Pin Distribution
        cats: dict[str, list[tuple[str, str, str]]] = {"left": [], "right": [], "power": [], "gnd": []}
        if sym_type in ("ic", "connector", "mcu", "fpga"):
            # Phase 1: Semantic Binning (Professional EE Style)
            for p in pins:
                pt = getattr(p, "pin_type", "").lower()
                pname = str(getattr(p, "name", "") or getattr(p, "num", ""))
                num = str(getattr(p, "num", "") or getattr(p, "number", ""))
                pn_up = pname.upper()
                if any(x in pn_up for x in ("GND", "VSS", "EARTH", "RETURN", "COMMON")): cats["gnd"].append((num, pname, "power_in"))
                elif any(x in pn_up for x in ("VCC", "VDD", "3V3", "5V", "12V", "24V", "VIN", "VBAT", "PWR")): cats["power"].append((num, pname, "power_in"))
                elif any(x in pn_up for x in ("OUT", "TX", "MISO", "SCK_OUT", "SDO", "PWM", "SCK", "MOSI")): cats["right"].append((num, pname, pt))
                else: cats["left"].append((num, pname, pt))
            
            # Phase 2: Balancing (Professional Aesthetics)
            all_signals = sorted(cats["left"] + cats["right"], key=lambda x: x[1])
            target = (len(all_signals) + 1) // 2
            cats["left"] = all_signals[:target]
            cats["right"] = all_signals[target:]
        else:
            # Passives: Simple 2-pin left/right
            cats["left"] = [(str(getattr(pins[i], "num", "") or i+1), str(getattr(pins[i], "name", "") or "1"), str(getattr(pins[i], "pin_type", ""))) for i in range(min(1, len(pins)))]
            if len(pins) > 1:
                cats["right"] = [(str(getattr(pins[1], "num", "") or 2), str(getattr(pins[1], "name", "") or "2"), str(getattr(pins[1], "pin_type", "")))]
        
        # Phase 3: Dimensions (Dynamic Professional Grade)
        n_pins_side = max(len(cats["left"]), len(cats["right"]))
        # Pro-Tip: Increased spacing to 5.08mm (200mil) as standard, 7.62mm for large modules
        spacing = 7.62 if len(pins) > 20 else 5.08
        
        h_mm = max((n_pins_side + 1) * spacing, 15.24)
        
        # Calculate width based on max label lengths
        max_left = max([len(p[1]) for p in cats["left"]] + [0])
        max_right = max([len(p[1]) for p in cats["right"]] + [0])
        # Force a minimum "Professional" width
        w_mm = max(30.48, (max_left + max_right) * 1.8 + 10.16)
        
        graphic = _get_graphic_for_type(sym_type, inner_base, len(pins), w_mm, h_mm)
        h = h_mm / 2
        
        header = (
            f'  (symbol "{outer_key}" (in_bom yes) (on_board yes)\n'
            f'    (property "Reference" "{ref_prefix}?" (at 0 {h + 2.54:.3f} 0) (effects (font (size 1.27 1.27))))\n'
            f'    (property "Value" "{inner_base}" (at 0 -{h + 2.54:.3f} 0) (effects (font (size 1.27 1.27))))\n'
            f'    (symbol "{inner_base}_0_1"\n'
            f'{graphic}\n'
        )
        
        pin_lines = []
        left_x, right_x = -(w_mm / 2), (w_mm / 2)
        top_y, bottom_y = -(h_mm / 2), (h_mm / 2)
        
        def _pin_block(num, name, x, y, rot, ptype):
            pname_esc = str(name).replace('"', '\\"')
            pnum_esc = str(num).replace('"', '\\"')
            
            # [Professional Cleanup] Suppress generic pin names that add no value
            # If name is P1, Pin_1, etc, and number is 1, hide name to reduce clutter
            hide_name = False
            clean_name = str(name).strip().upper()
            if clean_name in (f"P{num}", f"PIN_{num}", f"PIN{num}", str(num)):
                hide_name = True
            
            # KiCad-legal pin types (S-expression spec)
            VALID_TYPES = {
                "input", "output", "bidirectional", "tri_state", "passive", 
                "unspecified", "power_in", "power_out", "open_collector", 
                "open_emitter", "free", "no_connect"
            }
            # Common vendor mapping normalization
            MAPPING = {
                "power": "power_in", "analog": "passive", "digital": "bidirectional",
                "tristate": "tri_state", "3state": "tri_state", "nc": "no_connect"
            }
            raw_t = str(ptype or "bidirectional").lower().replace(" ", "_")
            t = MAPPING.get(raw_t, raw_t)
            if t not in VALID_TYPES:
                t = "unspecified"

            name_effects = '(effects (font (size 1.27 1.27))' + (' (hide yes))' if hide_name else ')')
            return (
                f'      (pin {t} line (at {x:.3f} {y:.3f} {rot}) (length 2.54)\n'
                f'        (name "{pname_esc}" {name_effects})\n'
                f'        (number "{pnum_esc}" (effects (font (size 1.27 1.27))))\n'
                f'      )'
            )

        def _dist(plist, x_fixed, y_fixed, rot, is_vert):
            lines = []
            if not plist: return lines
            # Use the dynamically calculated spacing (global to header scope)
            start = -((len(plist)-1)*spacing)/2
            for i, (pnum, pname, ptype) in enumerate(plist):
                offset = start + i*spacing
                if is_vert: lines.append(_pin_block(pnum, pname, x_fixed, offset, rot, ptype))
                else: lines.append(_pin_block(pnum, pname, offset, y_fixed, rot, ptype))
            return lines

        if sym_type in ("ic", "connector", "mcu"):
            # Professional KiCad Rotation Spec (FIXED):
            # Pins on Left side point LEFT (180 deg) to exit the body
            # Pins on Right side point RIGHT (0 deg) to exit the body
            pin_lines.extend(_dist(cats["left"], left_x, 0, 180, True))
            pin_lines.extend(_dist(cats["right"], right_x, 0, 0, True))
            pin_lines.extend(_dist(cats["power"], 0, top_y, 90, False))
            pin_lines.extend(_dist(cats["gnd"], 0, bottom_y, 270, False))
        else:
            # Passives: Pin 1 Left (point 180 left), Pin 2 Right (point 0 right)
            if cats["left"]:
                pnum, pname, ptype = cats["left"][0]
                pin_lines.append(_pin_block(pnum, pname, -5.08, 0, 180, ptype))
            if cats["right"]:
                pnum, pname, ptype = cats["right"][0]
                pin_lines.append(_pin_block(pnum, pname, 5.08, 0, 0, ptype))

        return header + "\n".join(pin_lines) + "\n    )\n  )\n"

    names = sorted({schematic_symbol_lib_key(p) for p in parts})
    if not names: return None, None
    by_name = {schematic_symbol_lib_key(p): p for p in parts}

    lines = ['(kicad_symbol_lib (version 20231120) (generator openhac)\n']
    embed_chunks: list[str] = []
    
    for name in names:
        part = by_name[name]
        
        # Professional Grade: Skip synthetic generation for native KiCad symbols
        lib_nick = part_library_name(part)
        if lib_nick in ("Device", "power"):
            continue
            
        val = str(getattr(part, 'value', '') or name)
        ref_prefix = _get_ref_prefix(part)
        stype = _detect_symbol_type(part)
        pins = part.get_pins() if hasattr(part, "get_pins") else (part.pins.values() if isinstance(getattr(part, "pins", None), dict) else getattr(part, "pins", []))
        
        # Local library symbol
        sym_body = _sym_header(name, name, ref_prefix, stype, pins)
        lines.append(sym_body)
        
        # Embedded symbol (prefixed with nickname)
        embed_sym = _sym_header(f"{nickname}:{name}", name, ref_prefix, stype, pins)
        embed_chunks.append(embed_sym)

    lines.append(')\n')
    out.write_text("".join(lines), encoding="utf-8")
    
    def _nest(body: str) -> str:
        return "\n".join("  " + l if l.strip() else l for l in body.splitlines())
    
    return str(out), _nest("".join(embed_chunks))




# Global set to track wire endpoints for junction dot detection
_wire_endpoints: set[tuple[float, float]] = set()
_junction_candidates: set[tuple[float, float]] = set()

from contextlib import contextmanager

@contextmanager
def _junction_tracking_context():
    _wire_endpoints.clear()
    _junction_candidates.clear()
    try:
        yield
    finally:
        _wire_endpoints.clear()
        _junction_candidates.clear()

def _register_wire_segment(x1, y1, x2, y2):
    p1, p2 = (round(x1, 2), round(y1, 2)), (round(x2, 2), round(y2, 2))
    for p in (p1, p2):
        if p in _wire_endpoints:
            _junction_candidates.add(p)
        else:
            _wire_endpoints.add(p)


def _snap(val: float) -> float:
    """Snap coordinate to standard 50mil (1.27mm) grid."""
    return round(val / 1.27) * 1.27

def _emit_symbol_instance(f, part, x, y, uuid_str: str) -> None:
    sym_name = schematic_symbol_lib_key(part)
    lib_nick = part_library_name(part)
    # Professional Grade: Allow native KiCad library symbols to render
    if not lib_nick:
        lib_nick = "OpenHaC"
    lib_id = f"{lib_nick}:{sym_name}"
    
    # Universal Rotation Logic based on Pin Function
    rot = 0.0
    pins = part.get_pins() if hasattr(part, "get_pins") else (part.pins.values() if isinstance(getattr(part, "pins", None), dict) else getattr(part, "pins", []))
    
    has_pwr = False
    has_gnd = False
    for pin in pins:
        pname = str(getattr(pin, "name", "")).upper()
        if any(n in pname for n in ["VCC", "3V3", "5V", "VIN", "PWR", "VDD"]):
            has_pwr = True
        if "GND" in pname or "VSS" in pname:
            has_gnd = True
    
    # Spec 3.2: Passive Alignment
    # Horizontal: Default for signal path components
    # Vertical: Automatic for components connected to Power or GND
    if (has_pwr or has_gnd) and len(pins) <= 2:
        rot = 90.0 # Vertical for Decoupling/Pull-ups
    else:
        rot = 0.0  # Horizontal for Signal Path (In-line resistors)

    f.write(f'  (symbol (lib_id "{lib_id}") (at {_fmt_mm(_snap(x))} {_fmt_mm(_snap(y))} {rot})\n')
    f.write('    (in_bom yes) (on_board yes) (fields_autoplaced yes)\n')
    f.write(f'    (uuid "{uuid_str}")\n')
    
    rd = getattr(part, "refdes", None)
    if not rd or str(rd).strip() == "?":
        rd = getattr(part, "ref", None)
    
    if not rd or str(rd).strip() == "?":
        rd = getattr(part, "name", "U?")


    
    # Correct field positions based on rotation
    h_est = (len(pins) // 2) * 2.54
    # Logic: If RefDes is missing, indicate it clearly in the Value field to aid debugging
    ref = str(rd).strip()
    val_attr = getattr(part, "value", None) or getattr(part, "name", None) or ""
    if not ref or ref == "?" or ref.startswith("U?"):
        val = f"{str(val_attr).strip()} (UNNAMED)"
    else:
        val = str(val_attr).strip() or ref
    fp = str(getattr(part, "footprint", None) or "").strip()
    
    ref_y = -h_est/2 - 2.54 if rot == 0 else -5.08
    val_y = h_est/2 + 2.54 if rot == 0 else 5.08

    f.write(f'    (property "Reference" "{ref}" (id 0) (at {_fmt_mm(_snap(x))} {_fmt_mm(_snap(y + ref_y))} 0)\n')
    f.write('      (effects (font (size 1.27 1.27) (thickness 0.15)))\n')
    f.write('    )\n')
    f.write(f'    (property "Value" "{val}" (id 1) (at {_fmt_mm(_snap(x))} {_fmt_mm(_snap(y + val_y))} 0)\n')
    f.write('      (effects (font (size 1.27 1.27) (thickness 0.15)))\n')
    f.write('    )\n')
    f.write(f'    (property "Footprint" "{fp}" (id 2) (at {_fmt_mm(_snap(x))} {_fmt_mm(_snap(y + val_y + 2.54))} 0) (effects (font (size 1.27 1.27)) (hide yes)))\n')
    f.write(f'    (property "Datasheet" "" (id 3) (at {_fmt_mm(_snap(x))} {_fmt_mm(_snap(y + val_y + 5.08))} 0) (effects (font (size 1.27 1.27)) (hide yes)))\n')
    f.write('  )\n')

def _emit_wire(f, x1: float, y1: float, x2: float, y2: float) -> None:
    if abs(x1 - x2) < 0.001 and abs(y1 - y2) < 0.001:
        return
    x1, y1, x2, y2 = _snap(x1), _snap(y1), _snap(x2), _snap(y2)
    _register_wire_segment(x1, y1, x2, y2)
    wire_uuid = _uuid_for(f"wire:{x1:.4f},{y1:.4f}:{x2:.4f},{y2:.4f}")
    f.write(f'  (wire (pts (xy {_fmt_mm(x1)} {_fmt_mm(y1)}) (xy {_fmt_mm(x2)} {_fmt_mm(y2)}))\n')
    f.write('    (stroke (width 0) (type default))\n')
    f.write(f'    (uuid "{wire_uuid}")\n')
    f.write('  )\n')

def _emit_junction(f, x: float, y: float) -> None:
    x, y = _snap(x), _snap(y)
    j_uuid = _uuid_for(f"junction:{x:.4f},{y:.4f}")
    f.write(f'  (junction (at {_fmt_mm(x)} {_fmt_mm(y)}) (diameter 0) (color 0 0 0 0) (uuid "{j_uuid}"))\n')

def _emit_orthogonal_path(f, x1: float, y1: float, x2: float, y2: float, rot1: float = 0, rot2: float = 0) -> None:
    x1, y1, x2, y2 = _snap(x1), _snap(y1), _snap(x2), _snap(y2)
    if abs(x1 - x2) < 0.01 or abs(y1 - y2) < 0.01:
        _emit_wire(f, x1, y1, x2, y2)
        return
    mid_x = _snap((x1 + x2) / 2)
    _emit_wire(f, x1, y1, mid_x, y1)
    _emit_wire(f, mid_x, y1, mid_x, y2)
    _emit_wire(f, mid_x, y2, x2, y2)


def _emit_sheet_instances(f, *, sheet_paths: list[tuple[str, str]] | None = None) -> None:
    f.write("  (sheet_instances\n")
    f.write('    (path "/" (page "1"))\n')
    for p, page in (sheet_paths or []):
        sp = str(p or "").strip()
        if not sp.startswith("/"):
            sp = "/" + sp
        f.write(f'    (path "{kicad_string_escape(sp)}" (page "{kicad_string_escape(str(page))}"))\n')
    f.write("  )\n")


def _emit_symbol_instances(f, *, sym_paths: list[tuple[str, str, str, str]] | None = None) -> None:
    f.write("  (symbol_instances\n")
    for path, ref, val, fp in (sym_paths or []):
        p = str(path or "").strip() or "/"
        if not p.startswith("/"):
            p = "/" + p
        f.write(f'    (path "{kicad_string_escape(p)}" (reference "{kicad_string_escape(ref)}") '
                f'(unit 1) (value "{kicad_string_escape(val)}") (footprint "{kicad_string_escape(fp)}"))\n')
    f.write("  )\n")


def _pin_world_xy(pin, part, part_xy: tuple[float, float], resolver: SymbolPinResolver | None) -> tuple[float, float, float]:
    x0, y0 = part_xy
    if resolver is not None:
        name = schematic_symbol_lib_key(part)
        off = resolver.offset_for_pin(part, pin, symbol_name=name)
        if off is not None:
            return x0 + off[0], y0 + off[1], off[2]
            
    # SMART FALLBACK: Dual-Column IC Layout
    # Logic: Even pins on Left (-10.16mm), Odd pins on Right (+10.16mm)
    # This prevents label stacking and creates a standard "chip" look.
    pins = part.get_pins() if hasattr(part, "get_pins") else (part.pins.values() if isinstance(getattr(part, "pins", None), dict) else getattr(part, "pins", []))
    try:
        idx = 0
        for i, p in enumerate(pins):
            if p is pin:
                idx = i
                break
    except Exception:
        idx = 0

    # IC Heuristic: 2.54mm pitch (100mil)
    row = idx // 2
    is_right = (idx % 2) == 1
    
    # 30.48mm (1200mil) width for the synthetic box to handle long labels
    dx = 15.24 if is_right else -15.24
    dy = row * 2.54
    rot = 180.0 if is_right else 0.0 # connection points face inward
    
    return x0 + dx, y0 + dy, rot


def _pin_index_on_part(pin) -> int:
    part = getattr(pin, "part", None)
    if part is None:
        return 0
    try:
        pins = part.get_pins() if hasattr(part, "get_pins") else (part.pins.values() if isinstance(getattr(part, "pins", None), dict) else getattr(part, "pins", []))
        for idx, p in enumerate(pins):
            if p is pin:
                return idx
    except Exception:
        pass
    return 0


_PIN_NAT_SPLIT = re.compile(r"(\d+|\D+)")


def _pin_number_natural_key(s: str) -> tuple:
    parts: list[tuple[int, int | str]] = []
    for chunk in _PIN_NAT_SPLIT.findall(str(s)):
        if chunk.isdigit():
            parts.append((0, int(chunk)))
        else:
            parts.append((1, chunk.lower()))
    return tuple(parts)


def _pin_sort_key(pin) -> tuple:
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
    pins = [p for p in net.pins if getattr(p, "part", None) is not None]
    return sorted(pins, key=_pin_sort_key)


def kicad_string_escape(text: str | None) -> str:
    r"""Escape *text* for KiCad schematic double-quoted strings (\\ and \")."""
    s = str(text or "").replace("\\", "\\\\").replace('"', '\\"')
    return s


def net_connectivity_signatures(circuit) -> dict[str, frozenset[tuple[str, str]]]:
    out: dict[str, frozenset[tuple[str, str]]] = {}
    for net in circuit.nets:
        pins = net.get_pins() if hasattr(net, "get_pins") else (net.pins.values() if isinstance(getattr(net, "pins", None), dict) else getattr(net, "pins", []))
        if not pins:
            continue
        name = getattr(net, "name", None) or str(net)
        sig = frozenset(
            (getattr(p.part, "ref", "?"), str(getattr(p, "num", "?")))
            for p in pins
            if getattr(p, "part", None) is not None
        )
        out[name] = sig
    return out


def schematic_geometry(circuit, *, symbol_resolver: SchematicPinResolver | None = None) -> dict:
    if symbol_resolver is not None:
        resolver: SchematicPinResolver = symbol_resolver
    else:
        resolver = EmptySymbolPinResolver() if _truthy_env("OPENHAC_SCHEMATIC_STUB_ONLY") else SymbolPinResolver()
    parts = sorted(list(circuit.parts), key=_part_stable_key)
    positions = _assign_positions_grouped_by_module(parts, resolver=resolver)
    wires: list[tuple[float, float, float, float]] = []
    labels: list[tuple[str, float, float]] = []
    
    # We need a stable placement for all parts to do geometry
    part_placements = positions
    
    for net in sorted(list(circuit.nets), key=_net_stable_key):
        pins = sorted_net_pins(net)
        if len(pins) < 2:
            continue
        net_name = getattr(net, "name", None) or str(net)
        if _is_power_net(net_name):
            for pin in pins:
                if pin.part not in part_placements: continue
                px, py = part_placements[pin.part]
                pxw, pyw, prot = _pin_world_xy(pin, pin.part, (px, py), resolver)
                pxw, pyw = _snap(pxw), _snap(pyw)
                # Power stub: draw a short line and place a power symbol
                if abs(pxw - px) < 0.1:
                    dy = -5.08 if pyw < py else 5.08
                    wires.append((pxw, pyw, pxw, pyw + dy))
                    labels.append((net_name, pxw, pyw + dy))
                else:
                    dx = -5.08 if pxw < px else 5.08
                    wires.append((pxw, pyw, pxw + dx, pyw))
                    labels.append((net_name, pxw + dx, pyw))
        else:
            for i in range(len(pins) - 1):
                pin_a, pin_b = pins[i], pins[i + 1]
                if pin_a.part not in part_placements or pin_b.part not in part_placements: continue
                ax, ay = part_placements[pin_a.part]
                bx, by = part_placements[pin_b.part]
                axw, ayw, arot = _pin_world_xy(pin_a, pin_a.part, (ax, ay), resolver)
                bxw, byw, brot = _pin_world_xy(pin_b, pin_b.part, (bx, by), resolver)
                axw, ayw, bxw, byw = _snap(axw), _snap(ayw), _snap(bxw), _snap(byw)
                if abs(axw - bxw) < 0.01 or abs(ayw - byw) < 0.01:
                    # Same row/column: direct wire (matches _emit_orthogonal_path short-circuit)
                    if abs(axw - bxw) > 0.001 or abs(ayw - byw) > 0.001:
                        wires.append((axw, ayw, bxw, byw))
                else:
                    mid_x = _snap((axw + bxw) / 2)
                    for x1, y1, x2, y2 in [(axw, ayw, mid_x, ayw), (mid_x, ayw, mid_x, byw), (mid_x, byw, bxw, byw)]:
                        if abs(x1 - x2) > 0.001 or abs(y1 - y2) > 0.001:
                            wires.append((x1, y1, x2, y2))
            # Label placed at midpoint of first wire pair (matches the single-label emitter).
            # Only for multi-pin nets (>= 3): 2-pin point-to-point wires are self-documenting.
            if len(pins) >= 3 and pins[0].part in part_placements and pins[1].part in part_placements:
                ax0, ay0 = part_placements[pins[0].part]
                bx0, by0 = part_placements[pins[1].part]
                axw0, ayw0, _ = _pin_world_xy(pins[0], pins[0].part, (ax0, ay0), resolver)
                bxw0, byw0, _ = _pin_world_xy(pins[1], pins[1].part, (bx0, by0), resolver)
                axw0, ayw0 = _snap(axw0), _snap(ayw0)
                bxw0, byw0 = _snap(bxw0), _snap(byw0)
                lx_mid = _snap((axw0 + bxw0) / 2)
                ly_mid = _snap((ayw0 + byw0) / 2)
                labels.append((net_name, lx_mid, ly_mid))
    return {"part_placements": positions, "wires": wires, "labels": labels}


class _RecordingPinResolver:
    __slots__ = ("_inner", "resolved_pin_count", "stub_pin_count", "by_symbol")
    def __init__(self, inner: SchematicPinResolver):
        self._inner = inner
        self.resolved_pin_count: int = 0
        self.stub_pin_count: int = 0
        self.by_symbol: dict[str, dict[str, int]] = {}
    def offset_for_pin(self, part, pin, symbol_name: str | None = None) -> tuple[float, float, float] | None:
        off = self._inner.offset_for_pin(part, pin, symbol_name=symbol_name)
        lib = part_library_name(part)
        sname = symbol_name or (getattr(part, "name", "") or "")
        key = f"{lib}:{sname}"
        stats = self.by_symbol.setdefault(key, {"resolved": 0, "stub": 0})
        from openhac.compiler.kicad_sym_pinpos import EmptySymbolPinResolver

        if off is not None and not isinstance(self._inner, EmptySymbolPinResolver):
            self.resolved_pin_count += 1
            stats["resolved"] += 1
        else:
            self.stub_pin_count += 1
            stats["stub"] += 1
        return off


def _is_power_net(net_name: str) -> bool:
    _POWER_NET_KEYWORDS = ("GND", "VCC", "3V3", "3.3V", "5V", "5.0V", "VBAT", "VBUS", "PWR", "VSS", "VDD", "VIN", "VOUT", "12V", "15V", "24V", "SOURCE")
    upper = net_name.upper()
    return any(kw in upper for kw in _POWER_NET_KEYWORDS)


def _emit_no_connect(f, x, y) -> None:
    nc_uuid = _uuid_for(f"noconn:{x:.4f},{y:.4f}")
    f.write(f'  (no_connect (at {_fmt_mm(x)} {_fmt_mm(y)}) (uuid "{nc_uuid}"))\n')

def _emit_power_symbol(f, name: str, x: float, y: float, is_gnd: bool = False) -> None:
    dy = 5.08 if is_gnd else -5.08
    _emit_wire(f, x, y, x, y + dy)
    lib_name = "power:GND" if is_gnd else "power:VCC"
    f.write(f'  (symbol (lib_id "{lib_name}") (at {_fmt_mm(x)} {_fmt_mm(y + dy)} 0) (unit 1)\n')
    f.write('    (in_bom no) (on_board yes) (fields_autoplaced yes)\n')
    f.write(f'    (uuid "{_uuid_for(f"pwr:{name}:{x}:{y}")}")\n')
    f.write(f'    (property "Reference" "#PWR?" (id 0) (at {_fmt_mm(x)} {_fmt_mm(y + dy + 1.27)} 0) (effects (font (size 1.27 1.27)) (hide yes)))\n')
    f.write(f'    (property "Value" "{name}" (id 1) (at {_fmt_mm(x)} {_fmt_mm(y + dy + (2.54 if is_gnd else -2.54))} 0) (effects (font (size 1.27 1.27))))\n')
    f.write('  )\n')

def _emit_hierarchical_label(f, name: str, pin_type: str, x: float, y: float) -> None:
    _emit_wire(f, x, y, x + 5.08, y)
    lx = x + 5.08
    # Use caller-supplied shape; KiCad expects it to match the corresponding sheet pin type.
    safe_shape = pin_type if pin_type in (
        "input", "output", "bidirectional", "tri_state", "passive", "unspecified"
    ) else "passive"
    f.write(f'  (hierarchical_label "{kicad_string_escape(name)}" (shape {safe_shape}) (at {_fmt_mm(lx)} {_fmt_mm(y)} 0)\n')
    f.write('    (effects (font (size 1.27 1.27)) (justify left))\n')
    f.write(f'    (uuid "{_uuid_for(f"hlabel:{name}:{x}:{y}")}")\n')
    f.write('  )\n')

def _emit_hierarchical_pin(f, name: str, pin_type: str, x: float, y: float, idx: int) -> None:
    # Use the caller-supplied pin_type (defaulting to 'passive' for generic interface nets)
    # so KiCad ERC does not flag bidirectional-type mismatches (BUG-004 fix).
    safe_type = pin_type if pin_type in (
        "input", "output", "bidirectional", "tri_state", "passive",
        "unspecified", "power_in", "power_out", "open_collector", "open_emitter", "no_connect"
    ) else "passive"
    f.write(f'    (pin "{kicad_string_escape(name)}" {safe_type} (at {_fmt_mm(x)} {_fmt_mm(y)} 0)\n')
    f.write('      (effects (font (size 1.27 1.27)) (justify left))\n')
    f.write(f'      (uuid "{_uuid_for(f"hpin:{name}:{idx}")}")\n')
    f.write('    )\n')


def _write_kicad_sch_header(f, file_uuid: str, embedded_lib_symbols: str | None) -> None:
    f.write('(kicad_sch (version 20231120) (generator openhac)\n')
    f.write(f'  (uuid "{file_uuid}")\n')
    f.write('  (paper "A4")\n')
    
    # Professional Tier: Embed standard power symbols so they always resolve
    pwr_syms = """    (symbol "power:GND" (power) (pin_names (offset 0)) (in_bom no) (on_board yes)
      (property "Reference" "#PWR" (at 0 -6.35 0) (effects (font (size 1.27 1.27)) (hide yes)))
      (property "Value" "GND" (at 0 -3.81 0) (effects (font (size 1.27 1.27))))
      (symbol "GND_0_1"
        (polyline (pts (xy 0 0) (xy 0 -1.27)) (stroke (width 0)))
        (polyline (pts (xy -1.27 -1.27) (xy 1.27 -1.27) (xy 0 -2.54) (xy -1.27 -1.27)) (stroke (width 0)) (fill (type outline)))
      )
      (pin power_in line (at 0 0 270) (length 0) (name "GND" (effects (font (size 1.27 1.27)))) (number "1" (effects (font (size 1.27 1.27)))))
    )
    (symbol "power:VCC" (power) (pin_names (offset 0)) (in_bom no) (on_board yes)
      (property "Reference" "#PWR" (at 0 3.81 0) (effects (font (size 1.27 1.27)) (hide yes)))
      (property "Value" "VCC" (at 0 3.81 0) (effects (font (size 1.27 1.27))))
      (symbol "VCC_0_1"
        (polyline (pts (xy 0 0) (xy 0 1.27)) (stroke (width 0)))
        (circle (center 0 1.27) (radius 0.635) (stroke (width 0)) (fill (type none)))
      )
      (pin power_in line (at 0 0 90) (length 0) (name "VCC" (effects (font (size 1.27 1.27)))) (number "1" (effects (font (size 1.27 1.27)))))
    )
"""
    f.write("  (lib_symbols\n")
    if pwr_syms: f.write(pwr_syms)
    if embedded_lib_symbols: f.write(embedded_lib_symbols)
    f.write("  )\n")

def _interface_nets_for_module(module) -> list:
    """Return list of nets that cross the module boundary (connect to parts outside)."""
    nets = []
    mod_parts = []
    all_circuit_parts = []
    
    # We need access to all parts in the circuit to check boundary crossing
    from openhac.circuit import get_default_circuit
    circuit = get_default_circuit()
    all_circuit_parts = list(circuit.parts)

    if hasattr(module, "components"):
        for comp in getattr(module, "components", []) or []:
            part = getattr(comp, "part", None)
            if part: mod_parts.append(part)
    elif isinstance(module, list):
        mod_parts = module
    
    mod_part_ids = {id(p) for p in mod_parts}
    seen_nets = set()
    
    # 1. Add all explicitly declared interface nets
    if hasattr(module, "required_interfaces"):
        for ifaces in (getattr(module, "required_interfaces", {}), getattr(module, "optional_interfaces", {})):
            for iface in ifaces.values():
                for net in list(iface.signals) + list(iface.named_signals.values()):
                    if net and id(net) not in seen_nets:
                        seen_nets.add(id(net))
                        nets.append(net)
    
    for part in mod_parts:
        pins = part.get_pins() if hasattr(part, "get_pins") else (part.pins.values() if isinstance(getattr(part, "pins", None), dict) else getattr(part, "pins", []))
        for pin in pins:
            net = getattr(pin, "net", None)
            if not net or id(net) in seen_nets:
                continue
            
            # Boundary Crossing Check: Does this net connect to ANY part outside this module?
            net_pins = net.get_pins() if hasattr(net, "get_pins") else (net.pins if hasattr(net, "pins") else [])
            crosses = False
            for np in net_pins:
                p_other = getattr(np, "part", None)
                if p_other and id(p_other) not in mod_part_ids:
                    crosses = True
                    break
            
            if crosses:
                seen_nets.add(id(net))
                nets.append(net)
                
    return sorted(nets, key=_net_stable_key)

def _emit_title_block(f, title: str, version: str = "v1.0.0") -> None:
    from datetime import datetime
    date_str = datetime.now().strftime("%Y-%m-%d")
    f.write('  (title_block\n')
    f.write(f'    (title "{kicad_string_escape(title)}")\n')
    f.write(f'    (date "{date_str}")\n')
    f.write(f'    (rev "{kicad_string_escape(version)}")\n')
    f.write('    (company "OpenHaC Hardware Compiler")\n')
    f.write('    (comment 1 "Fabrication Ready - Automated Synthesis")\n')
    f.write('  )\n')

def _is_significant_net(net) -> bool:
    """Filter for nets that warrant a visible text label."""
    n = (getattr(net, "name", None) or str(net)).upper().strip()
    if n.startswith("N$") or n.startswith("NET_") or n.isdigit(): return False
    # Power and NC nets use specialized symbols, not text labels
    if any(p in n for p in ("GND", "VSS", "VCC", "VDD", "3V3", "5V", "NC")): return False
    return True

def _get_label_shape(name: str) -> str:
    """Choose contextual shape for global labels based on semantic keywords."""
    n = name.upper()
    # Power and Passive Nets (High current, ground, etc)
    if any(p in n for p in ("GND", "VSS", "VCC", "VDD", "3V3", "5V", "12V", "VIN", "VBAT", "PWR")):
        return "passive"
    # Outputs (Pointing out)
    if any(o in n for o in ("TX", "MOSI", "SCK", "SDO", "PWM_OUT", "DAC_OUT")):
        return "output"
    # Inputs (Pointing in)
    if any(i in n for i in ("RX", "MISO", "SDI", "DATA_IN", "ADC_IN", "SENSOR_SIG")):
        return "input"
    # Bidirectional (Double chevron) for I2C, SPI CS, etc.
    if any(b in n for b in ("SDA", "SCL", "CS", "CAN", "USB")):
        return "bidirectional"
    # Fallback to passive for generic logic signals
    return "passive"

def _emit_net_label(f, net, x: float, y: float) -> None:
    """Emit the appropriate KiCad label type for *net* at (*x*, *y*).

    - GND / VSS nets     → power:GND symbol
    - Power / VCC nets   → power:VCC symbol  
    - Signal nets        → plain ``(label ...)``  ← what KiCad ERC expects for local nets
    """
    name = getattr(net, "name", None) or str(net)
    ntype = getattr(net, "_openhac_net_type", "signal")
    x, y = _snap(x), _snap(y)
    uuid_str = _uuid_for(f"label:{name}:{x}:{y}")
    n_upper = name.upper()

    if ntype == "gnd" or any(kw in n_upper for kw in ("GND", "VSS")):
        f.write(f'  (symbol (lib_id "power:GND") (at {_fmt_mm(x)} {_fmt_mm(y)} 0) (uuid "{uuid_str}")\n')
        f.write('    (in_bom no) (on_board yes) (fields_autoplaced yes)\n')
        f.write(f'    (property "Reference" "#PWR?" (id 0) (at {_fmt_mm(x)} {_fmt_mm(y + 2.54)} 0) (effects (font (size 1.27 1.27)) (hide yes)))\n')
        f.write(f'    (property "Value" "{name}" (id 1) (at {_fmt_mm(x)} {_fmt_mm(y + 1.27)} 0) (effects (font (size 1.27 1.27))))\n')
        f.write('  )\n')
        return

    is_power = ntype == "power" or _is_power_net(n_upper)

    if is_power:
        _emit_power_symbol(f, name, x, y, is_gnd="GND" in n_upper)
    else:
        # Plain local label — KiCad ERC treats these as local-scope labels which is
        # correct for intra-sheet signal routing.  global_label is reserved for
        # cross-sheet / hierarchical connections and causes ERC noise on flat designs.
        name_esc = kicad_string_escape(name)
        label_uuid = _uuid_for(f"label:{name}:{x}:{y}")
        f.write(f'  (label "{name_esc}" (at {_fmt_mm(x)} {_fmt_mm(y)} 0)\n')
        f.write('    (effects (font (size 1.27 1.27)) (justify left))\n')
        f.write(f'    (uuid "{label_uuid}")\n')
        f.write('  )\n')

def generate_schematic(output_path: str, board, *, symbol_resolver: SchematicPinResolver | None = None, pinpos_report_path: str | None = None, generated_symbol_lib_path: str | None = None, embedded_lib_symbols: str | None = None) -> None:
    logger.info(f"Synthesizing Logic Graph into 2D Schematic Array -> {output_path}")
    project_name = getattr(board, "project_name", "OpenHaC Project")
    project_rev = getattr(board, "release_tag", "v1.0")

    class _BoardCircuitView:
        def __init__(self, parts, nets):
            self.parts = parts
            self.nets = nets
    parts = []
    seen_parts = set()

    def _collect_parts(node):
        from openhac.core.base import Component
        from openhac.core.module import Module
        
        # Board has 'modules', Modules have 'components'
        items = []
        if isinstance(node, Module):
            items = getattr(node, "components", []) or []
        elif hasattr(node, "modules"): # Board
            items = getattr(node, "modules", []) or []
            
        for item in items:
            if isinstance(item, Component):
                part = getattr(item, "part", None)
                if part is not None and id(part) not in seen_parts:
                    seen_parts.add(id(part))
                    parts.append(part)
            elif isinstance(item, Module):
                _collect_parts(item)

    _collect_parts(board)
    if not parts:
        from openhac.circuit import get_default_circuit
        c = get_default_circuit()
        parts = list(c.parts)
    
    nets = set()
    for part in parts:
        pins = part.get_pins() if hasattr(part, "get_pins") else (part.pins.values() if isinstance(getattr(part, "pins", None), dict) else getattr(part, "pins", []))
        for pin in pins:
            n = getattr(pin, "net", None)
            if n is not None: nets.add(n)
    circuit = _BoardCircuitView(tuple(parts), tuple(sorted(nets, key=_net_stable_key)))
    file_uuid = _uuid_for("schematic:file")

    prev_sym_dirs = os.environ.get("OPENHAC_KICAD_SYMBOL_DIRS")
    if generated_symbol_lib_path:
        d = str(Path(generated_symbol_lib_path).resolve().parent)
        os.environ["OPENHAC_KICAD_SYMBOL_DIRS"] = (d + os.pathsep + prev_sym_dirs) if prev_sym_dirs else d

    rec = None  # _RecordingPinResolver — initialized inside try block below
    try:
        if symbol_resolver is None:
            symbol_resolver = EmptySymbolPinResolver() if _truthy_env("OPENHAC_SCHEMATIC_STUB_ONLY") else SymbolPinResolver()
        if generated_symbol_lib_path and hasattr(symbol_resolver, "add_explicit_library"):
            symbol_resolver.add_explicit_library("OpenHaC", generated_symbol_lib_path)
        rec = _RecordingPinResolver(symbol_resolver) if pinpos_report_path else None
        geom = schematic_geometry(circuit, symbol_resolver=(rec or symbol_resolver))
        part_placements = geom["part_placements"]
        
        module_names = sorted(list({_module_field(p) for p in parts if _module_field(p)}))
        multi_sheet = len(module_names) > 0 or len(parts) > 12

        label_resolver = symbol_resolver

        if not multi_sheet:
            with open(output_path, "w", encoding="utf-8") as f, _junction_tracking_context():
                _write_kicad_sch_header(f, file_uuid, embedded_lib_symbols)
                sym_instances = []
                for part in parts:
                    x, y = part_placements[part]
                    rd = getattr(part, "refdes", "")
                    if not rd or rd == "?":
                        rd = getattr(part, "ref", "")
                    ref = str(rd).strip() or "U?"
                    
                    # Stable UUID based on persistent part ID
                    part_uuid = _uuid_for(f"part_id:{getattr(part, '_part_id', 'unknown')}")
                    _emit_symbol_instance(f, part, x, y, part_uuid)
                    
                    val = str(getattr(part, "value", None) or getattr(part, "name", None) or "").strip() or ref
                    fp = str(getattr(part, "footprint", None) or "").strip()
                    sym_instances.append((f"/{part_uuid}", ref, val, fp))
                
                # Phase C: Professional Connectivity & Spaghetti Mitigation
                for net in sorted(list(circuit.nets), key=_net_stable_key):
                    pins = sorted_net_pins(net)
                    if len(pins) < 2: continue
                    nn = getattr(net, "name", None) or str(net)
                    ntype = getattr(net, "_openhac_net_type", "signal")
                    
                    if ntype in ("power", "gnd"):
                        # Rule 4.2: Power/GND terminate at Port Symbols, never long wires
                        for p in pins:
                            lx, ly, _ = _pin_world_xy(p, p.part, part_placements[p.part], label_resolver)
                            _emit_net_label(f, net, lx, ly)
                        continue

                    if len(pins) > 3:
                        # Rule 4.2: Spaghetti Mitigation - switch to Labels for high-fanout
                        for p in pins:
                            lx, ly, _ = _pin_world_xy(p, p.part, part_placements[p.part], label_resolver)
                            _emit_net_label(f, net, lx, ly)
                        continue

                    # Local connectivity for low-fanout signals.
                    # Emit wires using the same axis-alignment test as schematic_geometry so the
                    # emitted segments match what the geometry pre-computed.  Calling
                    # _emit_orthogonal_path unconditionally produced 3 segments for any pair of
                    # pins whose X *and* Y differed, even when one axis difference was negligible
                    # after snapping — causing test_schematic_wires_use_library_offsets to see
                    # 3 wires instead of 1 (BUG-004 fix).
                    label_emitted = False
                    for i in range(len(pins)-1):
                        axw, ayw, _ = _pin_world_xy(pins[i], pins[i].part, part_placements[pins[i].part], label_resolver)
                        bxw, byw, _ = _pin_world_xy(pins[i+1], pins[i+1].part, part_placements[pins[i+1].part], label_resolver)
                        axw, ayw, bxw, byw = _snap(axw), _snap(ayw), _snap(bxw), _snap(byw)
                        if abs(axw - bxw) < 0.01 or abs(ayw - byw) < 0.01:
                            # Already axis-aligned: emit a single straight wire
                            _emit_wire(f, axw, ayw, bxw, byw)
                        else:
                            # Diagonal: L-shaped path via horizontal midpoint
                            mid_x = _snap((axw + bxw) / 2)
                            _emit_wire(f, axw, ayw, mid_x, ayw)
                            _emit_wire(f, mid_x, ayw, mid_x, byw)
                            _emit_wire(f, mid_x, byw, bxw, byw)
                        # Label only multi-pin nets (>= 3 pins); 2-pin point-to-point wires are self-documenting.
                        if len(pins) >= 3 and _is_significant_net(net) and not label_emitted:
                            _emit_net_label(f, net, (axw+bxw)/2, (ayw+byw)/2)
                            label_emitted = True
                
                for p in sorted(list(_junction_candidates)): _emit_junction(f, p[0], p[1])
                _emit_title_block(f, project_name, project_rev)
                _emit_sheet_instances(f)
                _emit_symbol_instances(f, sym_paths=sym_instances)
                f.write(")\n")
        else:
            root_path = Path(output_path)
            stem = root_path.stem
            out_dir = root_path.parent
            by_mod = {}
            for p in parts: by_mod.setdefault(_module_field(p), []).append(p)
            
            # Root Sheet
            with open(output_path, "w", encoding="utf-8") as f, _junction_tracking_context():
                _write_kicad_sch_header(f, file_uuid, embedded_lib_symbols)
                sheet_inst = []
                sheet_pin_locations = {} # (net_name) -> list of (x, y)
                               # Phase C: Root Sheet as System Block Diagram
                module_pin_coords = {} # (mod_name, net_name) -> (x, y)
                # [Professional Grade] Root Sheet: Intelligent System Block Diagram
                # We use a 2D grid to shorten paths and align pins by connectivity
                for i, mod_name in enumerate(module_names):
                    s_uuid = _uuid_for(f"sheet:{mod_name}")
                    # Staggered 2-row layout for system flow
                    col, row = i % 2, i // 2
                    sx, sy = 50.8 + col * 180, 50.8 + row * 120
                    sw, sh = 140, 90
                    
                    f.write(f'  (sheet (at {_fmt_mm(sx)} {_fmt_mm(sy)}) (size {_fmt_mm(sw)} {_fmt_mm(sh)})\n')
                    f.write(f'    (property "Sheetname" "{mod_name}" (at {_fmt_mm(sx)} {_fmt_mm(sy - 2)} 0) (effects (font (size 1.27 1.27)) (justify left bottom)))\n')
                    f.write(f'    (property "Sheetfile" "{stem}.{mod_name}.kicad_sch" (at {_fmt_mm(sx)} {_fmt_mm(sy + sh + 2)} 0) (effects (font (size 1.27 1.27)) (justify left top) (hide yes)))\n')
                    f.write(f'    (uuid "{s_uuid}")\n')
                    
                    mod_obj = next((m for m in (getattr(board, "modules", []) or []) if str(getattr(m, "name", "")) == mod_name), None)
                    if mod_obj:
                        iface_nets = _interface_nets_for_module(mod_obj)
                        # Order pins: Pins connecting to sheets on the LEFT go on the LEFT edge, etc.
                        for j, net in enumerate(iface_nets[:40]):
                            nn = getattr(net, "name", None) or str(net)
                            nu = nn.upper()
                            
                            # Semantic direction guessing
                            is_power = any(kw in nu for kw in ("VCC", "VDD", "3V3", "5V", "12V", "VIN", "VBAT"))
                            is_output = any(kw in nu for kw in ("TX", "OUT", "MOSI", "SCK", "SDO", "PWM"))
                            
                            # Placement: Power/In on Left, Out on Right
                            edge = "right" if is_output else "left"
                            if is_power and "GND" not in nu: edge = "left" # Power usually enters from left
                            
                            px, py = (sx + sw) if edge == "right" else sx, sy + 10 + j * 5.08
                            _emit_hierarchical_pin(f, nn, "passive", px, py, j)
                            module_pin_coords[(mod_name, nn)] = (px, py)
                    f.write('  )\n')
                    sheet_inst.append((f"/{s_uuid}", str(i + 2)))

                # Rule 4.1: Main Bus Connections in Block Diagram
                for net in sorted(list(circuit.nets), key=_net_stable_key):
                    nn = getattr(net, "name", None) or str(net)
                    if _is_power_net(nn): continue
                    
                    # Find all module pins on this net
                    net_pins = []
                    for (mname, nname), (px, py) in module_pin_coords.items():
                        if nname == nn: net_pins.append((px, py))
                    
                    if len(net_pins) >= 2:
                        for k in range(len(net_pins)-1):
                            _emit_orthogonal_path(f, net_pins[k][0], net_pins[k][1], net_pins[k+1][0], net_pins[k+1][1])
                            _emit_net_label(f, net, (net_pins[k][0] + net_pins[k+1][0])/2, (net_pins[k][1] + net_pins[k+1][1])/2)
                
                global_sym_inst = []
                for p in parts:
                    mname = _module_field(p)
                    if not mname: continue
                    s_uuid = _uuid_for(f"sheet:{mname}")
                    # Stable Part UUID based on hierarchical path + persistent ID
                    p_local_uuid = _uuid_for(f"part:{mname}:{getattr(p, '_part_id', 'unknown')}")
                    p_full_path = f"/{s_uuid}/{p_local_uuid}"
                    
                    rd = getattr(p, "refdes", "")
                    if not rd or rd == "?":
                        rd = getattr(p, "ref", "")
                    ref = str(rd).strip() or "U?"
                    val = str(getattr(p, "value", None) or getattr(p, "name", None) or "").strip() or ref
                    fp = str(getattr(p, "footprint", None) or "").strip()
                    global_sym_inst.append((p_full_path, ref, val, fp))

                _emit_title_block(f, project_name, project_rev)
                _emit_sheet_instances(f, sheet_paths=sheet_inst)
                _emit_symbol_instances(f, sym_paths=global_sym_inst)
                f.write(")\n")

            # Sub-sheets
            for mod_name in module_names:
                sheet_path = out_dir / f"{stem}.{mod_name}.kicad_sch"
                sheet_uuid = _uuid_for(f"sheet:{mod_name}")
                sheet_parts = by_mod.get(mod_name, [])
                
                # Fetch module object and its interface nets for hierarchical label logic
                mod_obj = next((m for m in (getattr(board, "modules", []) or []) if str(getattr(m, "name", "")) == mod_name), None)
                iface_nets = _interface_nets_for_module(mod_obj) if mod_obj else []
                iface_net_ids = {id(n) for n in iface_nets}

                with open(sheet_path, "w", encoding="utf-8") as sf, _junction_tracking_context():
                    _write_kicad_sch_header(sf, sheet_uuid, embedded_lib_symbols)
                    gxs = [part_placements[p][0] for p in sheet_parts]
                    gys = [part_placements[p][1] for p in sheet_parts]
                    min_gx = min(gxs) if gxs else 0
                    min_gy = min(gys) if gys else 0
                    dx, dy = (25.0 - min_gx), (35.0 - min_gy)
                    sym_inst = []
                    local_pos = {}
                    for p in sheet_parts:
                        gx, gy = part_placements[p]
                        x, y = gx + dx, gy + dy
                        local_pos[p] = (x, y)
                        
                        # Ensure we use the groomed refdes
                        rd = getattr(p, "refdes", "")
                        if not rd or rd == "?":
                            rd = getattr(p, "ref", "")
                        ref = str(rd).strip() or "U?"
                        # Hierarchical Path spec: /{sheet_uuid}/{part_uuid}
                        # We use a stable part ID to prevent collisions across grooming/pickling
                        # Stable Part UUID based on hierarchical path + persistent ID
                        p_local_uuid = _uuid_for(f"part:{mod_name}:{getattr(p, '_part_id', 'unknown')}")
                        p_full_path = f"/{sheet_uuid}/{p_local_uuid}"
                        
                        _emit_symbol_instance(sf, p, x, y, p_local_uuid)
                        val = str(getattr(p, "value", None) or getattr(p, "name", None) or "").strip() or ref
                        fp = str(getattr(p, "footprint", None) or "").strip()
                        sym_inst.append((p_full_path, ref, val, fp))
                    
                    for net in sorted(list(circuit.nets), key=_net_stable_key):
                        pins = sorted_net_pins(net)
                        local_pins = [p for p in pins if _module_field(p.part) == mod_name]
                        if not local_pins: continue
                        nn = getattr(net, "name", None) or str(net)
                        
                        if nn.upper().strip() == "NC":
                            for p in local_pins:
                                lxw, lyw, _ = _pin_world_xy(p, p.part, local_pos[p.part], label_resolver)
                                _emit_no_connect(sf, lxw, lyw)
                        else:
                            # Sub-sheet Phase C logic: Reduce label redundancy
                            ntype = getattr(net, "_openhac_net_type", "signal")
                            
                            # For EVERY net in this sheet, we only want ONE label to identify it
                            # unless it's a very short local trace.
                            first_p = local_pins[0]
                            lxw, lyw, _ = _pin_world_xy(first_p, first_p.part, local_pos[first_p.part], label_resolver)
                            
                            if ntype in ("power", "gnd") or len(pins) > 3:
                                # High-fanout or Power: Just one label at the first pin to identify the net
                                _emit_net_label(sf, net, lxw, lyw)
                            else:
                                # Local Signal: Draw wires between local pins
                                if len(local_pins) >= 2:
                                    for i in range(len(local_pins)-1):
                                        axw, ayw, _ = _pin_world_xy(local_pins[i], local_pins[i].part, local_pos[local_pins[i].part], label_resolver)
                                        bxw, byw, _ = _pin_world_xy(local_pins[i+1], local_pins[i+1].part, local_pos[local_pins[i+1].part], label_resolver)
                                        _emit_orthogonal_path(sf, axw, ayw, bxw, byw)
                                    
                                    # Label the trace once if it's significant
                                    if _is_significant_net(net):
                                        mid_p = local_pins[len(local_pins)//2]
                                        mxw, myw, _ = _pin_world_xy(mid_p, mid_p.part, local_pos[mid_p.part], label_resolver)
                                        _emit_net_label(sf, net, mxw, myw)

                            # Module Interface Pins: Hierarchical label if net leaves the module
                            # or if it's explicitly declared as a module interface
                            mods_on_net = {_module_field(p.part) for p in pins}
                            if len(mods_on_net) > 1 or id(net) in iface_net_ids:
                                # Place hierarchical label near the first pin to signal it's a port
                                _emit_hierarchical_label(sf, nn, "passive", lxw, lyw)
                    for p in sorted(list(_junction_candidates)): _emit_junction(sf, p[0], p[1])
                    _emit_title_block(sf, f"{project_name} - {mod_name}", project_rev)
                    _emit_sheet_instances(sf)
                    _emit_symbol_instances(sf, sym_paths=sym_inst)
                    sf.write(")\n")

    finally:
        if generated_symbol_lib_path:
            if prev_sym_dirs is None: os.environ.pop("OPENHAC_KICAD_SYMBOL_DIRS", None)
            else: os.environ["OPENHAC_KICAD_SYMBOL_DIRS"] = prev_sym_dirs
        # Write pin-position report if requested and recording resolver was used
        if pinpos_report_path and rec is not None:
            import json as _json
            try:
                report = {
                    "schema": "openhac.sch_pinpos_report.v1",
                    "resolved_pin_count": rec.resolved_pin_count,
                    "stub_pin_count": rec.stub_pin_count,
                    "by_symbol": rec.by_symbol,
                }
                with open(pinpos_report_path, "w", encoding="utf-8") as _rf:
                    _json.dump(report, _rf, indent=2)
            except Exception as _e:
                logger.warning("Could not write pinpos report to %s: %s", pinpos_report_path, _e)

def kicad_sch_unescape_label(text: str) -> str:
    """Unescape KiCad schematic label strings (basic \" -> " and \\\\ -> \\)."""
    return text.replace(r'\"', '"').replace(r'\\', '\\')


def parse_kicad_sch_net_labels(text: str) -> list[tuple[str, float, float]]:
    """Extract (name, x, y) for all label forms in a .kicad_sch file.

    Matches plain ``(label ...)``, ``(global_label ...)``, and
    ``(hierarchical_label ...)`` so the round-trip geometry test can verify all
    label types regardless of which emitter path was taken.
    """
    import re
    # Matches: label|global_label|hierarchical_label "<name>" ... (at <x> <y>
    label_re = re.compile(
        r'(?:global_label|hierarchical_label|label)\s+"([^"]+)"'
        r'(?:\s+\(shape\s+\w+\))?\s+\(at\s+([\d\.]+)\s+([\d\.]+)'
    )
    return [
        (kicad_sch_unescape_label(m.group(1)), float(m.group(2)), float(m.group(3)))
        for m in label_re.finditer(text)
    ]


def parse_kicad_sch_wire_segments(text: str) -> list[tuple[float, float, float, float]]:
    """Extract (x1, y1, x2, y2) for all wire segments in a .kicad_sch file."""
    import re
    wire_re = re.compile(r'\(wire\s+\(pts\s+\(xy\s+([-0-9\.]+)\s+([-0-9\.]+)\)\s+\(xy\s+([-0-9\.]+)\s+([-0-9\.]+)\)\)')
    return [
        (float(m.group(1)), float(m.group(2)), float(m.group(3)), float(m.group(4)))
        for m in wire_re.finditer(text)
    ]


def schematic_wire_endpoint_pairs(circuit) -> list[frozenset[tuple[str, str]]]:
    """Return a list of frozensets, each containing two (ref, pin_num) pairs for logical schematic wires."""
    edges = []
    # We follow the same sorting logic as schematic_geometry to match expected segments
    for net in sorted(list(circuit.nets), key=_net_stable_key):
        if _is_power_net(getattr(net, "name", "") or str(net)):
            continue
        pins = sorted_net_pins(net)
        for i in range(len(pins) - 1):
            pa, pb = pins[i], pins[i+1]
            edges.append(frozenset({
                (getattr(pa.part, "ref", ""), str(getattr(pa, "num", ""))),
                (getattr(pb.part, "ref", ""), str(getattr(pb, "num", "")))
            }))
    return edges
