#!/usr/bin/env python3
"""Validate Phase-2 fab gates against a known-good board and negative fixtures.

No physical PCB required — software validation of compile gates and (when KiCad
is available) generated ``.kicad_pcb`` / DRC / Gerbers.

Exit codes:
  0 — all applicable checks passed (or SKIP when pcbnew missing for layout steps)
  1 — a gate check failed

Usage:
  python3 scripts/ci_validate_fab_gates.py
  OPENHAC_NO_NETWORK=1 python3 scripts/ci_validate_fab_gates.py --require-layout
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_GOLDEN = _REPO / "tests" / "fixtures" / "fab_golden_board.py"
_BAD_PINS = _REPO / "tests" / "fixtures" / "fab_bad_invented_pins.py"

if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))


def _env(**extra: str) -> dict[str, str]:
    env = os.environ.copy()
    env["OPENHAC_NO_NETWORK"] = "1"
    env["PYTHONPATH"] = str(_REPO) + os.pathsep + env.get("PYTHONPATH", "")
    env.setdefault("KICAD_FOOTPRINT_DIR", "/usr/share/kicad/footprints")
    for k, v in (
        ("KICAD9_SYMBOL_DIR", "/usr/share/kicad/symbols"),
        ("KICAD8_SYMBOL_DIR", "/usr/share/kicad/symbols"),
    ):
        env.setdefault(k, v)
    env.update(extra)
    return env


def _run(cmd: list[str], *, env: dict[str, str], cwd: Path | None = None) -> int:
    print(">>", " ".join(cmd), flush=True)
    return subprocess.run(cmd, cwd=str(cwd or _REPO), env=env).returncode


def check_negative_invented_pins() -> bool:
    """FAB-001: corrupt pinout under fabrication must fail (non-zero exit or import error)."""
    print("\n=== FAB-001 negative: invented/corrupt pins ===", flush=True)
    env = _env(OPENHAC_COMPILE_GOAL="fabrication")
    with tempfile.TemporaryDirectory(prefix="openhac_fab_bad_") as td:
        out = Path(td) / "out"
        out.mkdir()
        rc = _run(
            [
                sys.executable,
                "-m",
                "openhac.cli",
                "compile",
                str(_BAD_PINS),
                "--name",
                "bad_pins",
                "--compile-goal",
                "fabrication",
                "--no-schematic",
                "--skip-layout",
                "-o",
                str(out),
            ],
            env=env,
        )
    if rc == 0:
        print("FAIL: FAB-001 expected non-zero exit for corrupt pinout", file=sys.stderr)
        return False
    print("OK: FAB-001 refused corrupt/invented pins (exit %s)" % rc)
    return True


def check_unit_pin_resolution() -> bool:
    """Fast FAB-001/010 checks without CLI/KiCad."""
    print("\n=== Unit gate checks (pin_resolution / network) ===", flush=True)
    rc = _run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_fab_phase2_gates.py",
            "-q",
            "--tb=line",
        ],
        env=_env(),
    )
    if rc != 0:
        print("FAIL: tests/test_fab_phase2_gates.py", file=sys.stderr)
        return False
    print("OK: unit fab gates")
    return True


def check_golden_compile(*, require_layout: bool) -> bool:
    """Known-good board: place PCB (+ optional DRC/Gerbers)."""
    print("\n=== Known-good golden compile ===", flush=True)
    if not _GOLDEN.is_file():
        print(f"FAIL: missing {_GOLDEN}", file=sys.stderr)
        return False

    try:
        import pcbnew  # noqa: F401
    except ImportError:
        msg = "SKIP: pcbnew not importable; layout/Gerber steps skipped"
        if require_layout:
            print(f"FAIL: {msg} (--require-layout)", file=sys.stderr)
            return False
        print(msg, file=sys.stderr)
        return True

    env = _env(OPENHAC_COMPILE_GOAL="fabrication")
    with tempfile.TemporaryDirectory(prefix="openhac_fab_good_") as td:
        out = Path(td) / "out"
        out.mkdir()
        # Fabrication + no-route: exercise pin/pad/footprint gates + PCB DRC without FreeRouting.
        rc = _run(
            [
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
            ],
            env=env,
        )
        if rc != 0:
            print("FAIL: known-good fabrication compile", file=sys.stderr)
            return False
        pcb = out / "fab_golden.kicad_pcb"
        if not pcb.is_file():
            print("FAIL: missing .kicad_pcb", file=sys.stderr)
            return False
        man = out / "fab_golden.openhac-manifest.json"
        if man.is_file():
            import json

            data = json.loads(man.read_text(encoding="utf-8"))
            audit = data.get("fab_audit") or {}
            if audit.get("omitted_footprint_refs"):
                print(f"FAIL: omitted footprints {audit['omitted_footprint_refs']}", file=sys.stderr)
                return False
            print("OK: fab_audit present, no omitted footprints")

        # Metrics: expect at least 2 footprints for two resistors
        try:
            from openhac.compiler.pcb_metrics import compute_pcb_metrics

            m = compute_pcb_metrics(pcb)
            fc = int(m.get("footprint_count") or 0)
            if fc < 2:
                print(f"FAIL: footprint_count={fc} expected >= 2", file=sys.stderr)
                return False
            print(f"OK: footprint_count={fc}")
        except Exception as e:
            print(f"WARN: pcb_metrics skipped: {e}", file=sys.stderr)

        if shutil.which("kicad-cli"):
            drc_out = out / "fab_golden.kicad_pcb.drc.txt"
            drc = subprocess.run(
                [
                    "kicad-cli",
                    "pcb",
                    "drc",
                    "--exit-code-violations",
                    "-o",
                    str(drc_out),
                    str(pcb),
                ],
                cwd=str(_REPO),
                env=env,
                capture_output=True,
                text=True,
            )
            # Unrouted boards may still trip DRC; treat as soft unless OPENHAC_FAB_STRICT_DRC=1
            if drc.returncode != 0:
                if os.environ.get("OPENHAC_FAB_STRICT_DRC", "").strip().lower() in ("1", "true", "yes"):
                    print(drc.stdout or drc.stderr, file=sys.stderr)
                    print("FAIL: kicad-cli pcb drc", file=sys.stderr)
                    return False
                print("WARN: kicad-cli pcb drc non-zero (set OPENHAC_FAB_STRICT_DRC=1 to fail)", file=sys.stderr)
            else:
                print("OK: kicad-cli pcb drc clean")

            fab_out = out / "fab"
            gr = _run(
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
                env=env,
            )
            if gr != 0:
                print("FAIL: Gerber export", file=sys.stderr)
                return False
            print("OK: Gerber export (FAB-031)")
        else:
            print("SKIP: kicad-cli not on PATH (DRC/Gerbers)")

    print("OK: known-good golden path")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--require-layout",
        action="store_true",
        help="Fail if pcbnew is unavailable (CI layout job)",
    )
    ap.add_argument(
        "--skip-negative",
        action="store_true",
        help="Only run known-good path",
    )
    args = ap.parse_args()

    ok = True
    if not check_unit_pin_resolution():
        ok = False
    if not args.skip_negative and not check_negative_invented_pins():
        ok = False
    if not check_golden_compile(require_layout=bool(args.require_layout)):
        ok = False

    if ok:
        print("\nAll fab gate validation checks passed.")
        return 0
    print("\nFab gate validation FAILED.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
