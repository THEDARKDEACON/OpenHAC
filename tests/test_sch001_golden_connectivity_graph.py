from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from openhac.compiler.kicad_sym_pinpos import EmptySymbolPinResolver
from openhac.compiler.schematic_gen import (
    _pin_world_xy,
    generate_schematic,
    parse_kicad_sch_wire_segments,
    schematic_geometry,
    schematic_wire_endpoint_pairs,
)
from openhac.core.board import Board
from openhac.core.circuit import default_circuit, reset_default_circuit
from openhac.core.net import Net
from openhac.core.part import Part, Pin
from openhac.schematic.util import iter_pins


def _pt_key(x: float, y: float) -> tuple[int, int]:
    # Use micro-mm integer key to avoid float fuzz.
    return (int(round(x * 1_000_000.0)), int(round(y * 1_000_000.0)))


def _resistor(ref: str, value: str) -> Part:
    return Part(
        ref,
        "Resistor_SMD:R_0603_1608Metric",
        {"kicad_symbol": "Device:R"},
        [Pin("1", "1", "passive"), Pin("2", "2", "passive")],
        value=value,
    )


def test_exported_schematic_wires_match_expected_pin_edges(tmp_path: Path, monkeypatch) -> None:
    # Force stub-only geometry so pin coordinates are deterministic without KiCad libs.
    monkeypatch.setenv("OPENHAC_SCHEMATIC_STUB_ONLY", "1")
    reset_default_circuit()

    n1 = Net("N1")
    n2 = Net("N2")
    r1 = _resistor("R1", "10k")
    r2 = _resistor("R2", "10k")
    r3 = _resistor("R3", "1k")
    default_circuit.add_part(r1)
    default_circuit.add_part(r2)
    default_circuit.add_part(r3)
    r1["1"] += n1
    r2["1"] += n1
    r1["2"] += n2
    r3["1"] += n2

    b = Board((10, 10))
    out = tmp_path / "g.kicad_sch"
    generate_schematic(str(out), b, circuit=default_circuit)
    text = out.read_text(encoding="utf-8")

    circuit = default_circuit
    expected = set(schematic_wire_endpoint_pairs(circuit))

    resolver = EmptySymbolPinResolver()
    geom = schematic_geometry(circuit, symbol_resolver=resolver)
    placements = geom["part_placements"]
    pt_to_pin: dict[tuple[int, int], tuple[str, str]] = {}
    for part, (px, py) in placements.items():
        ref = str(getattr(part, "ref", "") or "?")
        for pin in iter_pins(part):
            x, y, _rot = _pin_world_xy(pin, part, (px, py), resolver)
            pt_to_pin[_pt_key(x, y)] = (ref, str(getattr(pin, "num", "?")))

    adj: dict[tuple[int, int], set[tuple[int, int]]] = defaultdict(set)
    for x1, y1, x2, y2 in parse_kicad_sch_wire_segments(text):
        p1, p2 = _pt_key(x1, y1), _pt_key(x2, y2)
        adj[p1].add(p2)
        adj[p2].add(p1)

    seen: set[tuple[int, int]] = set()
    got_components = set()
    for node in adj:
        if node in seen:
            continue
        comp: set[tuple[int, int]] = set()
        q = [node]
        while q:
            curr = q.pop()
            if curr in comp:
                continue
            comp.add(curr)
            seen.add(curr)
            q.extend(adj[curr])
        comp_pins = frozenset(pt_to_pin[pt] for pt in comp if pt in pt_to_pin)
        if len(comp_pins) > 1:
            got_components.add(comp_pins)

    exp_adj: dict[tuple[str, str], set[tuple[str, str]]] = defaultdict(set)
    for edge in expected:
        edge_list = list(edge)
        if len(edge_list) == 2:
            u, v = edge_list
            exp_adj[u].add(v)
            exp_adj[v].add(u)

    exp_seen: set[tuple[str, str]] = set()
    expected_components = set()
    for node in exp_adj:
        if node in exp_seen:
            continue
        comp_n: set[tuple[str, str]] = set()
        qn = [node]
        while qn:
            curr = qn.pop()
            if curr in comp_n:
                continue
            comp_n.add(curr)
            exp_seen.add(curr)
            qn.extend(exp_adj[curr])
        if len(comp_n) > 1:
            expected_components.add(frozenset(comp_n))

    assert got_components == expected_components
