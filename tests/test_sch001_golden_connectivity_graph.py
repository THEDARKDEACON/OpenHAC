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
            x, y, _rot = _pin_world_xy(pin, part, (px, py), None)
            pt_to_pin[_pt_key(x, y)] = (ref, str(getattr(pin, "num", "?")))

    # Build a graph of wire segments to find connected components.
    from collections import defaultdict
    adj = defaultdict(set)
    for x1, y1, x2, y2 in parse_kicad_sch_wire_segments(text):
        p1, p2 = _pt_key(x1, y1), _pt_key(x2, y2)
        adj[p1].add(p2)
        adj[p2].add(p1)

    seen = set()
    got_components = set()
    for node in adj:
        if node in seen:
            continue
        comp = set()
        q = [node]
        while q:
            curr = q.pop()
            if curr in comp:
                continue
            comp.add(curr)
            seen.add(curr)
            q.extend(adj[curr])
        # Find all logical pins attached to this physical wire cluster.
        comp_pins = frozenset(pt_to_pin[pt] for pt in comp if pt in pt_to_pin)
        if len(comp_pins) > 1:
            got_components.add(comp_pins)

    # Convert the expected (pairwise) edges into connected components for comparison.
    exp_adj = defaultdict(set)
    for edge in expected:
        # edge is a frozenset of two (ref, pin) tuples
        edge_list = list(edge)
        if len(edge_list) == 2:
            u, v = edge_list
            exp_adj[u].add(v)
            exp_adj[v].add(u)
    
    exp_seen = set()
    expected_components = set()
    for node in exp_adj:
        if node in exp_seen:
            continue
        comp = set()
        q = [node]
        while q:
            curr = q.pop()
            if curr in comp:
                continue
            comp.add(curr)
            exp_seen.add(curr)
            q.extend(exp_adj[curr])
        if len(comp) > 1:
            expected_components.add(frozenset(comp))

    assert got_components == expected_components

