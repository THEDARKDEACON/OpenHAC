#!/usr/bin/env python3
"""
Minimal OpenHaC compile example.

Prerequisites:
  pip install -e .
  python -m openhac.database.seed_data   # or sync_jlc — needs ``R_10k_0805`` in the DB

Run:
  python scripts/example_build.py
"""

from __future__ import annotations

from skidl import Net, Part

import openhac.core  # noqa: F401 — KiCad / SKiDL bootstrap

from openhac.core import Board
from openhac.core.base import Component, Module

# Shared rails + power flags (KiCad ERC expects PWR_FLAG on power nets)
VCC = Net("3V3")
GND = Net("GND")
Part("power", "PWR_FLAG")[1] += VCC
Part("power", "PWR_FLAG")[1] += GND


class ResistorNode(Module):
    def __init__(self, label: str):
        super().__init__(label)
        r = self.add(Component("R_10k_0805"))
        r["1"] += VCC
        r["2"] += GND
        self.power = self.declare_interface("power", VCC, GND)


def main() -> None:
    left, right = ResistorNode("A"), ResistorNode("B")
    board = Board(size_mm=(40.0, 30.0))
    board.add_module(left)
    board.add_module(right)
    board.connect(left.expose_interface("power"), right.expose_interface("power"))

    board.compile(
        project_name="example_build",
        generate_bom=True,
        auto_route=False,
        export_schematic=False,
    )


if __name__ == "__main__":
    main()
