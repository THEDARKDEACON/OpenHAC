"""SCH-001: KiCad .kicad_sym pin position parsing."""

from __future__ import annotations

from pathlib import Path

import pytest

import openhac.core  # noqa: F401
from skidl import Net, Part

from openhac.compiler.kicad_sym_pinpos import (
    clear_symbol_pin_cache,
    find_symbol_library_file,
    load_symbol_pin_positions,
    parse_pin_positions_from_symbol_tree,
)
from openhac.compiler.schematic_gen import (
    EmptySymbolPinResolver,
    generate_schematic,
    parse_kicad_sch_wire_segments,
    schematic_geometry,
)
from openhac.core.board import Board

_FIXTURE_SYM = Path(__file__).resolve().parent / "fixtures" / "kicad_symbols" / "Device.kicad_sym"


def test_parse_fixture_resistor_pins():
    text = _FIXTURE_SYM.read_text(encoding="utf-8")
    pos = parse_pin_positions_from_symbol_tree(text)
    assert pos["1"] == pytest.approx((0.0, 5.08))
    assert pos["2"] == pytest.approx((0.0, -5.08))
    clear_symbol_pin_cache()
    m = load_symbol_pin_positions(_FIXTURE_SYM, "R")
    assert m == pos


def test_find_device_library_with_fixture_path(monkeypatch):
    monkeypatch.setenv("OPENHAC_KICAD_SYMBOL_DIRS", str(_FIXTURE_SYM.parent))
    clear_symbol_pin_cache()
    p = find_symbol_library_file("Device")
    assert p is not None
    assert p.name == "Device.kicad_sym"
    m = load_symbol_pin_positions(p, "R")
    assert m and m["1"][1] == pytest.approx(5.08)


def test_schematic_wires_use_library_offsets_when_fixture_on_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENHAC_KICAD_SYMBOL_DIRS", str(_FIXTURE_SYM.parent))
    clear_symbol_pin_cache()

    n = Net("N12")
    r1 = Part("Device", "R", value="1k", ref="R1")
    r2 = Part("Device", "R", value="1k", ref="R2")
    r1[1] += n
    r2[2] += n

    from openhac.circuit import get_default_circuit

    c = get_default_circuit()
    geom = schematic_geometry(c)
    out = tmp_path / "sympos.kicad_sch"
    generate_schematic(str(out), Board(size_mm=(10, 10)))
    parsed = parse_kicad_sch_wire_segments(out.read_text(encoding="utf-8"))
    assert len(parsed) == 1
    assert len(geom["wires"]) == 1
    assert parsed[0] == pytest.approx(geom["wires"][0], rel=1e-4, abs=1e-4)
    # Pin 1 at y+5.08, pin 2 at y-5.08 from same part origin — not the 2.54 index stub.
    x1, y1, x2, y2 = geom["wires"][0]
    assert abs(y1 - y2) == pytest.approx(10.16, rel=1e-3)


def test_empty_resolver_matches_index_stub_geometry(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    n = Net("N12")
    r1 = Part("Device", "R", value="1k", ref="R1")
    r2 = Part("Device", "R", value="1k", ref="R2")
    r1[1] += n
    r2[2] += n

    from openhac.circuit import get_default_circuit

    c = get_default_circuit()
    res = EmptySymbolPinResolver()
    geom = schematic_geometry(c, symbol_resolver=res)
    assert len(geom["wires"]) == 1
    x1, y1, x2, y2 = geom["wires"][0]
    assert y2 - y1 == pytest.approx(2.54, rel=1e-3)
