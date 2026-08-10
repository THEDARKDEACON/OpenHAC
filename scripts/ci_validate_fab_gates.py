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
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_GOLDEN = _REPO / "tests" / "fixtures" / "fab_golden_board.py"
_BAD_PINS = _REPO / "tests" / "fixtures" / "fab_bad_invented_pins.py"
_BAD_FP = _REPO / "tests" / "fixtures" / "fab_bad_missing_footprint.py"

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


def _freerouting_available() -> bool:
    jar = (os.environ.get("FREEROUTING_JAR") or "").strip()
    if jar and Path(jar).is_file():
        return True
    return bool(shutil.which("freerouting") or shutil.which("freeRouting"))


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


def check_negative_invented_pins() -> bool:
    """FAB-001: corrupt pinout under fabrication must fail."""
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


def check_negative_missing_footprint(*, require_layout: bool) -> bool:
    """FAB-003: missing footprint library must fail fabrication layout."""
    print("\n=== FAB-003 negative: missing footprint ===", flush=True)
    if not _BAD_FP.is_file():
        print(f"FAIL: missing {_BAD_FP}", file=sys.stderr)
        return False
    try:
        import pcbnew  # noqa: F401
    except ImportError:
        msg = "SKIP: pcbnew not importable; FAB-003 layout negative skipped"
        if require_layout:
            print(f"FAIL: {msg} (--require-layout)", file=sys.stderr)
            return False
        print(msg, file=sys.stderr)
        return True

    env = _env(OPENHAC_COMPILE_GOAL="fabrication")
    with tempfile.TemporaryDirectory(prefix="openhac_fab_badfp_") as td:
        out = Path(td) / "out"
        out.mkdir()
        rc = _run(
            [
                sys.executable,
                "-m",
                "openhac.cli",
                "compile",
                str(_BAD_FP),
                "--name",
                "bad_fp",
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
    if rc == 0:
        print("FAIL: FAB-003 expected non-zero exit for missing footprint", file=sys.stderr)
        return False
    print("OK: FAB-003 refused missing footprint (exit %s)" % rc)
    return True


def _assert_fab_audit(man: Path) -> bool:
    if not man.is_file():
        print("FAIL: missing openhac-manifest.json", file=sys.stderr)
        return False
    data = json.loads(man.read_text(encoding="utf-8"))
    audit = data.get("fab_audit")
    if not isinstance(audit, dict):
        print("FAIL: fab_audit missing from manifest", file=sys.stderr)
        return False
    if audit.get("schema_ref") != "openhac.fab_audit.v1":
        print(f"FAIL: unexpected fab_audit schema_ref={audit.get('schema_ref')!r}", file=sys.stderr)
        return False
    omitted = audit.get("omitted_footprint_refs") or []
    if omitted:
        print(f"FAIL: omitted footprints {omitted}", file=sys.stderr)
        return False
    if audit.get("compile_goal") != "fabrication":
        print(f"FAIL: fab_audit.compile_goal={audit.get('compile_goal')!r}", file=sys.stderr)
        return False
    print("OK: fab_audit present and clean")
    return True


def check_golden_compile(*, require_layout: bool, try_route: bool) -> bool:
    """Known-good board: place PCB (+ optional route/DRC/Gerbers)."""
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

    do_route = bool(try_route and _freerouting_available())
    if try_route and not do_route:
        print("SKIP route: FreeRouting not configured (FREEROUTING_JAR); using --no-route", flush=True)

    env = _env(OPENHAC_COMPILE_GOAL="fabrication")
    if do_route:
        env["OPENHAC_FAB_STRICT_DRC"] = "1"

    with tempfile.TemporaryDirectory(prefix="openhac_fab_good_") as td:
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
            "-o",
            str(out),
        ]
        if do_route:
            print("Using FreeRouting + strict PCB DRC path", flush=True)
        else:
            cmd.append("--no-route")
        rc = _run(cmd, env=env)
        if rc != 0:
            print("FAIL: known-good fabrication compile", file=sys.stderr)
            return False
        pcb = out / "fab_golden.kicad_pcb"
        if not pcb.is_file():
            print("FAIL: missing .kicad_pcb", file=sys.stderr)
            return False

        man = out / "fab_golden.openhac-manifest.json"
        if not _assert_fab_audit(man):
            return False

        from openhac.compiler.pcb_metrics import compute_pcb_metrics

        m = compute_pcb_metrics(pcb)
        if not m:
            print("FAIL: pcb_metrics returned empty (pcbnew load failed?)", file=sys.stderr)
            return False
        fc = int(m.get("footprint_count") or 0)
        if fc < 2:
            print(f"FAIL: footprint_count={fc} expected >= 2", file=sys.stderr)
            return False
        print(f"OK: footprint_count={fc}")

        if shutil.which("kicad-cli"):
            if do_route:
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
                if drc.returncode != 0:
                    print(drc.stdout or drc.stderr, file=sys.stderr)
                    print("FAIL: kicad-cli pcb drc (routed fab golden)", file=sys.stderr)
                    return False
                print("OK: kicad-cli pcb drc clean (routed)")
            else:
                print("OK: PCB DRC deferred (--no-route; unconnected items expected)")

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
            zips = list(Path(fab_out).glob("*.zip")) + list(out.glob("fab.zip"))
            # export writes zip next to out dir as fab.zip when -o fab --zip
            fab_zip = out / "fab.zip"
            if not fab_zip.is_file() and not any(Path(fab_out).glob("*")):
                print("FAIL: Gerber export produced no outputs", file=sys.stderr)
                return False
            print("OK: Gerber export (FAB-031)")
        else:
            print("FAIL: kicad-cli not on PATH (required for Gerber validation when layout runs)", file=sys.stderr)
            if require_layout:
                return False
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
    ap.add_argument(
        "--try-route",
        action="store_true",
        default=True,
        help="If FreeRouting is configured, compile with routing + strict DRC (default: on)",
    )
    ap.add_argument(
        "--no-try-route",
        action="store_true",
        help="Never attempt FreeRouting; always --no-route",
    )
    args = ap.parse_args()
    try_route = bool(args.try_route) and not bool(args.no_try_route)

    ok = True
    if not check_unit_pin_resolution():
        ok = False
    if not args.skip_negative:
        if not check_negative_invented_pins():
            ok = False
        if not check_negative_missing_footprint(require_layout=bool(args.require_layout)):
            ok = False
    if not check_golden_compile(
        require_layout=bool(args.require_layout),
        try_route=try_route,
    ):
        ok = False

    if ok:
        print("\nAll fab gate validation checks passed.")
        return 0
    print("\nFab gate validation FAILED.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
