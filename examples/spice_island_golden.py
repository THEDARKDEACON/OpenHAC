"""SPS-045 / GLD-001: analog-island golden (not Fundi MIG).

Resistor island plus bundled Apache physics (diode / opto / in-amp).
Offline — no vendor SPICE scrape. Not the FAB-051 2R ``--require-all`` class.
Schematic stamp golden remains ``examples/sso041_signoff_node.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

import openhac.core  # noqa: F401
from openhac.core import Board
from openhac.core.base import Component, Module
from openhac.core.net import Net

_MODELS = Path(__file__).resolve().parents[1] / "openhac" / "database" / "spice_models"


def _res(name: str) -> Component:
    return Component(
        name,
        {
            "generic_name": name,
            "category": "Resistor",
            "kicad_symbol": "Device:R",
            "kicad_footprint": "Resistor_SMD:R_0603_1608Metric",
            "pinout_json": json.dumps(
                [
                    {"num": "1", "name": "1", "type": "passive"},
                    {"num": "2", "name": "2", "type": "passive"},
                ]
            ),
        },
        pins={"1": ("1", "passive"), "2": ("2", "passive")},
        footprint="Resistor_SMD:R_0603_1608Metric",
    )


def _diode() -> Component:
    return Component(
        "D_1N4007",
        {
            "generic_name": "D_1N4007",
            "category": "diodes",
            "kicad_symbol": "Device:D",
            "kicad_footprint": "Diode_SMD:D_SOD-123",
            "mpn": "1N4007",
            "spice_include": str(_MODELS / "d_1n4007.cir"),
            "spice_subckt": "D1N4007",
            "pinout_json": json.dumps(
                [
                    {"num": "2", "name": "A", "type": "passive"},
                    {"num": "1", "name": "K", "type": "passive"},
                ]
            ),
        },
        pins={"2": ("A", "passive"), "1": ("K", "passive")},
        footprint="Diode_SMD:D_SOD-123",
    )


def _opto() -> Component:
    pins = [
        {"num": "1", "name": "A", "type": "passive"},
        {"num": "2", "name": "K", "type": "passive"},
        {"num": "3", "name": "E", "type": "passive"},
        {"num": "4", "name": "C", "type": "passive"},
    ]
    return Component(
        "OPTO_PC817",
        {
            "generic_name": "OPTO_PC817",
            "category": "opto",
            "kicad_symbol": "Device:R",
            "kicad_footprint": "Package_DIP:DIP-4_W7.62mm",
            "mpn": "PC817",
            "spice_include": str(_MODELS / "pc817.cir"),
            "spice_subckt": "PC817",
            "pinout_json": json.dumps(pins),
        },
        pins={"1": ("A", "passive"), "2": ("K", "passive"), "3": ("E", "passive"), "4": ("C", "passive")},
        footprint="Package_DIP:DIP-4_W7.62mm",
    )


def _inamp() -> Component:
    pins = [
        {"num": "1", "name": "RG1", "type": "passive"},
        {"num": "2", "name": "INN", "type": "input"},
        {"num": "3", "name": "INP", "type": "input"},
        {"num": "4", "name": "VSM", "type": "power_in"},
        {"num": "5", "name": "REF", "type": "passive"},
        {"num": "6", "name": "OUT", "type": "output"},
        {"num": "7", "name": "VSP", "type": "power_in"},
        {"num": "8", "name": "RG2", "type": "passive"},
    ]
    pd = {p["num"]: (p["name"], p["type"]) for p in pins}
    return Component(
        "AD620",
        {
            "generic_name": "AD620",
            "category": "amplifier",
            "kicad_symbol": "Device:R",
            "kicad_footprint": "Package_DIP:DIP-8_W7.62mm",
            "mpn": "AD620ANZ",
            "spice_include": str(_MODELS / "ad620.cir"),
            "spice_subckt": "AD620",
            "pinout_json": json.dumps(pins),
        },
        pins=pd,
        footprint="Package_DIP:DIP-8_W7.62mm",
    )


class AnalogIsland(Module):
    def __init__(self):
        super().__init__("AnalogIsland")
        self.r1 = self.add(_res("R_ISLAND_A"))
        self.r2 = self.add(_res("R_ISLAND_B"))
        vin, mid, gnd = Net("VIN"), Net("MID"), Net("GND")
        self.r1[1] += vin
        self.r1[2] += mid
        self.r2[1] += mid
        self.r2[2] += gnd


class PhysicsIsland(Module):
    """GLD-001: bundled Apache diode / opto / in-amp — not vendor macromodels."""

    def __init__(self):
        super().__init__("PhysicsIsland")
        self.d = self.add(_diode())
        self.u_opto = self.add(_opto())
        self.u_ina = self.add(_inamp())
        vin, gnd = Net("VIN"), Net("GND")
        vsp, vsm = Net("VSP"), Net("VSM")
        inp, inn, out, ref = Net("INP"), Net("INN"), Net("INA_OUT"), Net("REF")
        led_k, opto_c, opto_e = Net("LED_K"), Net("OPTO_C"), Net("OPTO_E")
        rg = Net("RG")
        self.d[2] += vin
        self.d[1] += gnd
        self.u_opto[1] += vin
        self.u_opto[2] += led_k
        self.u_opto[4] += opto_c
        self.u_opto[3] += opto_e
        self.r_led = self.add(_res("R_OPTO_LED"))
        self.r_led[1] += led_k
        self.r_led[2] += gnd
        self.u_ina[3] += inp
        self.u_ina[2] += inn
        self.u_ina[6] += out
        self.u_ina[5] += ref
        self.u_ina[7] += vsp
        self.u_ina[4] += vsm
        self.u_ina[1] += rg
        self.u_ina[8] += rg
        ref += gnd
        opto_e += gnd


class DigitalIgnored(Module):
    def __init__(self):
        super().__init__("DigitalIgnored")
        self.r = self.add(_res("R_DIGITAL"))
        a, b = Net("D0"), Net("D1")
        self.r[1] += a
        self.r[2] += b


board = Board(size_mm=(40, 30), compile_goal="handoff", strict=False)
ana = AnalogIsland()
phy = PhysicsIsland()
dig = DigitalIgnored()
board.add_module(ana)
board.add_module(phy)
board.add_module(dig)
board.declare_spice_ground("GND")
board.declare_spice_island(ana, phy)
board.declare_spice_rail("VIN", 5.0)
board.declare_spice_rail("VSP", 9.0)
board.declare_spice_rail("VSM", -9.0)
