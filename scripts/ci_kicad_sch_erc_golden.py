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
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

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
            "OPENHAC_SCHEMATIC_SINGLE_SHEET": "1",
        }
        # Typical Ubuntu KiCad layout (matches CI kicad-layout-smoke).
        env.setdefault("KICAD_FOOTPRINT_DIR", "/usr/share/kicad/footprints")
        for key, val in (
            ("KICAD9_SYMBOL_DIR", "/usr/share/kicad/symbols"),
            ("KICAD8_SYMBOL_DIR", "/usr/share/kicad/symbols"),
        ):
            env.setdefault(key, val)

        out_dir = tdp / "out"
        out_dir.mkdir()
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
                "--skip-layout",
                "-o",
                str(out_dir),
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

        sch = out_dir / "ci_sch_erc_golden.kicad_sch"
        if not sch.is_file():
            # Legacy nested layout if CLI wrote a project subdir.
            nested = out_dir / "ci_sch_erc_golden" / "ci_sch_erc_golden.kicad_sch"
            sch = nested if nested.is_file() else sch
        if not sch.is_file():
            sys.stderr.write(f"FAIL: schematic not written: {sch}\n")
            return 1

        erc_json = sch.with_suffix(sch.suffix + ".erc.json")
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

        # SSO-041: multi-module Device R/C/LED node under --schematic-signoff (skip-layout).
        complex_script = _REPO / "examples" / "sso041_signoff_node.py"
        if not complex_script.is_file():
            sys.stderr.write(f"FAIL: missing complex golden {complex_script}\n")
            return 1
        c_out = tdp / "complex"
        c_out.mkdir()
        r2 = subprocess.run(
            [
                sys.executable,
                "-m",
                "openhac.cli",
                "compile",
                str(complex_script),
                "--name",
                "ci_sso041_signoff",
                "--schematic-signoff",
                "--no-route",
                "--skip-layout",
                "-o",
                str(c_out),
            ],
            cwd=str(tdp),
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
        )
        if r2.returncode != 0:
            sys.stdout.write(r2.stdout)
            sys.stderr.write(r2.stderr)
            sys.stderr.write("FAIL: SSO-041 examples/sso041_signoff_node.py compile --schematic-signoff\n")
            return r2.returncode or 1
        sch2 = c_out / "ci_sso041_signoff.kicad_sch"
        if not sch2.is_file():
            nested2 = c_out / "ci_sso041_signoff" / "ci_sso041_signoff.kicad_sch"
            sch2 = nested2 if nested2.is_file() else sch2
        if not sch2.is_file():
            sys.stderr.write(f"FAIL: SSO-041 schematic not written: {sch2}\n")
            return 1
        erc2 = sch2.with_suffix(sch2.suffix + ".erc.json")
        try:
            run_kicad_schematic_erc(
                sch2,
                output_report=erc2,
                report_format="json",
                strict=False,
            )
        except Exception as e:
            sys.stderr.write(f"FAIL: SSO-041 KiCad ERC invocation: {e}\n")
            return 1
        if not erc2.is_file():
            sys.stderr.write("FAIL: SSO-041 ERC JSON report not created\n")
            return 1
        summary2 = summarize_kicad_erc_report(erc2)
        err2 = int(summary2.get("error_count") or 0)
        if err2 != 0:
            sys.stderr.write(
                f"FAIL: SSO-041 KiCad ERC {err2} error(s). "
                f"See {erc2}\n{erc2.read_text(encoding='utf-8', errors='replace')[:4000]}\n"
            )
            return 1
        print(
            f"OK: SSO-041 complex RS-485 sign-off schematic ERC passed "
            f"(errors=0, warnings={int(summary2.get('warning_count') or 0)})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
