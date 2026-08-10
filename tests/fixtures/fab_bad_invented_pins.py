"""Negative fixture: corrupt pinout_json → must fail under fabrication (FAB-001)."""

from __future__ import annotations

import openhac.core  # noqa: F401
from openhac.core import Board
from openhac.core.base import Component, Module
from openhac.core.net import Net

vcc = Net("3V3")
gnd = Net("GND")


class BadNode(Module):
    def __init__(self, name: str) -> None:
        super().__init__(name)
        # Corrupt pinout — fabrication must refuse inventing pins (FAB-001).
        r = Component(
            "BAD_PINOUT_PART",
            comp_data={
                "generic_name": "BAD_PINOUT_PART",
                "package": "WEIRD-PKG",
                "pinout_json": "{not-valid-json",
                "kicad_footprint": "Resistor_SMD:R_0805_2012Metric",
                "kicad_symbol": "Device:R",
                "category": "Resistor",
            },
        )
        r[1] += vcc
        r[2] += gnd
        self.add(r)
        self.declare_interface("power", vcc, gnd)


board = Board(size_mm=(30.0, 30.0), compile_goal="fabrication")
board.add_module(BadNode("N"))
