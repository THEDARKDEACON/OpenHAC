"""SCH-001: KiCad .kicad_sym pin position parsing."""

from __future__ import annotations

from pathlib import Path

import pytest

import openhac.core  # noqa: F401
import json
from skidl import Net, Part

from openhac.compiler.kicad_sym_pinpos import (
    SymbolPinResolver,
    clear_symbol_pin_cache,
    find_symbol_library_file,
    load_symbol_pin_positions,
    map_graph_pin_to_library_number,
    parse_pin_positions_from_symbol_tree,
    parse_pinout_from_symbol_tree,
    pinout_from_kicad_symbol_id,
    resolve_symbol_tree_for_pins,
    rewrite_symbol_pin_electrical_types,
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
_FIXTURE_SHIFT = Path(__file__).resolve().parent / "fixtures" / "kicad_symbols" / "NameShift.kicad_sym"


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
    assert pos["1"][:2] == pytest.approx((0.0, 5.08))
    assert pos["2"][:2] == pytest.approx((0.0, -5.08))
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
    monkeypatch.setenv("OPENHAC_LEGACY_SKIDL", "1")
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
    ir = geom["ir"]
    r1p = next(p for p in geom["part_placements"] if str(getattr(p, "ref", "")) == "R1")
    px1, py1 = geom["part_placements"][r1p]
    pin_xy = ir.pin_xy[("R1", "1")]
    # Library pin 1 is 5.08 mm from origin (not the 2.54 mm stub-resolver fallback).
    assert abs(pin_xy[1] - py1) == pytest.approx(5.08, abs=1e-3)
    assert parsed
    assert len(geom["wires"]) == len(parsed)


def test_empty_resolver_matches_index_stub_geometry(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENHAC_LEGACY_SKIDL", "1")
    n = Net("N12")
    r1 = Part("Device", "R", value="1k", ref="R1")
    r2 = Part("Device", "R", value="1k", ref="R2")
    r1[1] += n
    r2[2] += n

    from openhac.circuit import get_default_circuit

    c = get_default_circuit()
    res = EmptySymbolPinResolver()
    geom = schematic_geometry(c, symbol_resolver=res)
    r1 = next(p for p in geom["part_placements"] if str(getattr(p, "ref", "")) == "R1")
    px1, py1 = geom["part_placements"][r1]
    from openhac.compiler.schematic_gen import _pin_world_xy

    axw, ayw, _ = _pin_world_xy(r1[1], r1, (px1, py1), res)
    assert max(abs(axw - px1), abs(ayw - py1)) == pytest.approx(2.54, rel=1e-3)


def test_openhac_schematic_stub_only_env_forces_stub_geometry_and_report(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENHAC_LEGACY_SKIDL", "1")
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
    r1 = next(p for p in geom["part_placements"] if str(getattr(p, "ref", "")) == "R1")
    px1, py1 = geom["part_placements"][r1]
    from openhac.compiler.schematic_gen import _pin_world_xy, EmptySymbolPinResolver

    res = EmptySymbolPinResolver()
    axw, ayw, _ = _pin_world_xy(r1[1], r1, (px1, py1), res)
    assert max(abs(axw - px1), abs(ayw - py1)) == pytest.approx(2.54, rel=1e-3)

    out = tmp_path / "stubonly.kicad_sch"
    rep = tmp_path / "stubonly.openhac-sch-pinpos-report.json"
    generate_schematic(str(out), Board(size_mm=(10, 10)), pinpos_report_path=str(rep))
    payload = json.loads(rep.read_text(encoding="utf-8"))
    assert payload.get("schema") == "openhac.sch_pinpos_report.v1"
    assert int(payload.get("resolved_pin_count") or 0) == 0
    assert int(payload.get("stub_pin_count") or 0) >= 2


class _GPin:
    def __init__(self, num, name):
        self.num = num
        self.name = name


def test_map_graph_pin_prefers_unique_name_when_numbers_disagree():
    pmap = {"8": (0.0, 5.08, 90.0, 2.54), "9": (-5.08, 0.0, 180.0, 2.54), "10": (5.08, 0.0, 0.0, 2.54)}
    by_num = {
        "8": {"num": "8", "name": "VDD"},
        "9": {"num": "9", "name": "SDA"},
        "10": {"num": "10", "name": "SCL"},
    }
    assert map_graph_pin_to_library_number(_GPin("8", "SDA"), pmap, by_num) == "9"
    assert map_graph_pin_to_library_number(_GPin("10", "VDD"), pmap, by_num) == "8"
    assert map_graph_pin_to_library_number(_GPin("9", "SCL"), pmap, by_num) == "10"
    # Device:R passive names are "~" — keep the graph number.
    rmap = {"1": (0.0, 5.08, 0.0, 2.54), "2": (0.0, -5.08, 0.0, 2.54)}
    rnames = {"1": {"num": "1", "name": "~"}, "2": {"num": "2", "name": "~"}}
    assert map_graph_pin_to_library_number(_GPin("1", "~"), rmap, rnames) == "1"
    assert map_graph_pin_to_library_number(_GPin("2", "~"), rmap, rnames) == "2"
    ncmap = {"5": (0.0, 0.0, 0.0, 2.54), "3": (0.0, 5.08, 90.0, 2.54)}
    ncnames = {
        "5": {"num": "5", "name": "NC", "type": "no_connect"},
        "3": {"num": "3", "name": "VCC", "type": "power_in"},
    }
    assert map_graph_pin_to_library_number(_GPin("5", "VIO"), ncmap, ncnames) is None
    assert map_graph_pin_to_library_number(_GPin("3", "VCC"), ncmap, ncnames) == "3"


def test_offset_for_pin_follows_name_remap(monkeypatch):
    monkeypatch.setenv("OPENHAC_KICAD_SYMBOL_DIRS", str(_FIXTURE_SHIFT.parent))
    clear_symbol_pin_cache()

    class _Lib:
        filename = "NameShift"

    class _Part:
        lib = _Lib()
        name = "Chip"
        ref = "U1"

    res = SymbolPinResolver()
    res.add_explicit_library("NameShift", _FIXTURE_SHIFT)
    dx, dy, _rot = res.offset_for_pin(_Part(), _GPin("8", "SDA"), symbol_name="Chip")
    assert dx == pytest.approx(-5.08)
    assert dy == pytest.approx(0.0)
    dx, dy, _rot = res.offset_for_pin(_Part(), _GPin("10", "VDD"), symbol_name="Chip")
    assert dx == pytest.approx(0.0)
    assert dy == pytest.approx(5.08)


def test_rewrite_symbol_pin_electrical_types_keeps_geometry():
    tree = (
        '(symbol "X"\n'
        '  (pin output line (at 1.27 0 0) (length 2.54) (name "MISO") (number "2"))\n'
        ")"
    )
    out = rewrite_symbol_pin_electrical_types(tree, {"2": "tri_state"})
    assert "(pin tri_state " in out
    assert "(at 1.27 0 0)" in out
    assert '(number "2")' in out
