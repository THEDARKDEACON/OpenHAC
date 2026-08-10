#!/usr/bin/env python3
"""FAB-051 / FAB-031: compile known-good fab golden fixture + Gerber export.

Uses ``tests/fixtures/fab_golden_board.py``. Exits 0 with SKIP if pcbnew missing.
For full gate validation (negatives + unit), prefer ``scripts/ci_validate_fab_gates.py``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_GOLDEN = _REPO / "tests" / "fixtures" / "fab_golden_board.py"


def main() -> int:
    try:
        import pcbnew  # noqa: F401
    except ImportError:
        print("SKIP: pcbnew not importable; FAB-051 fab golden skipped.", file=sys.stderr)
        return 0

    if not _GOLDEN.is_file():
        print(f"FAIL: missing golden fixture {_GOLDEN}", file=sys.stderr)
        return 1

    env = os.environ.copy()
    env["OPENHAC_NO_NETWORK"] = "1"
    env["PYTHONPATH"] = str(_REPO) + os.pathsep + env.get("PYTHONPATH", "")
    env.setdefault("KICAD_FOOTPRINT_DIR", "/usr/share/kicad/footprints")

    with tempfile.TemporaryDirectory(prefix="openhac_fab_golden_") as td:
        out = Path(td) / "out"
        out.mkdir()
        cmd = [
            sys.executable,
            "-m",
            "openhac.cli",
            "compile",
            str(_GOLDEN),
            "--name",
            "fab_golden",
            "--compile-goal",
            "fabrication",
            "--strict-footprint-pads",
            "--no-schematic",
            "--no-route",
            "-o",
            str(out),
        ]
        print("Running:", " ".join(cmd), flush=True)
        r = subprocess.run(cmd, cwd=str(_REPO), env=env)
        if r.returncode != 0:
            return r.returncode
        pcb = out / "fab_golden.kicad_pcb"
        if not pcb.is_file():
            print("FAIL: expected .kicad_pcb missing", file=sys.stderr)
            return 1
        if shutil.which("kicad-cli"):
            fab_out = out / "fab"
            gr = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "openhac.cli",
                    "export",
                    "fab",
                    str(pcb),
                    "-o",
                    str(fab_out),
                    "--zip",
                ],
                cwd=str(_REPO),
                env=env,
            )
            if gr.returncode != 0:
                print("FAIL: Gerber export (FAB-031)", file=sys.stderr)
                return gr.returncode
            print("FAB-031: Gerber export ok")
        else:
            print("SKIP Gerbers: kicad-cli not on PATH")
        print("FAB-051 smoke ok")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
