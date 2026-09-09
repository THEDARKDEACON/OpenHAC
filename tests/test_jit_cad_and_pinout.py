from __future__ import annotations

from pathlib import Path
import pytest
from skidl import Net

from openhac.compiler.kicad_sym_pinpos import pinout_from_kicad_symbol_id
from openhac.compiler.schematic_gen import generate_schematic
from openhac.core.base import Component, Module
from openhac.core.board import Board
from openhac.core.circuit import reset_default_circuit


def test_authentic_manufacturer_pinout_c2040():
    """Verify Component('C2040') extracts authentic manufacturer pinout from vendor CAD."""
    c = Component("C2040")
    # There are 57 physical pins on RP2040 (56 perimeter pins + 1 thermal ground pad)
    unique_pins = set(c.pins.values())
    assert len(unique_pins) == 57

    # Verify manufacturer-named pins exist
    assert "GPIO0" in c.pins
    assert "GPIO7" in c.pins
    assert "VREG_IN" in c.pins
    assert "VREG_VOUT" in c.pins
    assert "RUN" in c.pins

    # Pin access by number and name should resolve to the same pin
    assert c["GPIO7"] is c[9]
    assert c["GPIO7"].name == "GPIO7"
    assert c[9].name == "GPIO7"


def test_pinout_from_kicad_symbol_id_builtin():
    """Verify pinout extraction from standard KiCad symbol library."""
    res_pins = pinout_from_kicad_symbol_id("Device:R")
    assert res_pins is not None
    assert len(res_pins) == 2
    pin_nums = {p["num"] for p in res_pins}
    assert pin_nums == {"1", "2"}

    led_pins = pinout_from_kicad_symbol_id("Device:LED")
    assert led_pins is not None
    assert len(led_pins) == 2
    pin_names = {p["name"] for p in led_pins}
    assert "A" in pin_names or "K" in pin_names or "~" in pin_names


def test_schematic_embeds_authentic_vendor_symbol(tmp_path: Path):
    """Verify that schematic generation with a JIT-downloaded part embeds the authentic vendor symbol."""
    reset_default_circuit()

    class CoreMCU(Module):
        def __init__(self, name: str):
            super().__init__(name)
            self.mcu = self.add(Component("C2040"))
            self.r1 = self.add(Component("C21190"))

            vreg_in = Net("VREG_IN")
            gnd = Net("GND")

            self.mcu["VREG_IN"] += vreg_in
            self.r1[1] += vreg_in
            self.r1[2] += gnd
            self.mcu[57] += gnd

    board = Board((100, 100))
    board.add_module(CoreMCU("MainMCU"))

    out_file = tmp_path / "jit_test.kicad_sch"
    generate_schematic(str(out_file), board)

    assert out_file.exists()
    content = out_file.read_text(encoding="utf-8")

    # Schematic should embed the vendor symbol block
    assert "RP2040" in content
    # Should embed authentic pins in the lib_symbols block
    assert "pin power_in line" in content or "pin bidirectional line" in content
    assert '"GPIO7"' in content


def test_jit_cad_offline_handling(monkeypatch):
    """Verify that when offline (OPENHAC_NO_NETWORK=1), missing components raise clean ValueError."""
    monkeypatch.setenv("OPENHAC_NO_NETWORK", "1")
    with pytest.raises(ValueError, match="not found"):
        Component("C9999999999")
