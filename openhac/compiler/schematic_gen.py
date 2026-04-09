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

_COLS_PER_ROW = 10
_CELL_SPACING = 10.0


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


def _assign_grid_positions(parts) -> dict:
    """Row-major grid assignment with 10-unit cell spacing, 10 columns per row."""
    positions = {}
    for idx, part in enumerate(parts):
        col = idx % _COLS_PER_ROW
        row = idx // _COLS_PER_ROW
        positions[part] = (col * _CELL_SPACING, row * _CELL_SPACING)
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


def _assign_positions_grouped_by_module(parts) -> dict:
    """Place parts in per-module blocks for readability (stretch).

    Falls back to a plain grid when no parts are tagged with ``OpenHaC_Module``.
    """
    if not any(_module_field(p) for p in parts):
        return _assign_grid_positions(parts)

    groups: dict[str, list] = {}
    for p in parts:
        groups.setdefault(_module_field(p), []).append(p)

    module_names = sorted(groups.keys(), key=lambda s: (s == "", s))
    y0 = 0.0
    positions: dict = {}
    gap = _CELL_SPACING * 1.5
    for m in module_names:
        ps = sorted(groups[m], key=_part_stable_key)
        for idx, part in enumerate(ps):
            col = idx % _COLS_PER_ROW
            row = idx // _COLS_PER_ROW
            positions[part] = (col * _CELL_SPACING, y0 + row * _CELL_SPACING)
        rows = (len(ps) + _COLS_PER_ROW - 1) // _COLS_PER_ROW
        y0 += max(1, rows) * _CELL_SPACING + gap

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


def write_generated_symbol_library(output_path: str, circuit, *, nickname: str = "OpenHaC") -> str | None:
    """Write a minimal KiCad ``.kicad_sym`` for SKiDL-native parts.

    This prevents KiCad showing '?' placeholders when symbols are not available in system libraries.
    Returns the written path, or None if nothing was generated.
    """
    parts = list(getattr(circuit, "parts", []) or [])
    skidl_parts = []
    try:
        import skidl

        for p in parts:
            if getattr(p, "tool", None) == getattr(skidl, "SKIDL", None):
                skidl_parts.append(p)
    except Exception:
        return None

    if not skidl_parts:
        return None

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    def _sym_header(name: str) -> str:
        # very small rectangle body, pins around left/right.
        return (
            f'  (symbol "{name}" (in_bom yes) (on_board yes)\n'
            f'    (property "Reference" "U" (at 0 4 0) (effects (font (size 1.27 1.27))))\n'
            f'    (property "Value" "{name}" (at 0 -4 0) (effects (font (size 1.27 1.27))))\n'
            f'    (symbol "{name}_0_1"\n'
            f'      (rectangle (start -5 3) (end 5 -3) (stroke (width 0.254) (type default)) (fill (type none)))\n'
        )

    def _sym_footer(name: str) -> str:
        return "    )\n  )\n"

    def _pin_block(num: str, pname: str, x: float, y: float, rot: float) -> str:
        # Use pin numbers for SCH-001 resolver (number "N") with (at x y rot).
        safe_name = pname.replace('"', "'")
        return (
            f'      (pin passive line (at {_fmt_mm(x)} {_fmt_mm(y)} {_fmt_mm(rot)}) (length 2.54)\n'
            f'        (name "{safe_name}" (effects (font (size 1 1))))\n'
            f'        (number "{num}" (effects (font (size 1 1))))\n'
            f"      )\n"
        )

    # Stable order by symbol name.
    def _pname(p) -> str:
        return (getattr(p, "name", None) or "").strip() or "?"

    names = sorted({_pname(p) for p in skidl_parts if _pname(p) != "?"})
    if not names:
        return None

    # Map symbol name -> representative part (for pin list).
    by_name = {}
    for p in skidl_parts:
        n = _pname(p)
        if n and n not in by_name:
            by_name[n] = p

    lines = []
    lines.append('(kicad_symbol_lib (version 20231120) (generator openhac)\n')
    for name in names:
        part = by_name[name]
        pins = list(getattr(part, "pins", []) or [])
        lines.append(_sym_header(name))

        # Place pins alternating left/right in a simple column.
        left_x, right_x = -7.54, 7.54
        y0 = 2.0
        dy = 1.27
        for i, pin in enumerate(pins):
            num = str(getattr(pin, "num", "") or str(i + 1))
            pname = str(getattr(pin, "name", "") or num)
            y = y0 - i * dy
            if i % 2 == 0:
                lines.append(_pin_block(num, pname, left_x, y, 0))
            else:
                lines.append(_pin_block(num, pname, right_x, y, 180))

        lines.append(_sym_footer(name))
    lines.append(")\n")

    out.write_text("".join(lines), encoding="utf-8")
    return str(out)


