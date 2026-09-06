"""LIVE-001…007: KiCad artwork overlay parse, merge, parity, freeze, preview PCB."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from openhac.compiler.kicad_artwork import (
    KicadArtworkOverlay,
    SchWire,
    attach_overlay_to_state,
    load_overlay_from_dir,
    overlay_wire_conflicts,
    parse_pcb_copper,
    parse_pcb_footprints,
    parse_pcb_net_table,
    parse_sch_overlay,
    parse_sch_symbol_poses,
    parse_sch_symbol_records,
    splice_pcb_copper,
)
from openhac.core.exceptions import ArtworkParityError, OpenHaCError

_SCH_FIXTURE = """(kicad_sch (version 20231120) (generator testdata)
  (uuid "11111111-1111-1111-1111-111111111111")
  (paper "A4")
  (lib_symbols)
  (symbol (lib_id "Device:R") (at 123.45 67.89 90) (unit 1)
    (in_bom yes) (on_board yes)
    (uuid "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    (property "Reference" "R1" (at 123.45 62.81 0)
      (effects (font (size 1.27 1.27)))
    )
    (property "Value" "10k" (at 123.45 73 0)
      (effects (font (size 1.27 1.27)))
    )
  )
  (symbol (lib_id "Device:R") (at 10 10 0) (unit 1)
    (uuid "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
    (property "Reference" "R99" (at 10 5 0)
      (effects (font (size 1.27 1.27)))
    )
  )
  (wire (pts (xy 0 0) (xy 10 0))
    (stroke (width 0) (type default))
    (uuid "cccccccccccccccccccccccccccccccccccc")
  )
  (label "GND" (at 0 0 0)
    (effects (font (size 1.27 1.27)))
  )
)
"""

_PCB_FIXTURE = """(kicad_pcb (version 20240108) (generator testdata)
  (general (thickness 1.6))
  (net 0 "")
  (net 1 "GND")
  (net 2 "3V3")
  (net 3 "GONE")
  (footprint "Resistor_SMD:R_0805_2012Metric" (layer "F.Cu")
    (uuid "dddddddd-dddd-dddd-dddd-dddddddddddd")
    (at 11.11 22.22 180)
    (property "Reference" "R1" (at 0 -1.65 0)
      (effects (font (size 1 1)))
    )
  )
  (segment (start 1 2) (end 3 4) (width 0.25) (layer "F.Cu") (net 1))
  (segment (start 5 5) (end 6 6) (width 0.25) (layer "F.Cu") (net 3))
  (via (at 7 8) (size 0.8) (drill 0.4) (layers "F.Cu" "B.Cu") (net 1))
)
"""


def _two_resistor_board(*, distinct_nets: bool = False):
    from openhac.core.circuit import reset_default_circuit
    from openhac.core.board import Board
    from openhac.core.base import Component, Module
    from openhac.core.net import Net

    reset_default_circuit()
    gnd = Net("GND")
    a = Net("SIG_A") if distinct_nets else Net("3V3")
    b = Net("SIG_B") if distinct_nets else a

    class Node(Module):
        def __init__(self, name: str, ref: str, n_hi: Net) -> None:
            super().__init__(name)
            r = self.add(
                Component(
                    f"R_{ref}",
                    refdes=ref,
                    pins={"1": ("1", "passive"), "2": ("2", "passive")},
                    comp_data={
                        "generic_name": f"R_{ref}",
                        "kicad_symbol": "Device:R",
                        "kicad_footprint": "Resistor_SMD:R_0805_2012Metric",
                        "manufacturer": "OpenHaC",
                        "mpn": ref,
                        "description": "test",
                        "pinout_json": json.dumps(
                            [
                                {"num": "1", "name": "1", "type": "passive"},
                                {"num": "2", "name": "2", "type": "passive"},
                            ]
                        ),
                    },
                )
            )
            r.fields["kicad_symbol"] = "Device:R"
            r[1] += n_hi
            r[2] += gnd

    board = Board(size_mm=(40.0, 30.0), compile_goal="handoff")
    board.add_module(Node("A", "R1", a))
    board.add_module(Node("B", "R2", b))
    return board


def test_parse_sch_symbol_pose_and_drop_hash():
    poses = parse_sch_symbol_poses(_SCH_FIXTURE)
    assert poses["R1"].x == pytest.approx(123.45)
    assert poses["R1"].y == pytest.approx(67.89)
    assert poses["R1"].rot == pytest.approx(90.0)
    assert "R99" in poses
    assert all(not r.startswith("#") for r in poses)


def test_parse_pcb_footprint_and_copper():
    fps = parse_pcb_footprints(_PCB_FIXTURE)
    assert fps["R1"].x == pytest.approx(11.11)
    assert fps["R1"].y == pytest.approx(22.22)
    assert fps["R1"].rot == pytest.approx(180.0)
    nets = parse_pcb_net_table(_PCB_FIXTURE)
    tracks, vias, _zones = parse_pcb_copper(_PCB_FIXTURE, nets)
    names = {t.net for t in tracks}
    assert "GND" in names
    assert "GONE" in names
    assert vias and vias[0].net == "GND"


def test_splice_drops_vanished_net():
    from openhac.compiler.kicad_artwork import KicadArtworkOverlay as Ov

    nets = parse_pcb_net_table(_PCB_FIXTURE)
    tracks, vias, zones = parse_pcb_copper(_PCB_FIXTURE, nets)
    ov = Ov(tracks=tracks, vias=vias, zones=zones)
    new_pcb = """(kicad_pcb (version 20240108)
  (net 0 "")
  (net 1 "GND")
)
"""
    out = splice_pcb_copper(new_pcb, ov, {"GND"})
    assert "(net 1)" in out
    assert "GONE" not in out
    assert "(start 5 5)" not in out
    assert "(start 1 2)" in out


def test_load_overlay_from_dir(tmp_path: Path):
    (tmp_path / "demo.kicad_sch").write_text(_SCH_FIXTURE, encoding="utf-8")
    (tmp_path / "demo.kicad_pcb").write_text(_PCB_FIXTURE, encoding="utf-8")
    ov = load_overlay_from_dir(tmp_path, "demo")
    assert ov.symbols["R1"].x == pytest.approx(123.45)
    assert ov.footprints["R1"].x == pytest.approx(11.11)
    assert ov.has_pcb_copper()


def test_merge_keeps_r1_xy_and_drops_r99(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENHAC_SCHEMATIC_STUB_ONLY", "1")
    from openhac.schematic.emit_kicad import generate_schematic

    board = _two_resistor_board()
    (tmp_path / "live.kicad_sch").write_text(_SCH_FIXTURE, encoding="utf-8")
    board._kicad_artwork_overlay = load_overlay_from_dir(tmp_path, "live")
    out = tmp_path / "merged.kicad_sch"
    generate_schematic(str(out), board)
    text = out.read_text(encoding="utf-8")
    assert "123.45" in text and "67.89" in text
    assert '(property "Reference" "R1"' in text
    assert '(property "Reference" "R99"' not in text
    assert '(property "Reference" "R2"' in text
    from openhac.schematic.kicad_links import root_schematic_uuid

    assert "(instances" in text
    assert f'(path "/{root_schematic_uuid()}" (reference "R1") (unit 1))' in text


def test_kicad9_unannotated_ref_keeps_xy_by_uuid(tmp_path: Path, monkeypatch):
    """KiCad 9 Save rewrites Reference to R?; pose must still merge by symbol UUID."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENHAC_SCHEMATIC_STUB_ONLY", "1")
    from openhac.schematic.collect import collect_parts_and_nets
    from openhac.schematic.emit_kicad import generate_schematic
    from openhac.schematic.kicad_links import root_schematic_uuid, symbol_instance_uuid
    from openhac.schematic.util import part_ref

    board = _two_resistor_board()
    parts, _nets = collect_parts_and_nets(board)
    r1 = next(p for p in parts if part_ref(p) == "R1")
    uid = symbol_instance_uuid(r1, 1)
    sheet = root_schematic_uuid()
    (tmp_path / "live.kicad_sch").write_text(
        f"""(kicad_sch (version 20250114) (generator "eeschema") (generator_version "9.0")
  (uuid "{sheet}")
  (paper "A4")
  (lib_symbols
    (symbol "Device:R"
      (lib_id "Device:R")
      (at 0 0 0)
      (uuid "deadbeef-dead-dead-dead-deadbeefdead")
      (property "Reference" "R1"
        (at 1 1 0)
        (effects (font (size 1.27 1.27)))
      )
    )
  )
  (symbol
    (lib_id "Device:R")
    (at 99.25 88.5 180)
    (unit 1)
    (in_bom yes)
    (on_board yes)
    (uuid "{uid}")
    (property "Reference" "R?"
      (at 101.79 87.23 0)
      (effects (font (size 1.27 1.27)))
    )
    (instances
      (project "live"
        (path "/{sheet}"
          (reference "R?")
          (unit 1)
        )
      )
    )
  )
)
""",
        encoding="utf-8",
    )
    text_in = (tmp_path / "live.kicad_sch").read_text(encoding="utf-8")
    assert parse_sch_symbol_poses(text_in) == {}
    symbols, by_uuid, _wires, _labels, _graphics = parse_sch_overlay(text_in)
    assert symbols == {}
    assert uid in by_uuid
    assert by_uuid[uid].x == pytest.approx(99.25)
    assert by_uuid[uid].y == pytest.approx(88.5)
    assert by_uuid[uid].rot == pytest.approx(180.0)
    assert "deadbeef-dead-dead-dead-deadbeefdead" not in by_uuid
    board._kicad_artwork_overlay = load_overlay_from_dir(tmp_path, "live")
    out = tmp_path / "merged.kicad_sch"
    generate_schematic(str(out), board)
    text = out.read_text(encoding="utf-8")
    recs = [p for p in parse_sch_symbol_records(text) if p.ref == "R1"]
    assert recs and recs[0].x == pytest.approx(99.25) and recs[0].y == pytest.approx(88.5)
    assert recs[0].rot == pytest.approx(180.0)
    assert f'(path "/{sheet}" (reference "R1") (unit 1))' in text


