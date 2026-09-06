"""Schematic emitter layout: stubs on pins, sheet ownership, collisions, spacing."""

from __future__ import annotations

from pathlib import Path

from skidl import Net, Part

from openhac.compiler.schematic_gen import generate_schematic
from openhac.core.board import Board
from openhac.core.base import Module
from openhac.schematic.ir import NetLabel, NoConnect, SchematicIR, SymbolInstance, WireSeg
from openhac.schematic.layout import (
    _COL_PITCH_MM,
    _STUB_MM,
    _add_stub_label,
    _nc_extra_library_pins,
    _separate_colliding_nets,
    _through_wire_hits_foreign,
    build_ir,
    schematic_geometry,
)
from openhac.schematic.util import snap


def test_col_pitch_leaves_room_for_stub():
    assert _COL_PITCH_MM >= 127.0
    assert _STUB_MM == 2.54


def test_fanout_label_sits_on_stub_wire(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    n = Net("THREE")
    for ref in ("R1", "R2", "R3"):
        r = Part("Device", "R", value="1k", ref=ref)
        r[1] += n
    ir = schematic_geometry(__import__("openhac.circuit", fromlist=["get_default_circuit"]).get_default_circuit())["ir"]
    labels = [lb for lb in ir.labels if lb.name == "THREE"]
    assert len(labels) >= 3
    pins = list(ir.pin_xy.values())
    for lb in labels:
        on_pin = any(abs(lb.x - px) < 0.05 and abs(lb.y - py) < 0.05 for px, py in pins)
        assert not on_pin
        assert any(
            w.net == "THREE"
            and abs(w.x2 - lb.x) < 0.05
            and abs(w.y2 - lb.y) < 0.05
            and (abs(w.x1 - w.x2) + abs(w.y1 - w.y2)) > 1.0
            for w in ir.wires
        )


def test_separate_colliding_nets_nudges_different_nets():
    ir = SchematicIR()
    ir.labels = [
        NetLabel("A", 10.0, 10.0, "local"),
        NetLabel("B", 10.0, 10.0, "local"),
    ]
    ir.wires = [
        WireSeg(7.46, 10.0, 10.0, 10.0, net="A"),
        WireSeg(7.46, 10.0, 10.0, 10.0, net="B"),
    ]
    _separate_colliding_nets(ir)
    assert abs(ir.labels[0].x - ir.labels[1].x) + abs(ir.labels[0].y - ir.labels[1].y) >= 2.0
    assert ir.labels[0].name != ir.labels[1].name
    for lb in ir.labels:
        assert any(
            (abs(w.x2 - lb.x) < 0.05 and abs(w.y2 - lb.y) < 0.05)
            or (abs(w.x1 - lb.x) < 0.05 and abs(w.y1 - lb.y) < 0.05)
            for w in ir.wires
            if w.net == lb.name
        )


def test_nc_occupies_point_so_other_net_moves():
    ir = SchematicIR()
    ir.no_connects = [NoConnect(0.0, 0.0)]
    ir.labels = [NetLabel("SIG", 0.0, 0.0, "local")]
    ir.wires = [WireSeg(-2.54, 0.0, 0.0, 0.0, net="SIG")]
    _separate_colliding_nets(ir)
    assert abs(ir.labels[0].x) + abs(ir.labels[0].y) >= 2.0


def test_multisheet_child_keeps_off_pin_labels(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPENHAC_SCHEMATIC_MULTI_SHEET", "1")
    monkeypatch.setenv("OPENHAC_SCHEMATIC_STUB_ONLY", "1")
    shared = Net("N1")

    class MA(Module):
        def __init__(self):
            super().__init__("MOD_A")
            r = self.add(Part("Device", "R", value="10k", footprint="Resistor_SMD:R_0603_1608Metric"))
            r[1] += shared

    class MB(Module):
        def __init__(self):
            super().__init__("MOD_B")
            r = self.add(Part("Device", "R", value="10k", footprint="Resistor_SMD:R_0603_1608Metric"))
            r[1] += shared

    b = Board((10, 10))
    b.add_module(MA())
    b.add_module(MB())
    out = tmp_path / "t.kicad_sch"
    generate_schematic(str(out), b)
    root = out.read_text(encoding="utf-8")
    assert "(global_label" not in root
    assert "(wire (pts" in root
    assert '(pin "N1"' in root
    a = (tmp_path / "t.MOD_A.kicad_sch").read_text(encoding="utf-8")
    btxt = (tmp_path / "t.MOD_B.kicad_sch").read_text(encoding="utf-8")
    assert "(wire (pts" in a
    assert "(wire (pts" in btxt
    assert 'hierarchical_label "N1"' in a or 'label "N1"' in a
    assert 'hierarchical_label "N1"' in btxt or 'label "N1"' in btxt


def test_power_and_io_modules_use_wide_columns(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENHAC_SCHEMATIC_SINGLE_SHEET", "1")
    vcc = Net("3V3")
    sig = Net("USB_DP")

    class Ldo(Module):
        def __init__(self):
            super().__init__("Ldo3V3", schematic_flow="power")
            r = self.add(Part("Device", "R", value="10k", footprint="Resistor_SMD:R_0603_1608Metric"))
            r[1] += vcc

    class Usb(Module):
        def __init__(self):
            super().__init__("UsbJack", schematic_flow="io")
            r = self.add(Part("Device", "R", value="10k", footprint="Resistor_SMD:R_0603_1608Metric"))
            r[1] += sig

    b = Board((10, 10))
    b.add_module(Ldo())
    b.add_module(Usb())
    from openhac.schematic.collect import collect_parts_and_nets

    parts, nets = collect_parts_and_nets(b)
    ir = build_ir(parts, nets, b)
    xs = [inst.x for inst in ir.instances]
    assert max(xs) - min(xs) >= 140.0


def _seg_len(w) -> float:
    return ((w.x1 - w.x2) ** 2 + (w.y1 - w.y2) ** 2) ** 0.5


def test_stub_wires_are_not_degenerate(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    n = Net("THREE")
    for ref in ("R1", "R2", "R3"):
        r = Part("Device", "R", value="1k", ref=ref)
        r[1] += n
    ir = schematic_geometry(__import__("openhac.circuit", fromlist=["get_default_circuit"]).get_default_circuit())["ir"]
    stubs = [w for w in ir.wires if w.net == "THREE"]
    assert stubs
    for w in stubs:
        assert _seg_len(w) >= 1.0


def test_parent_sheet_pins_on_grid_and_shared_net_spine(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENHAC_SCHEMATIC_MULTI_SHEET", "1")
    monkeypatch.setenv("OPENHAC_SCHEMATIC_STUB_ONLY", "1")
    shared = Net("N1")

    class MA(Module):
        def __init__(self):
            super().__init__("MOD_A")
            r = self.add(Part("Device", "R", value="10k", footprint="Resistor_SMD:R_0603_1608Metric"))
            r[1] += shared

    class MB(Module):
        def __init__(self):
            super().__init__("MOD_B")
            r = self.add(Part("Device", "R", value="10k", footprint="Resistor_SMD:R_0603_1608Metric"))
            r[1] += shared

    b = Board((10, 10))
    b.add_module(MA())
    b.add_module(MB())
    from openhac.schematic.collect import collect_parts_and_nets

    parts, nets = collect_parts_and_nets(b)
    ir = build_ir(parts, nets, b)
    assert ir.sheets
    for sh in ir.sheets:
        assert abs(sh.x - snap(sh.x)) < 1e-9
        assert abs(sh.y - snap(sh.y)) < 1e-9
        for hp in sh.pins:
            assert abs(hp.x - snap(hp.x)) < 1e-9
            assert abs(hp.y - snap(hp.y)) < 1e-9
    assert not any(lb.kind == "global" for lb in ir.root_labels)
    pin_pts = [(hp.x, hp.y) for sh in ir.sheets for hp in sh.pins if hp.name == "N1"]
    assert len(pin_pts) == 2
    for x, y in pin_pts:
        assert any(
            (abs(w.x1 - x) < 0.05 and abs(w.y1 - y) < 0.05)
            or (abs(w.x2 - x) < 0.05 and abs(w.y2 - y) < 0.05)
            for w in ir.root_wires
        )
    for w in ir.root_wires:
        assert _seg_len(w) >= 1.0
    for sh in ir.sheets:
        for hp in sh.pins:
            assert hp.rot == 180


def test_child_sheet_geometry_is_local(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENHAC_SCHEMATIC_MULTI_SHEET", "1")
    monkeypatch.setenv("OPENHAC_SCHEMATIC_STUB_ONLY", "1")
    shared = Net("N1")
    vcc = Net("3V3")

    class MA(Module):
        def __init__(self):
            super().__init__("Ldo3V3")
            r = self.add(Part("Device", "R", value="10k", footprint="Resistor_SMD:R_0603_1608Metric"))
            r[1] += vcc
            r[2] += shared

    class MB(Module):
        def __init__(self):
            super().__init__("UsbJack")
            r = self.add(Part("Device", "R", value="10k", footprint="Resistor_SMD:R_0603_1608Metric"))
            r[1] += vcc
            r[2] += shared

    b = Board((10, 10))
    b.add_module(MA())
    b.add_module(MB())
    from openhac.schematic.collect import collect_parts_and_nets

    parts, nets = collect_parts_and_nets(b)
    ir = build_ir(parts, nets, b)
    assert ir.child_sheets
    for child in ir.child_sheets.values():
        xs = [inst.x for inst in child.instances]
        ys = [inst.y for inst in child.instances]
        assert xs and min(xs) < 80.0
        assert ys and min(ys) < 80.0
    assert not any(hp.name == "3V3" for sh in ir.sheets for hp in sh.pins)
    assert any(hp.name == "N1" for sh in ir.sheets for hp in sh.pins)


def test_through_wire_blocked_when_foreign_pin_on_segment():
    ir = SchematicIR()
    ir.pin_xy = {
        ("U1", "1"): (0.0, 0.0),
        ("U2", "1"): (0.0, 10.16),
        ("U3", "1"): (0.0, 5.08),
    }
    assert _through_wire_hits_foreign(ir, 0.0, 0.0, 0.0, 10.16)
    ir.pin_xy = {
        ("U1", "1"): (0.0, 0.0),
        ("U2", "1"): (0.0, 10.16),
    }
    assert not _through_wire_hits_foreign(ir, 0.0, 0.0, 0.0, 10.16)


def test_nc_extra_library_pins_follow_name_ownership(monkeypatch):
    from openhac.compiler.kicad_sym_pinpos import clear_symbol_pin_cache

    fixture = Path(__file__).resolve().parent / "fixtures" / "kicad_symbols"
    monkeypatch.setenv("OPENHAC_KICAD_SYMBOL_DIRS", str(fixture))
    clear_symbol_pin_cache()

    class _Pin:
        def __init__(self, num, name):
            self.num = num
            self.name = name
            self.net = None

    class _Part:
        def get_pins(self):
            return [_Pin("8", "SDA"), _Pin("10", "VDD")]

    part = _Part()
    ir = SchematicIR()
    inst = SymbolInstance(
        part=part, lib_id="NameShift:Chip", x=0.0, y=0.0, rot=0.0,
        uuid="u", ref="U1", value="Chip", footprint="",
    )
    # Graph SDA@8 → library SDA@9 (-5.08, 0); graph VDD@10 → library VDD@8 (0, 5.08) → world y flip.
    ir.pin_xy = {("U1", "8"): (-5.08, 0.0), ("U1", "10"): (0.0, -5.08)}
    _nc_extra_library_pins(ir, part, inst, None, "NameShift:Chip")
    pts = {(round(nc.x, 2), round(nc.y, 2)) for nc in ir.no_connects}
    assert (5.08, 0.0) in pts  # unused SCL
    assert (0.0, 5.08) in pts  # unused LED
    assert (-5.08, 0.0) not in pts
    assert (0.0, -5.08) not in pts


def test_stubs_follow_pin_rotation_not_long_axis():
    """Top-of-body right pins must stub right, not vertically down the pin column."""
    ir = SchematicIR()
    ir.pin_rot[("U1", "1")] = 0.0
    ir.pin_rot[("U1", "2")] = 0.0
    _add_stub_label(
        ir, sheet="M", ref="U1", wx=15.24, wy=0.0, ox=0.0, oy=40.0,
        name="TX", pin_num_s="1",
    )
    _add_stub_label(
        ir, sheet="M", ref="U1", wx=15.24, wy=2.54, ox=0.0, oy=40.0,
        name="RX", pin_num_s="2",
    )
    assert len(ir.wires) == 2
    for w in ir.wires:
        assert abs(w.y1 - w.y2) < 0.01
        assert w.x2 > w.x1
    ends = {(round(w.x2, 2), round(w.y2, 2)) for w in ir.wires}
    assert (round(ir.wires[0].x2, 2), round(ir.wires[0].y1, 2)) in ends
    # Distinct nets must not share an endpoint (KiCad T-join).
    a, b = ir.wires
    assert not (
        (abs(a.x2 - b.x1) < 0.05 and abs(a.y2 - b.y1) < 0.05)
        or (abs(a.x2 - b.x2) < 0.05 and abs(a.y2 - b.y2) < 0.05)
        or (abs(a.x1 - b.x1) < 0.05 and abs(a.y1 - b.y1) < 0.05)
    )


def test_schematic_sheet_constructor_groups_modules(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENHAC_SCHEMATIC_MULTI_SHEET", "1")
    monkeypatch.setenv("OPENHAC_SCHEMATIC_STUB_ONLY", "1")
    shared = Net("CAN_H")

    class Phy(Module):
        def __init__(self):
            super().__init__("CanPhy", schematic_sheet="CAN")
            r = self.add(Part("Device", "R", value="1k", footprint="Resistor_SMD:R_0603_1608Metric"))
            r[1] += shared

    class Term(Module):
        def __init__(self):
            super().__init__("CanTerm")
            r = self.add(Part("Device", "R", value="120", footprint="Resistor_SMD:R_0603_1608Metric"))
            r[1] += shared

    b = Board((10, 10))
    phy, term = Phy(), Term()
    b.add_module(phy)
    b.add_module(term)
    b.set_schematic_sheet("CAN", phy, term)
    out = tmp_path / "grouped.kicad_sch"
    generate_schematic(str(out), b)
    assert (tmp_path / "grouped.CAN.kicad_sch").is_file()
    assert not (tmp_path / "grouped.CanPhy.kicad_sch").is_file()
    assert not (tmp_path / "grouped.CanTerm.kicad_sch").is_file()
    text = (tmp_path / "grouped.CAN.kicad_sch").read_text(encoding="utf-8")
    assert text.count('(lib_id "Device:R")') == 2


def test_instance_reference_uses_part_ref_not_library_placeholder(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    n = Net("N")
    r = Part("Device", "R", value="120", ref="R12")
    r[1] += n
    out = tmp_path / "ref.kicad_sch"
    generate_schematic(str(out), Board(size_mm=(10, 10)))
    text = out.read_text(encoding="utf-8")
    assert '(property "Reference" "R12"' in text
    assert '(property "Reference" "R12" (id 0)' not in text
