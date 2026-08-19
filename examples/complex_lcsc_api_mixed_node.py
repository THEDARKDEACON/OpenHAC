"""
complex_lcsc_api_mixed_node.py — hybrid board that **forces live LCSC/jlcsearch API** lookups.

Offline USB-C + AMS1117 power path (explicit pinouts), plus passives / one IC resolved
via ``Component("Cxxxxx")`` so construction hits ``Component._live_lookup`` (jlcsearch).

Not fabrication-strict: live parts are low-confidence and may have generic footprints.
Use for network/API path validation:

  OPENHAC_DB_PATH=/tmp/openhac_api_demo.db OPENHAC_ALLOW_RISKY_PARTS=1 \\
    python3 -m openhac.cli compile examples/complex_lcsc_api_mixed_node.py \\
      --name lcsc_api --allow-risky-parts --compile-goal handoff \\
      --no-schematic --skip-layout -o build/lcsc_api

Optional enrich (needs network allowed):

  OPENHAC_ALLOW_NETWORK=1 ... --auto-enrich-board --auto-enrich-vendor jlcpcb
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_EX = Path(__file__).resolve().parent
if str(_EX) not in sys.path:
    sys.path.insert(0, str(_EX))

import openhac.core  # noqa: F401
from openhac.core import Board
from openhac.core.base import Component, Module
from openhac.core.net import Net

from _offline_parts import AMS1117_33, USB_C_HRO, mk_component as _mk

# LCSC SKUs intentionally resolved via live API (must miss local DB).
# C17513≈1k 0805, C14663=100nF, C15850=10uF class, C21190=1k 0603
_API_SKUS = ("C17513", "C14663", "C15850", "C21190")


def _live(sku: str) -> Component:
    """Construct a part so a DB miss triggers jlcsearch live lookup."""
    os.environ.setdefault("OPENHAC_ALLOW_RISKY_PARTS", "1")
    return Component(sku)


class UsbJack(Module):
    def __init__(self) -> None:
        super().__init__("UsbJack")
        self.vbus, self.gnd = Net("VBUS_5V"), Net("GND")
        self.usb = self.add(_mk("USB_C", USB_C_HRO))
        for p in ("A4", "A9", "B4", "B9"):
            self.usb[p] += self.vbus
        for p in ("A1", "A12", "B1", "B12"):
            self.usb[p] += self.gnd
        self.usb["S1"] += self.gnd
        self.usb.nc_unused_pins()
        self.pwr = self.declare_interface("pwr_5v", self.vbus, self.gnd)


class LdoChip(Module):
    def __init__(self) -> None:
        super().__init__("LdoChip")
        self.vin, self.v3v3, self.gnd = Net("VBUS_5V"), Net("3V3"), Net("GND")
        self.ldo = self.add(_mk("AMS1117_3V3", AMS1117_33))
        self.ldo["VIN"] += self.vin
        self.ldo["GND"] += self.gnd
        self.ldo["VOUT"] += self.v3v3
        self.pwr_in = self.declare_interface("pwr_5v", self.vin, self.gnd)
        self.pwr_out = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)


class ApiPassives(Module):
    """Passives from live LCSC lookup — exercises network at Component construction."""

    def __init__(self) -> None:
        super().__init__("ApiPassives")
        self.vin, self.v3v3, self.gnd = Net("VBUS_5V"), Net("3V3"), Net("GND")
        # Live API parts (generic Device:Q footprints from jlcsearch mapping)
        self.r_cc = self.add(_live("C17513"))
        self.c_in = self.add(_live("C15850"))
        self.c_out = self.add(_live("C14663"))
        self.r_led = self.add(_live("C21190"))
        # Wire as power filter + LED ballast (pin 1/2 assumed on 2-pin passives)
        self.r_cc[1] += self.vin
        self.r_cc[2] += self.gnd
        self.c_in[1] += self.vin
        self.c_in[2] += self.gnd
        self.c_out[1] += self.v3v3
        self.c_out[2] += self.gnd
        self.r_led[1] += self.v3v3
        self.r_led[2] += self.gnd
        self.pwr_5v = self.declare_interface("pwr_5v", self.vin, self.gnd)
        self.pwr_3v3 = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)


def build_board() -> Board:
    board = Board(
        size_mm=(80.0, 50.0),
        layers=2,
        compile_goal="handoff",
        declared_supply_voltages_v={"VBUS_5V": 5.0, "3V3": 3.3},
        # Live LCSC rows lack catalog voltage_rating; keep Board.strict off so REL-001
        # is not force-enabled (strict=True would override require_passive_voltage_ratings=False).
        strict=False,
        strict_kicad=False,
        require_passive_voltage_ratings=False,
    )
    usb = UsbJack()
    ldo = LdoChip()
    api = ApiPassives()
    for m in (usb, ldo, api):
        board.add_module(m)
    board.connect(usb.pwr, ldo.pwr_in)
    board.connect(usb.pwr, api.pwr_5v)
    board.connect(ldo.pwr_out, api.pwr_3v3)
    board.declare_power_rail("VBUS_5V", usb.vbus)
    board.declare_power_rail("3V3", ldo.v3v3)
    board.declare_power_rail("GND", usb.gnd)
    board.declare_rail_conversion("VBUS_5V", "3V3", efficiency=0.85)
    return board


board = build_board()

# Exported for validators
API_SKUS = _API_SKUS

if __name__ == "__main__":
    board.compile(
        project_name="lcsc_api",
        generate_bom=True,
        export_schematic=False,
        auto_route=False,
        skip_layout=True,
    )
