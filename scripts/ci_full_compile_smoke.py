#!/usr/bin/env python3
"""
Optional CI smoke test: full ``openhac compile`` with KiCad ``pcbnew`` layout (no OPENHAC_SKIP_LAYOUT).

Exits 0 with a skip message if ``pcbnew`` is not importable on this Python.
Run with the same interpreter that has KiCad bindings (often system ``python3`` after ``apt install kicad``).
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]

_SMOKE_BOARD = '''
import openhac.core  # noqa: F401
from skidl import Net, Part
from openhac.core import Board
from openhac.core.base import Module

vcc, gnd = Net("3V3"), Net("GND")
Part("power", "PWR_FLAG")[1] += vcc
Part("power", "PWR_FLAG")[1] += gnd


class Node(Module):
    def __init__(self, name: str):
        super().__init__(name)
        r = Part(
            "Device",
            "R",
            value="10k",
            footprint="Resistor_SMD:R_0805_2012Metric",
        )
        r[1] += vcc
        r[2] += gnd
        self.declare_interface("power", vcc, gnd)


a, b = Node("A"), Node("B")
board = Board(size_mm=(50.0, 40.0))
board.add_module(a)
board.add_module(b)
board.connect(a.expose_interface("power"), b.expose_interface("power"))
'''


def main() -> int:
    try:
        import pcbnew  # noqa: F401
    except ImportError:
        print(
            "SKIP: pcbnew not importable; full layout smoke test skipped (SW-006).",
            file=sys.stderr,
        )
        return 0

    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        script = tdp / "ci_smoke_board.py"
        script.write_text(_SMOKE_BOARD, encoding="utf-8")
        env = {**os.environ, "PYTHONPATH": str(_REPO)}
        if "OPENHAC_SKIP_LAYOUT" in env:
            del env["OPENHAC_SKIP_LAYOUT"]

        r = subprocess.run(
            [
                sys.executable,
                "-m",
                "openhac.cli",
                "compile",
                str(script),
                "--name",
                "ci_layout_smoke",
                "--no-route",
                "--no-schematic",
            ],
            cwd=str(tdp),
            env=env,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if r.returncode != 0:
            sys.stdout.write(r.stdout)
            sys.stderr.write(r.stderr)
            return r.returncode

        pcb = tdp / "ci_layout_smoke.kicad_pcb"
        if not pcb.is_file():
            sys.stderr.write("FAIL: ci_layout_smoke.kicad_pcb not written\n")
            return 1

        net = tdp / "ci_layout_smoke.net"
        if not net.is_file():
            sys.stderr.write("FAIL: ci_layout_smoke.net not written\n")
            return 1

        print(f"OK: layout compile produced {pcb} ({pcb.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
