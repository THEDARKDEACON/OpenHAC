from __future__ import annotations

import os
from pathlib import Path

from skidl import Part, Net

from openhac.compiler.schematic_gen import generate_schematic
from openhac.core.board import Board


def test_multisheet_export_writes_subsheets(tmp_path: Path, monkeypatch) -> None:
    # Build a tiny circuit with module tags to force per-module sheets.
    n = Net("N1")
    p1 = Part("Device", "R", value="10k", footprint="Resistor_SMD:R_0603_1608Metric")
    p2 = Part("Device", "R", value="10k", footprint="Resistor_SMD:R_0603_1608Metric")
    p1.fields["OpenHaC_Module"] = "MOD_A"
    p2.fields["OpenHaC_Module"] = "MOD_B"
    n += p1[1]
    n += p2[1]

    b = Board((10, 10))
    out = tmp_path / "t.kicad_sch"

    monkeypatch.setenv("OPENHAC_SCHEMATIC_MULTI_SHEET", "1")
    generate_schematic(str(out), b)

    assert out.is_file()
    root = out.read_text(encoding="utf-8")
    assert "(sheet" in root

    # Expect subsheets for both module tags.
    a = tmp_path / "t.MOD_A.kicad_sch"
    b2 = tmp_path / "t.MOD_B.kicad_sch"
    assert a.is_file()
    assert b2.is_file()

