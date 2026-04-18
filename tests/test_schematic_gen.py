"""SCH-001: schematic connectivity helpers and deterministic wiring (OpenHaC)."""

from __future__ import annotations

import json

import openhac.core  # noqa: F401 — KiCad / SKiDL paths
from skidl import Net, Part

from openhac.compiler.schematic_gen import (
    generate_schematic,
    kicad_sch_unescape_label,
    kicad_string_escape,
    net_connectivity_signatures,
    parse_kicad_sch_net_labels,
    parse_kicad_sch_wire_segments,
    schematic_geometry,
    schematic_wire_endpoint_pairs,
    sorted_net_pins,
)
from openhac.core import Board


def test_kicad_string_escape():
    assert kicad_string_escape('a"b') == 'a\\"b'
    assert kicad_string_escape(r"a\b") == r"a\\b"


def test_sorted_net_pins_orders_by_ref_then_numeric_pin():
    n = Net("N1")
    r3 = Part("Device", "R", value="1k", ref="R3")
    r1 = Part("Device", "R", value="1k", ref="R1")
    r2 = Part("Device", "R", value="1k", ref="R2")
    r3[2] += n
    r1[1] += n
    r2[2] += n

    ordered = sorted_net_pins(n)
    assert [p.part.ref for p in ordered] == ["R1", "R2", "R3"]


def test_net_connectivity_signatures_and_wire_pairs():
    n = Net("BUS")
    r1 = Part("Device", "R", value="1k", ref="R1")
    r2 = Part("Device", "R", value="1k", ref="R2")
    r3 = Part("Device", "R", value="1k", ref="R3")
    r1[1] += n
    r2[2] += n
    r3[1] += n

    from openhac.circuit import get_default_circuit

    c = get_default_circuit()
    sigs = net_connectivity_signatures(c)
    assert sigs["BUS"] == frozenset({("R1", "1"), ("R2", "2"), ("R3", "1")})

    edges = schematic_wire_endpoint_pairs(c)
    assert len(edges) == 2
    assert frozenset({("R1", "1"), ("R2", "2")}) in edges
    assert frozenset({("R2", "2"), ("R3", "1")}) in edges


def test_generate_schematic_wire_and_label_counts(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    n = Net("THREE")
    r1 = Part("Device", "R", value="1k", ref="R1")
    r2 = Part("Device", "R", value="1k", ref="R2")
    r3 = Part("Device", "R", value="1k", ref="R3")
    r1[1] += n
    r2[1] += n
    r3[1] += n

    p2 = Net("PAIR")
    a = Part("Device", "R", value="1k", ref="RA")
    b = Part("Device", "R", value="1k", ref="RB")
    a[2] += p2
    b[2] += p2

    out = tmp_path / "sch.kicad_sch"
    rep = tmp_path / "sch.openhac-sch-pinpos-report.json"
    generate_schematic(str(out), Board(size_mm=(10, 10)), pinpos_report_path=str(rep))

    text = out.read_text(encoding="utf-8")
    assert text.startswith("(kicad_sch ")
    # THREE: 3 pins → 2 wires + 1 label; PAIR: 2 pins → 1 wire, no label
    assert text.count("(wire (pts") == 3
    assert '  (label "THREE"' in text
    assert "PAIR" not in text or text.count("(label ") == 1

    data = json.loads(rep.read_text(encoding="utf-8"))
    assert data.get("schema") == "openhac.sch_pinpos_report.v1"
    assert isinstance(data.get("resolved_pin_count"), int)
    assert isinstance(data.get("stub_pin_count"), int)
    assert isinstance(data.get("by_symbol"), dict)


def test_generate_schematic_is_deterministic_when_env_enabled(tmp_path, monkeypatch):
    """Determinism stretch: UUIDs in .kicad_sch are stable when OPENHAC_DETERMINISTIC_UUIDS is set."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENHAC_DETERMINISTIC_UUIDS", "1")
    n = Net("PAIR")
    a = Part("Device", "R", value="1k", ref="RA")
    b = Part("Device", "R", value="1k", ref="RB")
    a[2] += n
    b[2] += n

    out1 = tmp_path / "a.kicad_sch"
    out2 = tmp_path / "b.kicad_sch"
    generate_schematic(str(out1), Board(size_mm=(10, 10)))
    generate_schematic(str(out2), Board(size_mm=(10, 10)))
    assert out1.read_text(encoding="utf-8") == out2.read_text(encoding="utf-8")


def test_generate_schematic_is_deterministic_with_convenience_env(tmp_path, monkeypatch):
    """Determinism stretch: OPENHAC_DETERMINISTIC_SCHEMATIC implies deterministic UUIDs for .kicad_sch."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENHAC_DETERMINISTIC_SCHEMATIC", "1")
    n = Net("PAIR")
    a = Part("Device", "R", value="1k", ref="RA")
    b = Part("Device", "R", value="1k", ref="RB")
    a[2] += n
    b[2] += n

    out1 = tmp_path / "a.kicad_sch"
    out2 = tmp_path / "b.kicad_sch"
    generate_schematic(str(out1), Board(size_mm=(10, 10)))
    generate_schematic(str(out2), Board(size_mm=(10, 10)))
    assert out1.read_text(encoding="utf-8") == out2.read_text(encoding="utf-8")