def test_overlay_wire_shorts_fail_generate(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENHAC_SCHEMATIC_STUB_ONLY", "1")
    from openhac.compiler.kicad_sym_pinpos import EmptySymbolPinResolver
    from openhac.schematic.collect import collect_parts_and_nets
    from openhac.schematic.emit_kicad import generate_schematic
    from openhac.schematic.layout import build_ir

    board = _two_resistor_board(distinct_nets=True)
    parts, nets = collect_parts_and_nets(board)
    ir = build_ir(parts, nets, board, resolver=EmptySymbolPinResolver())
    p1 = ir.pin_xy[("R1", "1")]
    p2 = ir.pin_xy[("R2", "1")]
    ov = KicadArtworkOverlay()
    ov.sch_wires.append(SchWire(p1[0], p1[1], p2[0], p2[1]))
    pin_to_net = {("R1", "1"): "SIG_A", ("R2", "1"): "SIG_B"}
    conflicts = overlay_wire_conflicts(ov, ir.pin_xy, pin_to_net)
    assert conflicts
    board._kicad_artwork_overlay = ov
    generate_schematic(str(tmp_path / "short_default.kicad_sch"), board)
    assert (tmp_path / "short_default.kicad_sch").is_file()
    board._keep_kicad_artwork = True
    with pytest.raises(ArtworkParityError, match="LIVE-006"):
        generate_schematic(str(tmp_path / "short.kicad_sch"), board)


def test_overlay_ir_echo_stub_is_not_a_user_short():
    """Re-ingesting OpenHaC's own pin stub must not LIVE-006, even if pin_xy stacks nets."""
    from openhac.compiler.kicad_artwork import ir_wire_echo_keys
    from openhac.schematic.ir import SchematicIR, WireSeg

    ir = SchematicIR(title="echo")
    ir.pin_xy = {("U1", "2"): (45.72, 797.56), ("U1", "8"): (48.26, 797.56)}
    ir.wires.append(WireSeg(45.72, 797.56, 48.26, 797.56, sheet="COMMS", net="3V3"))
    ov = KicadArtworkOverlay()
    ov.sch_wires.append(SchWire(45.72, 797.56, 48.26, 797.56, sheet="COMMS"))
    pin_to_net = {("U1", "2"): "GND", ("U1", "8"): "I2C_SDA"}
    raw = overlay_wire_conflicts(ov, ir.pin_xy, pin_to_net)
    assert raw
    skipped = overlay_wire_conflicts(
        ov, ir.pin_xy, pin_to_net, echo_keys=ir_wire_echo_keys(ir)
    )
    assert skipped == []


def test_overlay_child_sheet_local_coords_do_not_cross_short():
    """Same numeric xy on ANALOG vs COMMS must not snap as a cross-net short."""
    ov = KicadArtworkOverlay()
    ov.sch_wires.append(SchWire(38.1, 38.1, 40.64, 38.1, sheet="ANALOG"))
    analog_xy = {("U1", "4"): (38.1, 38.1)}
    comms_xy = {("U12", "2"): (38.1, 38.1), ("U6", "8"): (40.64, 38.1)}
    pin_to_net = {("U1", "4"): "INA_OUT", ("U12", "2"): "SPI_MISO", ("U6", "8"): "GND"}
    packed = {**analog_xy, **comms_xy}
    crossed = overlay_wire_conflicts(ov, packed, pin_to_net)
    assert crossed
    scoped = overlay_wire_conflicts(
        ov,
        packed,
        pin_to_net,
        pin_xy_by_sheet={"ANALOG": analog_xy, "COMMS": comms_xy},
        hierarchical=True,
    )
    assert scoped == []


def test_keep_kicad_artwork_missing_overlay_errors(tmp_path: Path):
    from openhac.core.board import Board

    st = SimpleNamespace(
        keep_kicad_artwork=True,
        regenerate_artwork=False,
        output_dir=str(tmp_path),
        project_name="missing",
        compile_goal="fabrication",
        board=Board(size_mm=(10, 10), compile_goal="fabrication"),
        auto_route=True,
        artwork_overlay=None,
    )
    with pytest.raises(OpenHaCError, match="LIVE-006"):
        attach_overlay_to_state(st)


def test_cli_live_flags_in_source():
    from openhac import cli as cli_mod

    src = Path(cli_mod.__file__).read_text(encoding="utf-8")
    assert "--keep-kicad-artwork" in src
    assert "--regenerate-artwork" in src
    assert '"--pcb"' in src
    assert '"--no-browser"' in src
    assert 'kicad_cli, "sch", "erc"' not in src


def test_preview_pcb_phases_skip_route_and_erc():
    from openhac.compiler.compile_pipeline import phases_for_profile

    preview = [fn.__name__ for fn in phases_for_profile("preview")]
    pcb = [fn.__name__ for fn in phases_for_profile("preview_pcb")]
    assert "phase_layout" not in preview
    assert "phase_schematic" in preview
    assert "phase_layout" in pcb
    assert "phase_schematic" in pcb
    assert "phase_autoroute" not in pcb
    assert "phase_erc_drc" not in pcb


def test_watch_debounce_pcb_slower():
    from openhac.compiler.kicad_live import watch_debounce_s

    assert watch_debounce_s(pcb=False) == pytest.approx(0.4)
    assert watch_debounce_s(pcb=True) == pytest.approx(0.8)


def test_kicad_sch_svg_never_runs_erc():
    from openhac.compiler import kicad_sch_svg

    src = Path(kicad_sch_svg.__file__).read_text(encoding="utf-8")
    assert 'kicad_cli, "sch", "export", "svg"' in src
    assert 'kicad_cli, "sch", "erc"' not in src
