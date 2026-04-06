"""SIM-002: Board.simulate() accepts spice_analysis_json_path (SW-006 contract)."""

from __future__ import annotations

import json

import openhac.core  # noqa: F401
from skidl import Net, Part


def test_simulate_reads_analysis_lines_from_json(tmp_path, tmp_db, monkeypatch):
    from openhac.core.base import Component
    from openhac.core.board import Board

    _, dm = tmp_db
    dm.insert_component(
        {
            "generic_name": "R_10k_0805",
            "kicad_symbol": "Device:R",
            "kicad_footprint": "Resistor_SMD:R_0805_2012Metric",
            "manufacturer": "",
            "mpn": "X",
            "supplier_sku": "",
            "description": "",
        }
    )
    monkeypatch.setattr(Component, "db", dm)
    monkeypatch.chdir(tmp_path)

    vcc, gnd = Net("3V3"), Net("GND")
    Part("power", "PWR_FLAG")[1] += vcc
    Part("power", "PWR_FLAG")[1] += gnd
    r = Part("Device", "R", value="1k", footprint="Resistor_SMD:R_0805_2012Metric")
    r[1] += vcc
    r[2] += gnd

    jpath = tmp_path / "analysis.json"
    jpath.write_text(json.dumps({"analysis_lines": [".op"]}), encoding="utf-8")

    board = Board(size_mm=(10.0, 10.0))
    board.simulate("simjson", spice_analysis_json_path=jpath, output_dir=tmp_path)

    cir = (tmp_path / "simjson.cir").read_text(encoding="utf-8")
    assert ".op" in cir
    assert "*   .op" in cir


def test_simulate_reads_preset_from_yaml(tmp_path, tmp_db, monkeypatch):
    from openhac.core.base import Component
    from openhac.core.board import Board

    _, dm = tmp_db
    dm.insert_component(
        {
            "generic_name": "R_10k_0805",
            "kicad_symbol": "Device:R",
            "kicad_footprint": "Resistor_SMD:R_0805_2012Metric",
            "manufacturer": "",
            "mpn": "X",
            "supplier_sku": "",
            "description": "",
        }
    )
    monkeypatch.setattr(Component, "db", dm)
    monkeypatch.chdir(tmp_path)

    vcc, gnd = Net("3V3"), Net("GND")
    Part("power", "PWR_FLAG")[1] += vcc
    Part("power", "PWR_FLAG")[1] += gnd
    r = Part("Device", "R", value="1k", footprint="Resistor_SMD:R_0805_2012Metric")
    r[1] += vcc
    r[2] += gnd

    ypath = tmp_path / "analysis.yaml"
    ypath.write_text("preset: op\n", encoding="utf-8")

    board = Board(size_mm=(10.0, 10.0))
    board.simulate("simyaml", spice_analysis_json_path=ypath, output_dir=tmp_path)

    cir = (tmp_path / "simyaml.cir").read_text(encoding="utf-8")
    assert ".op" in cir.lower()
