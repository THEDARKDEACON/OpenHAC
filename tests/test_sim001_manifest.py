"""SIM-001: manifest spice annotation counts."""

from __future__ import annotations

import json
from unittest.mock import patch

import openhac.core  # noqa: F401
from skidl import Net, Part

from openhac.core import Board
from openhac.core.base import Component, Module


def test_manifest_includes_spice_annotation_summary(tmp_path, tmp_db, monkeypatch):
    _, dm = tmp_db
    dm.insert_component(
        {
            "generic_name": "R_spicey",
            "kicad_symbol": "Device:R",
            "kicad_footprint": "Resistor_SMD:R_0805_2012Metric",
            "manufacturer": "",
            "mpn": "X",
            "supplier_sku": "",
            "description": "",
            "jlc_class": "Basic",
            "spice_subckt": "mysub",
        }
    )
    monkeypatch.setattr(Component, "db", dm)
    monkeypatch.chdir(tmp_path)

    design_py = tmp_path / "design.py"
    design_py.write_text("# spice manifest\n", encoding="utf-8")

    vcc, gnd = Net("3V3"), Net("GND")
    Part("power", "PWR_FLAG")[1] += vcc
    Part("power", "PWR_FLAG")[1] += gnd

    class N(Module):
        def __init__(self):
            super().__init__("n")
            r = self.add(Component("R_spicey"))
            r["1"] += vcc
            r["2"] += gnd
            self.declare_interface("p", vcc, gnd)

    board = Board(size_mm=(30.0, 30.0))
    board.add_module(N())

    with patch("openhac.compiler.layout_gen.generate_layout"):
        board.compile(
            project_name="spsum",
            generate_bom=True,
            auto_route=False,
            export_schematic=False,
            source_script_path=design_py,
        )

    data = json.loads((tmp_path / "spsum.openhac-manifest.json").read_text(encoding="utf-8"))
    s = data.get("spice_annotation_summary") or {}
    assert s.get("parts_with_spice_subckt", 0) >= 1
    hint = (tmp_path / "spsum.openhac-spice-model-hint.md").read_text(encoding="utf-8")
    assert "Checklist" in hint
    assert "Spice_Subckt" in hint
