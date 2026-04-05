#!/usr/bin/env python3
"""
SCH-003: generate a minimal schematic with OpenHaC, run ``kicad-cli sch erc``, assert zero JSON errors.

Expects KiCad installed (Ubuntu ``apt install kicad``). Uses ``OPENHAC_SKIP_LAYOUT=1`` so pcbnew is not required.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]

_GOLDEN_DESIGN = '''
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
    if not shutil.which("kicad-cli"):
        print("ERROR: kicad-cli not on PATH (install KiCad).", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        script = tdp / "golden_erc_board.py"
        script.write_text(_GOLDEN_DESIGN, encoding="utf-8")
        env = {
            **os.environ,
            "PYTHONPATH": str(_REPO),
            "OPENHAC_SKIP_LAYOUT": "1",
        }
        # Typical Ubuntu KiCad layout (matches CI kicad-layout-smoke).
        env.setdefault("KICAD_FOOTPRINT_DIR", "/usr/share/kicad/footprints")
        for key, val in (
            ("KICAD9_SYMBOL_DIR", "/usr/share/kicad/symbols"),
            ("KICAD8_SYMBOL_DIR", "/usr/share/kicad/symbols"),
        ):
            env.setdefault(key, val)

        r = subprocess.run(
            [
                sys.executable,
                "-m",
                "openhac.cli",
                "compile",
                str(script),
                "--name",
                "ci_sch_erc_golden",
                "--no-route",
            ],
            cwd=str(tdp),
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if r.returncode != 0:
            sys.stdout.write(r.stdout)
            sys.stderr.write(r.stderr)
            return r.returncode

        sch = tdp / "ci_sch_erc_golden.kicad_sch"
        if not sch.is_file():
            sys.stderr.write(f"FAIL: schematic not written: {sch}\n")
            return 1

        erc_json = tdp / "ci_sch_erc_golden.kicad_sch.erc.json"
        from openhac.compiler.kicad_sch_erc import run_kicad_schematic_erc
        from openhac.compiler.kicad_erc_report import summarize_kicad_erc_report

        try:
            run_kicad_schematic_erc(
                sch,
                output_report=erc_json,
                report_format="json",
                strict=False,
            )
        except Exception as e:
            sys.stderr.write(f"FAIL: KiCad ERC invocation: {e}\n")
            return 1

        if not erc_json.is_file():
            sys.stderr.write("FAIL: ERC JSON report not created\n")
            return 1

        summary = summarize_kicad_erc_report(erc_json)
        err_n = int(summary.get("error_count") or 0)
        if err_n != 0:
            sys.stderr.write(
                f"FAIL: KiCad schematic ERC reported {err_n} error(s). "
                f"See {erc_json}\n{erc_json.read_text(encoding='utf-8', errors='replace')[:4000]}\n"
            )
            return 1

        warn_n = int(summary.get("warning_count") or 0)
        print(
            f"OK: KiCad schematic ERC golden passed (errors=0, warnings={warn_n}, format={summary.get('format')})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
