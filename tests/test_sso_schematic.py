"""SSO-001…040 unit tests for schematic sign-off."""

from __future__ import annotations

from pathlib import Path

import pytest

import openhac.core  # noqa: F401
from openhac.core.exceptions import SchematicGenerationError
from openhac.schematic.emit_kicad import generate_schematic
from openhac.schematic.layout import pin_world_xy
from openhac.schematic.resolve import match_power_symbol
from openhac.schematic.util import rotate_offset
from openhac.core.board import Board
from openhac.core.base import Component, Module
from openhac.core.net import Net


def test_sso002_rotate_offset_90() -> None:
    dx, dy = rotate_offset(2.54, 0.0, 90.0)
    assert abs(dx - 0.0) < 1e-9
    assert abs(dy - 2.54) < 1e-9


def test_sso003_power_symbol_never_reuses_vcc_for_3v3() -> None:
    lib_id, pin_name, is_gnd = match_power_symbol("3V3")
    assert "VCC" not in lib_id.upper() or pin_name.upper() in ("3V3", "+3V3")
    assert pin_name.upper().replace("+", "") in ("3V3", "3.3V") or lib_id.endswith("3V3") or lib_id.endswith("+3V3")
    assert is_gnd is False
    lib_gnd, gnd_pin, is_gnd2 = match_power_symbol("GND")
    assert is_gnd2 is True
    assert "GND" in lib_gnd.upper() or gnd_pin.upper() == "GND"


def test_library_symbol_embed_renames_outer_and_keeps_unit_children() -> None:
    from openhac.compiler.kicad_sym_pinpos import (
        find_symbol_library_file,
        schematic_lib_symbol_sexp,
    )

    if find_symbol_library_file("Device") is None:
        pytest.skip("Device.kicad_sym not on search path")
    body = schematic_lib_symbol_sexp("Device:C")
    assert body is not None
    assert '(symbol "Device:C"' in body
    assert '(symbol "C_0_1"' in body or '(symbol "C_1_1"' in body
    assert "(pin " in body
    stm_path = find_symbol_library_file("MCU_ST_STM32F1")
    if stm_path is not None:
        stm = schematic_lib_symbol_sexp("MCU_ST_STM32F1:STM32F103C8Tx")
        assert stm is not None
        assert '(symbol "MCU_ST_STM32F1:STM32F103C8Tx"' in stm
        assert "(pin " in stm
        assert '(symbol "STM32F103C8Tx_1_1"' in stm or '(symbol "STM32F103C8Tx_0_1"' in stm


def test_sso003_synth_power_unit_children_match_lib_id() -> None:
    from openhac.schematic.synth import synthesize_power_symbol

    lib_id, pin_name, is_gnd = match_power_symbol("VBUS_5V")
    assert lib_id.startswith("OpenHaC:")
    assert pin_name == "VBUS_5V"
    assert is_gnd is False
    short = lib_id.split(":", 1)[1]
    body = synthesize_power_symbol(lib_id, pin_name, is_gnd=False)
    assert f'(symbol "{lib_id}" (power)' in body
    assert f'(symbol "{short}_0_1"' in body
    assert f'(symbol "{short}_1_1"' in body
    assert f'(name "{pin_name}"' in body
    assert f'(symbol "{pin_name}_0_1"' in body or short == pin_name


