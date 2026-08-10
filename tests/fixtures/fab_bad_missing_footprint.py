"""Negative fixture: valid pins but missing footprint library → FAB-003 under fabrication+layout."""

from __future__ import annotations

import json

import openhac.core  # noqa: F401
from openhac.core import Board
from openhac.core.base import Component, Module
from openhac.core.net import Net

_PINS = {1: ("1", "passive"), 2: ("2", "passive")}
_FAKE_FP = "OpenHaC_MissingLib:DoesNotExist_0805"


def _comp_data(generic_name: str) -> dict:
    pinout = [{"num": str(n), "name": info[0], "type": info[1]} for n, info in _PINS.items()]
    return {
        "generic_name": generic_name,
        "mpn": generic_name,
        "manufacturer": "OpenHaC",
        "description": "Fab negative: missing footprint",
        "category": "Resistor",
        "package": "0805",
        "kicad_symbol": "Device:R",
        "kicad_footprint": _FAKE_FP,
        "pinout_json": json.dumps(pinout),
    }


class BadFpNode(Module):
    def __init__(self, name: str, vcc: Net, gnd: Net) -> None:
        super().__init__(name)
        gn = f"R_MISSING_FP_{name}"
        r = Component(gn, comp_data=_comp_data(gn), pins=_PINS)
        part = getattr(r, "part", None)
        if part is not None:
            part.footprint = _FAKE_FP
        r[1] += vcc
        r[2] += gnd
        self.add(r)
        self.declare_interface("power", vcc, gnd)


vcc = Net("3V3")
gnd = Net("GND")
board = Board(size_mm=(40.0, 30.0), compile_goal="fabrication")
board.add_module(BadFpNode("A", vcc, gnd))
