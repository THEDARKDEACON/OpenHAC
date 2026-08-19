"""SSO-041 golden: multi-module board that must pass ``kicad-cli sch erc`` (errors=0).

Each module is Device:R / Device:C / Device:LED on named 3V3/GND (power ports +
PWR_FLAG). No floating signal labels. Offline — no network.
Used by ``scripts/ci_kicad_sch_erc_golden.py``.
"""

from __future__ import annotations

import openhac.core  # noqa: F401
from openhac.core import Board
from openhac.core.base import Component, Module
from openhac.core.net import Net


def _r(name: str, ohms: str = "10k") -> Component:
    c = Component(
        name,
        {
            "generic_name": name,
            "category": "Resistor",
            "kicad_symbol": "Device:R",
            "kicad_footprint": "Resistor_SMD:R_0603_1608Metric",
            "pinout_json": '[{"num":"1","name":"1","type":"passive"},{"num":"2","name":"2","type":"passive"}]',
        },
        pins={"1": ("1", "passive"), "2": ("2", "passive")},
        footprint="Resistor_SMD:R_0603_1608Metric",
    )
    c.part.fields["kicad_symbol"] = "Device:R"
    c.part.value = ohms
    return c


def _c(name: str, val: str = "100nF") -> Component:
    c = Component(
        name,
        {
            "generic_name": name,
            "category": "Capacitor",
            "kicad_symbol": "Device:C",
            "kicad_footprint": "Capacitor_SMD:C_0603_1608Metric",
            "pinout_json": '[{"num":"1","name":"1","type":"passive"},{"num":"2","name":"2","type":"passive"}]',
        },
        pins={"1": ("1", "passive"), "2": ("2", "passive")},
        footprint="Capacitor_SMD:C_0603_1608Metric",
    )
    c.part.fields["kicad_symbol"] = "Device:C"
    c.part.value = val
    return c


def _led(name: str) -> Component:
    c = Component(
        name,
        {
            "generic_name": name,
            "category": "LED",
            "kicad_symbol": "Device:LED",
            "kicad_footprint": "LED_SMD:LED_0603_1608Metric",
            "pinout_json": '[{"num":"1","name":"K","type":"passive"},{"num":"2","name":"A","type":"passive"}]',
        },
        pins={"1": ("K", "passive"), "2": ("A", "passive")},
        footprint="LED_SMD:LED_0603_1608Metric",
    )
    c.part.fields["kicad_symbol"] = "Device:LED"
    return c


class Rails(Module):
    def __init__(self) -> None:
        super().__init__("Rails")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.cdec = self.add(_c("C_DEC_100N", "100nF"))
        self.cdec[1] += self.v3v3
        self.cdec[2] += self.gnd
        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)


class PullupA(Module):
    def __init__(self) -> None:
        super().__init__("PullupA")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.r = self.add(_r("R_PU_A_10K", "10k"))
        self.r[1] += self.v3v3
        self.r[2] += self.gnd
        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)


class PullupB(Module):
    def __init__(self) -> None:
        super().__init__("PullupB")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.r = self.add(_r("R_PU_B_10K", "10k"))
        self.r[1] += self.v3v3
        self.r[2] += self.gnd
        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)


class StatusLed(Module):
    def __init__(self) -> None:
        super().__init__("StatusLed")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.rled = self.add(_r("R_LED_1K", "1k"))
        self.led = self.add(_led("D_STATUS"))
        self.rled[1] += self.v3v3
        self.rled[2] += self.gnd
        self.led[2] += self.v3v3
        self.led[1] += self.gnd
        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)


def build_board() -> Board:
    rails, a, b, led = Rails(), PullupA(), PullupB(), StatusLed()
    board = Board(size_mm=(80.0, 50.0))
    board.add_module(rails)
    board.add_module(a)
    board.add_module(b)
    board.add_module(led)
    board.connect(rails.pwr, a.pwr)
    board.connect(rails.pwr, b.pwr)
    board.connect(rails.pwr, led.pwr)
    return board


board = build_board()