def test_sso020_no_connect_on_unused_pin(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENHAC_SCHEMATIC_STUB_ONLY", "1")
    sig = Net("SIG")
    gnd = Net("GND")

    class M(Module):
        def __init__(self) -> None:
            super().__init__("M")
            u = self.add(
                Component(
                    "U_NC",
                    pins={
                        "1": ("OUT", "output"),
                        "2": ("NC", "no_connect"),
                        "3": ("GND", "power_in"),
                    },
                )
            )
            u["1"] += sig
            u["3"] += gnd
            r = self.add(
                Component("R_LOAD", pins={"1": ("1", "passive"), "2": ("2", "passive")})
            )
            r.fields["kicad_symbol"] = "Device:R"
            r["1"] += sig
            r["2"] += gnd

    b = Board((20, 20))
    b.add_module(M())
    out = tmp_path / "nc.kicad_sch"
    generate_schematic(str(out), b)
    text = out.read_text(encoding="utf-8")
    assert "(no_connect" in text


def test_sso021_pwr_flag_and_named_rail(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENHAC_SCHEMATIC_STUB_ONLY", "1")
    vcc = Net("3V3")
    gnd = Net("GND")

    class M(Module):
        def __init__(self) -> None:
            super().__init__("M")
            r = self.add(
                Component("R_A", pins={"1": ("1", "passive"), "2": ("2", "passive")})
            )
            r.fields["kicad_symbol"] = "Device:R"
            r["1"] += vcc
            r["2"] += gnd

    b = Board((20, 20))
    b.add_module(M())
    out = tmp_path / "pwr.kicad_sch"
    generate_schematic(str(out), b)
    text = out.read_text(encoding="utf-8")
    assert 'lib_id "power:PWR_FLAG"' in text
    assert 'lib_id "power:VCC"' not in text or "3V3" in text
    assert "power:VCC" not in text.split("3V3")[0] or 'lib_id "power:VCC"' not in text
    # 3V3 rail must not be instanced as power:VCC
    assert 'lib_id "power:VCC"' not in text


def test_sso002_rotation_composed_into_pin_world(monkeypatch) -> None:
    monkeypatch.setenv("OPENHAC_SCHEMATIC_STUB_ONLY", "1")
    from openhac.compiler.kicad_sym_pinpos import EmptySymbolPinResolver
    from skidl import Part

    p = Part("Device", "R", value="1k", ref="R90")
    p.fields["OpenHaC_Rotation_Deg"] = "90"
    pin = p[1]
    resolver = EmptySymbolPinResolver()
    x, y, _ = pin_world_xy(pin, p, (0.0, 0.0), 90.0, resolver)
    # Stub offset is (0, ±2.54); 90° maps (0, dy) → (-dy, 0).
    assert abs(y) < 0.02
    assert abs(abs(x) - 2.54) < 0.02


def test_sso010_signoff_fails_passive_without_device_symbol(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    from openhac.compiler.kicad_sym_pinpos import find_symbol_library_file

    if find_symbol_library_file("Device") is None:
        pytest.skip("Device.kicad_sym not on search path")

    class M(Module):
        def __init__(self) -> None:
            super().__init__("M")
            r = self.add(
                Component(
                    "mystery_passive",
                    pins={"1": ("1", "passive"), "2": ("2", "passive")},
                    footprint="Resistor_SMD:R_0603_1608Metric",
                )
            )
            r.fields["kicad_symbol"] = ""
            r.fields["kiCad_symbol"] = ""

    b = Board((10, 10))
    b.add_module(M())
    out = tmp_path / "fail.kicad_sch"
    with pytest.raises(SchematicGenerationError, match="SSO-010"):
        generate_schematic(str(out), b, signoff=True)


def test_sso004_circuit_generate_schematic_writes_wires(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENHAC_SCHEMATIC_STUB_ONLY", "1")
    from openhac.core.circuit import default_circuit, reset_default_circuit
    from openhac.core.part import Part, Pin
    from openhac.core.net import Net as CoreNet

    reset_default_circuit()
    n = CoreNet("PAIR")
    p1 = Part("R1", "Resistor_SMD:R_0603_1608Metric", {"kicad_symbol": "Device:R"}, [
        Pin("1", "1", "passive"), Pin("2", "2", "passive"),
    ], value="1k")
    p2 = Part("R2", "Resistor_SMD:R_0603_1608Metric", {"kicad_symbol": "Device:R"}, [
        Pin("1", "1", "passive"), Pin("2", "2", "passive"),
    ], value="1k")
    default_circuit.add_part(p1)
    default_circuit.add_part(p2)
    p1["1"] += n
    p2["1"] += n
    out = tmp_path / "circ.kicad_sch"
    default_circuit.generate_schematic(out)
    text = out.read_text(encoding="utf-8")
    assert "(kicad_sch" in text
    assert "(wire (pts" in text or "(label" in text
    assert "Device:IC" not in text