def _emit_symbol_instance(f, part, x, y, uuid_str: str) -> None:
    """Write a (symbol ...) S-expression block for a single part."""
    lib = part_library_name(part)
    name = (getattr(part, "name", None) or "").strip()
    lib_id = f"{lib}:{name}" if lib else name
    rot = 0.0
    try:
        fields = getattr(part, "fields", None)
        if isinstance(fields, dict) and fields.get("OpenHaC_Rotation_Deg") is not None:
            rot = float(fields.get("OpenHaC_Rotation_Deg"))
    except Exception:
        rot = 0.0
    f.write(
        f'  (symbol (lib_id "{lib_id}") (at {_fmt_mm(x)} {_fmt_mm(y)} {_fmt_mm(rot)}) (unit 1)\n'
    )
    f.write(f'    (in_bom yes) (on_board yes)\n')
    f.write(f'    (uuid "{uuid_str}")\n')
    f.write(f'  )\n')


def _emit_wire(f, x1, y1, x2, y2) -> None:
    """Write a (wire ...) S-expression block."""
    wire_uuid = _uuid_for(f"wire:{x1:.6f},{y1:.6f}:{x2:.6f},{y2:.6f}")
    f.write(
        f'  (wire (pts (xy {_fmt_mm(x1)} {_fmt_mm(y1)}) (xy {_fmt_mm(x2)} {_fmt_mm(y2)}))\n'
    )
    f.write(f'    (stroke (width 0) (type default))\n')
    f.write(f'    (uuid "{wire_uuid}")\n')
    f.write(f'  )\n')


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
        for idx, p in enumerate(part.pins):
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

        for i in range(len(pins) - 1):
            pin_a = pins[i]
            pin_b = pins[i + 1]
            ax, ay = part_placements.get(pin_a.part, (0.0, 0.0))
            bx, by = part_placements.get(pin_b.part, (0.0, 0.0))
            axw, ayw = _pin_world_xy(pin_a, pin_a.part, (ax, ay), resolver)
            bxw, byw = _pin_world_xy(pin_b, pin_b.part, (bx, by), resolver)
            wires.append((axw, ayw, bxw, byw))

        if len(pins) > 2:
            first_pin = pins[0]
            lx, ly = part_placements.get(first_pin.part, (0.0, 0.0))
            lxw, lyw = _pin_world_xy(first_pin, first_pin.part, (lx, ly), resolver)
            net_name = getattr(net, "name", None) or str(net)
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
    """Write a (label ...) S-expression block for nets with > 2 pins."""
    label_uuid = _uuid_for(f"label:{net_name}:{x:.6f},{y:.6f}")
    safe = kicad_string_escape(net_name)
    f.write(f'  (label "{safe}" (at {_fmt_mm(x)} {_fmt_mm(y)} 0)\n')
    f.write(f'    (effects (font (size 1.27 1.27)))\n')
    f.write(f'    (uuid "{label_uuid}")\n')
    f.write(f'  )\n')