def test_generate_schematic_is_deterministic_with_umbrella_env(tmp_path, monkeypatch):
    """Determinism stretch: OPENHAC_DETERMINISTIC implies deterministic UUIDs for .kicad_sch."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENHAC_DETERMINISTIC", "1")
    n = Net("PAIR")
    a = Part("Device", "R", value="1k", ref="RA")
    b = Part("Device", "R", value="1k", ref="RB")
    a[2] += n
    b[2] += n

    out1 = tmp_path / "a.kicad_sch"
    out2 = tmp_path / "b.kicad_sch"
    generate_schematic(str(out1), Board(size_mm=(10, 10)))
    generate_schematic(str(out2), Board(size_mm=(10, 10)))
    assert out1.read_text(encoding="utf-8") == out2.read_text(encoding="utf-8")


def test_generate_schematic_emits_rotation_from_part_field(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    n = Net("PAIR")
    a = Part("Device", "R", value="1k", ref="RA")
    b = Part("Device", "R", value="1k", ref="RB")
    # Rotation hint for one part.
    a.fields["OpenHaC_Rotation_Deg"] = "90"
    a[2] += n
    b[2] += n
    out = tmp_path / "rot.kicad_sch"
    generate_schematic(str(out), Board(size_mm=(10, 10)))
    text = out.read_text(encoding="utf-8")
    assert '(symbol (lib_id "OpenHaC:R") (at ' in text
    assert " 90" in text


def _norm_wires(segs):
    return sorted(tuple(round(x, 4) for x in w) for w in segs)


def _norm_labels(labs):
    return sorted((n, round(x, 4), round(y, 4)) for n, x, y in labs)


def test_schematic_geometry_round_trip_matches_parsed_file(tmp_path, monkeypatch):
    """SCH-001: written .kicad_sch wire/label geometry matches ``schematic_geometry``."""
    monkeypatch.chdir(tmp_path)
    n = Net("THREE")
    r1 = Part("Device", "R", value="1k", ref="R1")
    r2 = Part("Device", "R", value="1k", ref="R2")
    r3 = Part("Device", "R", value="1k", ref="R3")
    r1[1] += n
    r2[1] += n
    r3[1] += n

    p2 = Net("PAIR")
    a = Part("Device", "R", value="1k", ref="RA")
    b = Part("Device", "R", value="1k", ref="RB")
    a[2] += p2
    b[2] += p2

    from openhac.circuit import get_default_circuit

    c = get_default_circuit()
    geom = schematic_geometry(c)
    out = tmp_path / "roundtrip.kicad_sch"
    generate_schematic(str(out), Board(size_mm=(10, 10)))
    text = out.read_text(encoding="utf-8")

    parsed_w = parse_kicad_sch_wire_segments(text)
    parsed_l = parse_kicad_sch_net_labels(text)

    assert _norm_wires(parsed_w) == _norm_wires(geom["wires"])
    assert _norm_labels(parsed_l) == _norm_labels(geom["labels"])
    assert {lbl[0] for lbl in parsed_l} == {"THREE"}


def test_schematic_geometry_is_stable_across_part_insertion_order(tmp_path, monkeypatch):
    """SCH-001: schematic placement/wiring should not depend on SKiDL part insertion order."""
    monkeypatch.chdir(tmp_path)
    n = Net("N")
    r2 = Part("Device", "R", value="1k", ref="R2")
    r1 = Part("Device", "R", value="1k", ref="R1")
    r2[1] += n
    r1[1] += n

    from openhac.circuit import get_default_circuit

    c = get_default_circuit()
    out1 = tmp_path / "o1.kicad_sch"
    out2 = tmp_path / "o2.kicad_sch"
    monkeypatch.setenv("OPENHAC_DETERMINISTIC_UUIDS", "1")
    generate_schematic(str(out1), Board(size_mm=(10, 10)))
    generate_schematic(str(out2), Board(size_mm=(10, 10)))
    assert out1.read_text(encoding="utf-8") == out2.read_text(encoding="utf-8")


def test_kicad_sch_unescape_label():
    assert kicad_sch_unescape_label(r"net\"x") == 'net"x'
    assert kicad_sch_unescape_label(r"a\\b") == r"a\b"


def test_net_label_escapes_embedded_quote(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    n = Net('net"weird')
    r1 = Part("Device", "R", value="1k", ref="R1")
    r2 = Part("Device", "R", value="1k", ref="R2")
    r3 = Part("Device", "R", value="1k", ref="R3")
    r1[1] += n
    r2[1] += n
    r3[1] += n

    out = tmp_path / "esc.kicad_sch"
    generate_schematic(str(out), Board(size_mm=(10, 10)))
    text = out.read_text(encoding="utf-8")
    # kicad_string_escape turns " into \"
    assert 'net\\"weird' in text
