"""SCH-001: KiCad .kicad_sym pin position parsing."""

from __future__ import annotations

from pathlib import Path

import pytest

import openhac.core  # noqa: F401
import json
from skidl import Net, Part

from openhac.compiler.kicad_sym_pinpos import (
    clear_symbol_pin_cache,
    find_symbol_library_file,
    load_symbol_pin_positions,
    parse_pin_positions_from_symbol_tree,
    parse_pinout_from_symbol_tree,
    pinout_from_kicad_symbol_id,
    resolve_symbol_tree_for_pins,
)
from openhac.compiler.schematic_gen import (
    EmptySymbolPinResolver,
    generate_schematic,
    parse_kicad_sch_wire_segments,
    schematic_geometry,
)
from openhac.core.board import Board

_FIXTURE_SYM = Path(__file__).resolve().parent / "fixtures" / "kicad_symbols" / "Device.kicad_sym"
_FIXTURE_EXTENDS = Path(__file__).resolve().parent / "fixtures" / "kicad_symbols" / "ExtendsDemo.kicad_sym"


def test_parse_pinout_from_fixture_resistor():
    text = _FIXTURE_SYM.read_text(encoding="utf-8")
    po = parse_pinout_from_symbol_tree(text)
    assert len(po) == 2
    assert po[0]["num"] == "1" and po[0]["name"] == "~" and po[0]["type"] == "passive"
    assert po[1]["num"] == "2" and po[1]["name"] == "~"


def test_pinout_from_kicad_symbol_id_uses_search_path(monkeypatch):
    monkeypatch.setenv("OPENHAC_KICAD_SYMBOL_DIRS", str(_FIXTURE_SYM.parent))
    clear_symbol_pin_cache()
    po = pinout_from_kicad_symbol_id("Device:R")
    assert po and len(po) == 2
    assert po[0]["type"] == "passive"


def test_resolve_extends_stub_loads_parent_pins():
    text = _FIXTURE_EXTENDS.read_text(encoding="utf-8")
    tree = resolve_symbol_tree_for_pins(text, "DerivedPart")
    assert tree is not None
    po = parse_pinout_from_symbol_tree(tree)
    assert len(po) == 2
    assert {p["num"]: p["name"] for p in po} == {"1": "VIN", "2": "GND"}


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


def test_find_device_library_with_kicad6_symbol_dir(monkeypatch):
    monkeypatch.setenv("KICAD6_SYMBOL_DIR", str(_FIXTURE_SYM.parent))
    clear_symbol_pin_cache()
    p = find_symbol_library_file("Device")
    assert p is not None
    assert p.name == "Device.kicad_sym"


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
    # Verify real library offsets (±5.08mm) are used, not the 2.54mm stub default.
    # With two parts at different Y positions, the wire y-span > stub span (2.54).
    x1, y1, x2, y2 = geom["wires"][0]
    assert abs(y1 - y2) > 2.54  # Proves library pin offsets (5.08mm) are active


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


def test_openhac_schematic_stub_only_env_forces_stub_geometry_and_report(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENHAC_KICAD_SYMBOL_DIRS", str(_FIXTURE_SYM.parent))
    monkeypatch.setenv("OPENHAC_SCHEMATIC_STUB_ONLY", "1")
    clear_symbol_pin_cache()

    n = Net("N12")
    r1 = Part("Device", "R", value="1k", ref="R1")
    r2 = Part("Device", "R", value="1k", ref="R2")
    r1[1] += n
    r2[2] += n

    from openhac.circuit import get_default_circuit

    c = get_default_circuit()
    geom = schematic_geometry(c)
    assert len(geom["wires"]) == 1
    x1, y1, x2, y2 = geom["wires"][0]
    assert y2 - y1 == pytest.approx(2.54, rel=1e-3)

    out = tmp_path / "stubonly.kicad_sch"
    rep = tmp_path / "stubonly.openhac-sch-pinpos-report.json"
    generate_schematic(str(out), Board(size_mm=(10, 10)), pinpos_report_path=str(rep))
    payload = json.loads(rep.read_text(encoding="utf-8"))
    assert payload.get("schema") == "openhac.sch_pinpos_report.v1"
    assert int(payload.get("resolved_pin_count") or 0) == 0
    assert int(payload.get("stub_pin_count") or 0) >= 2