def _safe_sheet_filename(stem: str) -> str:
    s = (stem or "").strip()
    s = re.sub(r"[^A-Za-z0-9_.-]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("._")
    return s or "sheet"


def _emit_sheet_symbol(f, *, sheet_name: str, sheet_file: str, x: float, y: float, w: float, h: float) -> None:
    """Emit a KiCad sheet symbol referencing a subsheet file.

    Uses global labels for cross-sheet connectivity (no sheet pins), so the hierarchy exists for readability
    without requiring a full hierarchical-pin exporter yet.
    """
    su = _uuid_for(f"sheet:{sheet_name}:{sheet_file}:{x:.3f},{y:.3f}")
    safe_name = kicad_string_escape(sheet_name)
    safe_file = kicad_string_escape(sheet_file)
    f.write(f'  (sheet (at {_fmt_mm(x)} {_fmt_mm(y)} 0) (size {_fmt_mm(w)} {_fmt_mm(h)})\n')
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


def generate_schematic(
    output_path: str,
    board,
    *,
    symbol_resolver: SchematicPinResolver | None = None,
    pinpos_report_path: str | None = None,
    generated_symbol_lib_path: str | None = None,
) -> None:
    """Generate a KiCad S-expression schematic file from the current default circuit (see ``openhac.circuit.get_default_circuit`` / ``get_circuit``)."""
    logger.info(f"Synthesizing Logic Graph into 2D Schematic Array -> {output_path}")

    try:
        circuit = get_default_circuit()
    except RuntimeError as e:
        raise SchematicGenerationError(
            "default_circuit is unavailable; cannot generate schematic. "
            "Ensure SKiDL has been initialised before calling generate_schematic()."
        ) from e

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
        if pinpos_report_path is not None:
            base_resolver: SchematicPinResolver = (
                symbol_resolver
                if symbol_resolver is not None
                else (
                    EmptySymbolPinResolver()
                    if _truthy_env("OPENHAC_SCHEMATIC_STUB_ONLY")
                    else SymbolPinResolver()
                )
            )
            rec = _RecordingPinResolver(base_resolver)
            geom = schematic_geometry(circuit, symbol_resolver=rec)
        else:
            rec = None
            geom = schematic_geometry(circuit, symbol_resolver=symbol_resolver)

        part_placements = geom["part_placements"]
        parts = sorted(list(circuit.parts), key=_part_stable_key)

        multi_sheet = bool(getattr(board, "schematic_multi_sheet", False)) or _truthy_env("OPENHAC_SCHEMATIC_MULTI_SHEET")

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
                # Header
                f.write('(kicad_sch (version 20231120) (generator openhac)\n')
                f.write(f'  (uuid "{file_uuid}")\n')
                f.write('  (paper "A4")\n')

                for part in parts:
                    x, y = part_placements[part]
                    ref = str(getattr(part, "ref", "") or "?")
                    part_uuid = _uuid_for(f"symbol:{ref}")
                    _emit_symbol_instance(f, part, x, y, part_uuid)

                for x1, y1, x2, y2 in geom["wires"]:
                    _emit_wire(f, x1, y1, x2, y2)

                for net_name, lx, ly in geom["labels"]:
                    _emit_net_label(f, net_name, lx, ly)

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
                f.write('(kicad_sch (version 20231120) (generator openhac)\n')
                f.write(f'  (uuid "{file_uuid}")\n')
                f.write('  (paper "A4")\n')

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
                sx, sy = 10.0, 10.0
                sw, sh = 60.0, 20.0
                gap = 10.0
                for i, mod_name in enumerate(mods):
                    fname = f"{stem}.{_safe_sheet_filename(mod_name)}.kicad_sch"
                    x0 = sx
                    y0 = sy + i * (sh + gap)
                    _emit_sheet_symbol(f, sheet_name=mod_name, sheet_file=fname, x=x0, y=y0, w=sw, h=sh)

                    # Add hierarchical pins for this module's declared interfaces (if we can find the module object).
                    mod_obj = None
                    for mm in getattr(board, "modules", None) or []:
                        if str(getattr(mm, "name", "")) == mod_name:
                            mod_obj = mm
                            break
                    if mod_obj is not None:
                        nets = _interface_nets_for_module(mod_obj)
                        # Stable unique names.
                        seen: set[str] = set()
                        pin_names: list[str] = []
                        for net in nets:
                            nn = str(getattr(net, "name", "") or "").strip()
                            if nn and nn not in seen:
                                seen.add(nn)
                                pin_names.append(nn)
                        # Pin placement: left side of sheet.
                        px = x0
                        py = y0 + 5.0
                        for j, pname in enumerate(pin_names[:20]):  # cap to avoid insane sheet symbol
                            _emit_sheet_pin(f, name=pname, pin_type="passive", x=px, y=py + j * 2.54, rot=0.0)

                f.write(")\n")

            # Write each subsheet: module’s parts + local wires + hierarchical labels for interface nets.
            for mod_name in mods:
                sheet_file = out_dir / f"{stem}.{_safe_sheet_filename(mod_name)}.kicad_sch"
                sheet_uuid = _uuid_for(f"schematic:sheet:{mod_name}")
                sheet_parts = sorted(by_mod.get(mod_name, []) or [], key=_part_stable_key)

                with open(sheet_file, "w", encoding="utf-8") as sf:
                    sf.write('(kicad_sch (version 20231120) (generator openhac)\n')
                    sf.write(f'  (uuid "{sheet_uuid}")\n')
                    sf.write('  (paper "A4")\n')
                    for part in sheet_parts:
                        x, y = part_placements[part]
                        ref = str(getattr(part, "ref", "") or "?")
                        part_uuid = _uuid_for(f"symbol:{mod_name}:{ref}")
                        _emit_symbol_instance(sf, part, x, y, part_uuid)

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
