"""FAB golden board — known-good tiny design for gate validation.

Two modules, each with one 0805 resistor across 3V3/GND. Explicit pinouts
(FAB-001 safe). Standard KiCad footprint ``Resistor_SMD:R_0805_2012Metric``.
Uses ``comp_data=`` so construction never hits network/JIT (FAB-010/011).

Used by ``scripts/ci_validate_fab_gates.py`` and ``scripts/ci_fab_golden.py``.
"""

from __future__ import annotations

import json

import openhac.core  # noqa: F401 — circuit bootstrap
from openhac.core import Board
from openhac.core.base import Component, Module
from openhac.core.net import Net

_FOOTPRINT = "Resistor_SMD:R_0805_2012Metric"
_PINS = {1: ("1", "passive"), 2: ("2", "passive")}


def _resistor_comp_data(generic_name: str) -> dict:
    pinout = [
        {"num": str(n), "name": info[0], "type": info[1]}
        for n, info in _PINS.items()
    ]
    return {
        "generic_name": generic_name,
        "mpn": generic_name,
        "manufacturer": "OpenHaC",
        "description": "Fab golden 0805 resistor",
        "category": "Resistor",
        "package": "0805",
        "kicad_symbol": "Device:R",
        "kicad_footprint": _FOOTPRINT,
        "pinout_json": json.dumps(pinout),
    }


class ResistorNode(Module):
    def __init__(self, name: str, vcc: Net, gnd: Net) -> None:
        super().__init__(name)
        gn = f"R_10k_{name}"
        r = Component(gn, comp_data=_resistor_comp_data(gn), pins=_PINS)
        part = getattr(r, "part", None)
        if part is not None:
            part.footprint = _FOOTPRINT
            try:
                fields = getattr(part, "fields", None)
                if isinstance(fields, dict):
                    fields["Footprint"] = _FOOTPRINT
            except Exception:
                pass
        r[1] += vcc
        r[2] += gnd
        self.add(r)
        self.declare_interface("power", vcc, gnd)


vcc = Net("3V3")
gnd = Net("GND")
node_a = ResistorNode("A", vcc, gnd)
node_b = ResistorNode("B", vcc, gnd)

# Default handoff for local ``python board.py``; CI validators override via CLI/env.
board = Board(size_mm=(50.0, 40.0), compile_goal="handoff")
board.add_module(node_a)
board.add_module(node_b)
board.connect(node_a.expose_interface("power"), node_b.expose_interface("power"))
