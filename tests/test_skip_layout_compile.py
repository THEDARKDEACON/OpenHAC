"""SW-006: OPENHAC_SKIP_LAYOUT skips pcbnew layout path."""

from __future__ import annotations

import os
from unittest.mock import patch

import openhac.core  # noqa: F401
import pytest
from skidl import Net, Part

from openhac.core import Board
from openhac.core.base import Component, Module


@pytest.fixture()
def seeded_r_db(tmp_db, monkeypatch):
    _, dm = tmp_db
    dm.insert_component(
        {
            "generic_name": "R_10k_0805",
            "kicad_symbol": "Device:R",
            "kicad_footprint": "Resistor_SMD:R_0805_2012Metric",
            "manufacturer": "",
            "mpn": "X",
            "description": "",
            "jlc_class": "Basic",
            # LIB-006: strict_passive_catalog_fields requires tolerance
            "tolerance": "1%",
            # LIB-006: strict_passive_attributes_json requires valid JSON object
            "attributes_json": '{"resistance": "10k", "package": "0805"}',
        }
    )
    monkeypatch.setattr(Component, "db", dm)


def test_skip_layout_env_skips_generate_layout(tmp_path, seeded_r_db, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENHAC_SKIP_LAYOUT", "1")

    vcc, gnd = Net("3V3"), Net("GND")
    Part("power", "PWR_FLAG")[1] += vcc
    Part("power", "PWR_FLAG")[1] += gnd

    class N(Module):
        def __init__(self):
            super().__init__("n")
            r = self.add(Component("R_10k_0805"))
            r["1"] += vcc
            r["2"] += gnd
            self.declare_interface("p", vcc, gnd)

    board = Board(size_mm=(20.0, 20.0))
    m = N()
    board.add_module(m)

    design_py = tmp_path / "sl.py"
    design_py.write_text("# skip layout\n", encoding="utf-8")

    with patch("openhac.compiler.layout_gen.generate_layout") as mock_layout:
        board.compile(
            project_name="skipl",
            generate_bom=True,
            auto_route=True,
            export_schematic=False,
            source_script_path=design_py,
        )

    mock_layout.assert_not_called()
    assert (tmp_path / "skipl.net").is_file()

    monkeypatch.delenv("OPENHAC_SKIP_LAYOUT", raising=False)
