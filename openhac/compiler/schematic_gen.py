from __future__ import annotations

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


def _emit_symbol_instance(f, part, x, y, uuid_str: str) -> None:
    """Write a (symbol ...) S-expression block for a single part."""
    lib = part_library_name(part)
    name = (getattr(part, "name", None) or "").strip()
    lib_id = f"{lib}:{name}" if lib else name
    f.write(f'  (symbol (lib_id "{lib_id}") (at {x} {y} 0) (unit 1)\n')
    f.write(f'    (in_bom yes) (on_board yes)\n')
    f.write(f'    (uuid "{uuid_str}")\n')
    f.write(f'  )\n')


def _emit_wire(f, x1, y1, x2, y2) -> None:
    """Write a (wire ...) S-expression block."""
    wire_uuid = str(uuid.uuid4())
    f.write(f'  (wire (pts (xy {x1} {y1}) (xy {x2} {y2}))\n')
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
    resolver: SchematicPinResolver = (
        symbol_resolver if symbol_resolver is not None else SymbolPinResolver()
    )
    positions = _assign_grid_positions(circuit.parts)
    part_placements: dict = {part: positions[part] for part in circuit.parts}

    wires: list[tuple[float, float, float, float]] = []
    labels: list[tuple[str, float, float]] = []

    for net in circuit.nets:
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


def schematic_wire_endpoint_pairs(circuit) -> list[frozenset[tuple[str, str]]]:
    """Undirected edges (ref, pin) pairs the schematic generator will wire (chain over sorted pins)."""
    edges: list[frozenset[tuple[str, str]]] = []
    for net in circuit.nets:
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
    label_uuid = str(uuid.uuid4())
    safe = kicad_string_escape(net_name)
    f.write(f'  (label "{safe}" (at {x} {y} 0)\n')
    f.write(f'    (effects (font (size 1.27 1.27)))\n')
    f.write(f'    (uuid "{label_uuid}")\n')
    f.write(f'  )\n')


def generate_schematic(
    output_path: str,
    board,
    *,
    symbol_resolver: SchematicPinResolver | None = None,
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

    file_uuid = str(uuid.uuid4())
    geom = schematic_geometry(circuit, symbol_resolver=symbol_resolver)
    part_placements = geom["part_placements"]

    with open(output_path, 'w', encoding='utf-8') as f:
        # Header
        f.write('(kicad_sch (version 20231120) (generator openhac)\n')
        f.write(f'  (uuid "{file_uuid}")\n')
        f.write('  (paper "A4")\n')

        for part in circuit.parts:
            x, y = part_placements[part]
            part_uuid = str(uuid.uuid4())
            _emit_symbol_instance(f, part, x, y, part_uuid)

        for x1, y1, x2, y2 in geom["wires"]:
            _emit_wire(f, x1, y1, x2, y2)

        for net_name, lx, ly in geom["labels"]:
            _emit_net_label(f, net_name, lx, ly)

        # Close root S-expression
        f.write(')\n')

    logger.info("Schematic S-Expression document generated successfully.")
