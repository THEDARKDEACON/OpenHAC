"""Unit tests for ABC advanced board capabilities."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from openhac.compiler.advanced_board_policy import (
    check_bga_fab_gate,
    check_highspeed_fab_gate,
    check_rf_fab_gate,
    footprint_looks_like_bga,
)
from openhac.database.passive_ratings import (
    enrich_comp_data_from_jlc_item,
    parse_power_watts,
    parse_voltage_rating_v,
    stock_footprint_for_package,
)


def test_abc026_bga_heuristic():
    assert footprint_looks_like_bga("Package_BGA:BGA-100_10x10mm")
    assert footprint_looks_like_bga("", "WLCSP-16")
    assert not footprint_looks_like_bga("Package_SO:SOIC-8_3.9x4.9mm_P1.27mm")


def test_abc027_bga_fab_gate(tmp_path, monkeypatch):
    from openhac.core import Board
    from openhac.core.base import Component, Module
    from openhac.core.net import Net

    class M(Module):
        def __init__(self):
            super().__init__("BgaMod")
            data = {
                "generic_name": "FAKE_BGA",
                "kicad_footprint": "Package_BGA:BGA-64_8x8mm",
                "kicad_symbol": "Device:Q",
                "pinout_json": json.dumps(
                    [{"num": "1", "name": "1", "type": "passive"}, {"num": "2", "name": "2", "type": "passive"}]
                ),
                "category": "ic",
                "jlc_class": "Basic",
            }
            self.c = self.add(Component("FAKE_BGA", comp_data=data))
            self.gnd = Net("GND")
            self.c[1] += self.gnd
            self.c[2] += self.gnd

    board = Board(size_mm=(50, 50), compile_goal="fabrication", strict=False)
    board.add_module(M())
    viols = check_bga_fab_gate(board)
    assert viols and "ABC-027" in viols[0]
    board.quality_gates["allow_manual_bga_fanout"] = True
    assert check_bga_fab_gate(board) == []


def test_abc036_highspeed_stackup_gate():
    from openhac.core import Board

    board = Board(size_mm=(50, 50), board_class="highspeed", compile_goal="fabrication", strict=False)
    viols = check_highspeed_fab_gate(board)
    assert any("ABC-036" in v for v in viols)
    board.declare_stackup_reference(str(Path("docs/stackup_template.yaml")), role="primary")
    viols2 = check_highspeed_fab_gate(board)
    assert not any("ABC-036" in v for v in viols2)


def test_abc046_rf_keepout_gate():
    from openhac.core import Board
    from openhac.core.base import Component, Module
    from openhac.core.net import Net

    class M(Module):
        def __init__(self):
            super().__init__("RfMod")
            data = {
                "generic_name": "ESP32_C3_WROOM_02",
                "kicad_footprint": "RF_Module:ESP32-C3-WROOM-02",
                "kicad_symbol": "Device:Q",
                "pinout_json": json.dumps(
                    [{"num": "1", "name": "3V3", "type": "power"}, {"num": "2", "name": "GND", "type": "power"}]
                ),
                "category": "MCU",
                "jlc_class": "Basic",
            }
            self.c = self.add(Component("ESP32_C3_WROOM_02", comp_data=data))
            self.v, self.g = Net("3V3"), Net("GND")
            self.c[1] += self.v
            self.c[2] += self.g

    board = Board(size_mm=(50, 50), board_class="rf", compile_goal="fabrication", strict=False)
    board.add_module(M())
    viols = check_rf_fab_gate(board)
    assert any("ABC-046" in v for v in viols)
    board.declare_keepout_rect(5, 5, 20, 20, purpose="rf_module_courtyard")
    board.declare_copper_pour_intent(Net("GND"), purpose="ground")
    viols2 = check_rf_fab_gate(board)
    assert viols2 == []


def test_abc018_voltage_rating_parse():
    assert parse_voltage_rating_v("50V 100nF X7R") == 50.0
    assert parse_power_watts("125mW 1kΩ") == pytest.approx(0.125)
    fp, src = stock_footprint_for_package("0805", kind="resistor")
    assert "R_0805" in fp and src == "stock_kicad"
    data = enrich_comp_data_from_jlc_item(
        {"description": ""},
        {"package": "0805", "description": "150V 1kΩ Thick Film Resistor 125mW", "category": "Resistors"},
    )
    assert data.get("voltage_rating") == 150.0
    assert "Resistor_SMD" in str(data.get("kicad_footprint"))


def test_abc016_live_lookup_respects_no_network(monkeypatch):
    from openhac.core.base import Component

    monkeypatch.setenv("OPENHAC_NO_NETWORK", "1")
    monkeypatch.delenv("OPENHAC_ALLOW_NETWORK", raising=False)
    assert Component._live_lookup("C17513") is None
