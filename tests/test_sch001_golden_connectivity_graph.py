from __future__ import annotations

from pathlib import Path

import pytest
from skidl import Part, Net

from openhac.compiler.kicad_sym_pinpos import EmptySymbolPinResolver
from openhac.compiler.schematic_gen import (
    _pin_world_xy,
    generate_schematic,
    parse_kicad_sch_wire_segments,
    schematic_geometry,
    schematic_wire_endpoint_pairs,
)
from openhac.core.board import Board


def _pt_key(x: float, y: float) -> tuple[int, int]:
    # Use micro-mm integer key to avoid float fuzz.
    return (int(round(x * 1_000_000.0)), int(round(y * 1_000_000.0)))


def test_exported_schematic_wires_match_expected_pin_edges(tmp_path: Path, monkeypatch) -> None:
    # Force stub-only geometry so pin coordinates are deterministic without KiCad libs.
    monkeypatch.setenv("OPENHAC_SCHEMATIC_STUB_ONLY", "1")

    # Tiny circuit with multiple nets and refs to build a non-trivial edge set.
    n1 = Net("N1")
    n2 = Net("N2")
    r1 = Part("Device", "R", value="10k", footprint="Resistor_SMD:R_0603_1608Metric")
    r2 = Part("Device", "R", value="10k", footprint="Resistor_SMD:R_0603_1608Metric")
    r3 = Part("Device", "R", value="1k", footprint="Resistor_SMD:R_0603_1608Metric")
    n1 += r1[1]
    n1 += r2[1]
    n2 += r1[2]
    n2 += r3[1]

    b = Board((10, 10))
    out = tmp_path / "g.kicad_sch"
    generate_schematic(str(out), b)
    text = out.read_text(encoding="utf-8")

    # Expected edges are expressed in terms of (ref, pin-num).
    from openhac.circuit import get_default_circuit

    circuit = get_default_circuit()
    expected = set(schematic_wire_endpoint_pairs(circuit))

    # Build a coordinate -> (ref,pin) lookup from the generator’s own placements and stub pin model.
    geom = schematic_geometry(circuit, symbol_resolver=EmptySymbolPinResolver())
    placements = geom["part_placements"]
    pt_to_pin: dict[tuple[int, int], tuple[str, str]] = {}
    for part, (px, py) in placements.items():
        ref = str(getattr(part, "ref", "") or "?")
        for pin in getattr(part, "pins", []) or []:
            x, y = _pin_world_xy(pin, part, (px, py), None)
            pt_to_pin[_pt_key(x, y)] = (ref, str(getattr(pin, "num", "?")))

    got: set[frozenset[tuple[str, str]]] = set()
    for x1, y1, x2, y2 in parse_kicad_sch_wire_segments(text):
        a = pt_to_pin.get(_pt_key(x1, y1))
        b2 = pt_to_pin.get(_pt_key(x2, y2))
        if a is None or b2 is None:
            pytest.fail(f"Wire endpoint did not resolve to a pin: ({x1},{y1}) -> {a}, ({x2},{y2}) -> {b2}")
        got.add(frozenset({a, b2}))

    assert got == expected

