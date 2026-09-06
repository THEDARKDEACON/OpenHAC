#!/usr/bin/env python3
"""End-to-end production validation: code → ERC → DRC → place → route → Gerbers.

Proves the *software* fabrication-readiness claim for the **2×0805 resistor golden**
(`tests/fixtures/fab_golden_board.py`). See docs/internal/PRODUCTION_VALIDATION.md.
Does not claim multi-IC, physical, or HS/RF sign-off.

Exit codes:
  0 — all requested stages passed
  1 — a required stage failed

Usage:
  OPENHAC_NO_NETWORK=1 python3 scripts/ci_validate_production.py --logic-only
  FREEROUTING_JAR=/path/to/freerouting.jar \\
    OPENHAC_NO_NETWORK=1 python3 scripts/ci_validate_production.py --require-all
  OPENHAC_NO_NETWORK=1 python3 scripts/ci_validate_production.py --require-all --fetch-freerouting
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_GOLDEN = _REPO / "tests" / "fixtures" / "fab_golden_board.py"
_BAD_PINS = _REPO / "tests" / "fixtures" / "fab_bad_invented_pins.py"
_BAD_FP = _REPO / "tests" / "fixtures" / "fab_bad_missing_footprint.py"

# Pinned FreeRouting release used by CI / --fetch-freerouting (Java 25+).
_FREEROUTING_VERSION = "2.2.4"
_FREEROUTING_URL = (
    f"https://github.com/freerouting/freerouting/releases/download/"
    f"v{_FREEROUTING_VERSION}/freerouting-{_FREEROUTING_VERSION}.jar"
)
_FREEROUTING_CACHE = Path.home() / ".cache" / "openhac" / f"freerouting-{_FREEROUTING_VERSION}.jar"

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
    env.setdefault("OPENHAC_FREEROUTING_TIMEOUT_S", "300")
    env.update(extra)
    return env


def _run(cmd: list[str], *, env: dict[str, str], cwd: Path | None = None) -> int:
    print(">>", " ".join(cmd), flush=True)
    return subprocess.run(cmd, cwd=str(cwd or _REPO), env=env).returncode


def _pcbnew_ok() -> bool:
    try:
        import pcbnew  # noqa: F401

        return True
    except ImportError:
        return False


def _freerouting_jar() -> Path | None:
    jar = (os.environ.get("FREEROUTING_JAR") or "").strip()
    if jar and Path(jar).is_file():
        return Path(jar)
    if _FREEROUTING_CACHE.is_file():
        return _FREEROUTING_CACHE
    return None


def fetch_freerouting(*, force: bool = False) -> Path:
    dest = _FREEROUTING_CACHE
    if dest.is_file() and not force:
        print(f"OK: using cached FreeRouting jar {dest}", flush=True)
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".jar.partial")
    print(f"Fetching FreeRouting {_FREEROUTING_VERSION} → {dest}", flush=True)
    urllib.request.urlretrieve(_FREEROUTING_URL, tmp)  # nosec B310 — pinned HTTPS release URL
    tmp.replace(dest)
    print(f"OK: downloaded {dest} ({dest.stat().st_size} bytes)", flush=True)
    return dest


def stage_v0_unit_gates() -> bool:
    print("\n=== V0: Unit FAB gates ===", flush=True)
    rc = _run(
        [sys.executable, "-m", "pytest", "tests/test_fab_phase2_gates.py", "-q", "--tb=line"],
        env=_env(),
    )
    if rc != 0:
        print("FAIL: V0 unit gates", file=sys.stderr)
        return False
    print("OK: V0 unit gates")
    return True


def stage_v1_v2_native_erc_drc() -> bool:
    """Compile golden with --skip-layout so native ERC/DRC run without pcbnew."""
    print("\n=== V1/V2: Native ERC + OpenHaC DRC (skip-layout) ===", flush=True)
    if not _GOLDEN.is_file():
        print(f"FAIL: missing {_GOLDEN}", file=sys.stderr)
        return False
    with tempfile.TemporaryDirectory(prefix="openhac_prod_logic_") as td:
        out = Path(td) / "out"
        out.mkdir()
        rc = _run(
            [
                sys.executable,
                "-m",
                "openhac.cli",
                "compile",
                str(_GOLDEN),
                "--name",
                "prod_logic",
                "--production",
                "--compile-goal",
                "fabrication",
                "--strict-footprint-pads",
                "--require-verified-parts",
                "--no-schematic",
                "--skip-layout",
                "-o",
                str(out),
            ],
            env=_env(),
        )
        if rc != 0:
            print("FAIL: native ERC/DRC compile", file=sys.stderr)
            return False
        man = out / "prod_logic.openhac-manifest.json"
        if not man.is_file():
            print("FAIL: missing manifest after logic compile", file=sys.stderr)
            return False
    print("OK: V1 native ERC + V2 OpenHaC DRC")
    return True


def stage_v3_negatives(*, require_layout: bool) -> bool:
    print("\n=== V3: Negative gates (FAB-001 / FAB-003) ===", flush=True)
    ok = True
    with tempfile.TemporaryDirectory(prefix="openhac_prod_neg_") as td:
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
            env=_env(OPENHAC_COMPILE_GOAL="fabrication"),
        )
        if rc == 0:
            print("FAIL: FAB-001 expected non-zero exit", file=sys.stderr)
            ok = False
        else:
            print(f"OK: FAB-001 refused corrupt pins (exit {rc})")

    if not _BAD_FP.is_file():
        print(f"FAIL: missing {_BAD_FP}", file=sys.stderr)
        return False
    if not _pcbnew_ok():
        msg = "SKIP: FAB-003 layout negative (pcbnew unavailable)"
        if require_layout:
            print(f"FAIL: {msg}", file=sys.stderr)
            return False
        print(msg, file=sys.stderr)
        return ok

    with tempfile.TemporaryDirectory(prefix="openhac_prod_badfp_") as td:
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
            env=_env(OPENHAC_COMPILE_GOAL="fabrication"),
        )
        if rc == 0:
            print("FAIL: FAB-003 expected non-zero exit", file=sys.stderr)
            ok = False
        else:
            print(f"OK: FAB-003 refused missing footprint (exit {rc})")
    return ok


def stage_v4_schematic_erc() -> bool:
    """KiCad schematic ERC via the SCH-003 golden (SKiDL Device:R + PWR_FLAG).

    The native fab golden focuses on PCB/fab gates; pretty ``.kicad_sch`` for native
    parts still emits dangling-label noise. SCH-003 is the authoritative sch ERC gate.
    """
    print("\n=== V4: KiCad schematic ERC (SCH-003 golden) ===", flush=True)
    if not shutil.which("kicad-cli"):
        print("FAIL: kicad-cli not on PATH (required for V4)", file=sys.stderr)
        return False
    sch_script = _REPO / "scripts" / "ci_kicad_sch_erc_golden.py"
    if not sch_script.is_file():
        print(f"FAIL: missing {sch_script}", file=sys.stderr)
        return False
    rc = _run([sys.executable, str(sch_script)], env=_env())
    if rc != 0:
        print("FAIL: schematic ERC golden", file=sys.stderr)
        return False
    print("OK: V4 schematic ERC clean")
    return True


def _assert_fab_audit(man: Path) -> bool:
    if not man.is_file():
        print("FAIL: missing openhac-manifest.json", file=sys.stderr)
        return False
    data = json.loads(man.read_text(encoding="utf-8"))
    audit = data.get("fab_audit")
    if not isinstance(audit, dict):
        print("FAIL: fab_audit missing", file=sys.stderr)
        return False
    if audit.get("schema_ref") != "openhac.fab_audit.v1":
        print(f"FAIL: fab_audit schema_ref={audit.get('schema_ref')!r}", file=sys.stderr)
        return False
    if audit.get("omitted_footprint_refs"):
        print(f"FAIL: omitted footprints {audit.get('omitted_footprint_refs')}", file=sys.stderr)
        return False
    if audit.get("gates_passed") is not True:
        print(f"FAIL: fab_audit.gates_passed={audit.get('gates_passed')!r}", file=sys.stderr)
        return False
    if audit.get("enrich_failures"):
        print(f"FAIL: enrich_failures {audit.get('enrich_failures')}", file=sys.stderr)
        return False
    if audit.get("compile_goal") != "fabrication":
        print(f"FAIL: compile_goal={audit.get('compile_goal')!r}", file=sys.stderr)
        return False
    print("OK: fab_audit present and clean")
    return True


def stage_v5_v6_v7_pcb(*, require_route: bool, jar: Path | None) -> bool:
    print("\n=== V5–V7: Place / route / PCB DRC / Gerbers ===", flush=True)
    if not _pcbnew_ok():
        print("FAIL: pcbnew not importable", file=sys.stderr)
        return False
    if not shutil.which("kicad-cli"):
        print("FAIL: kicad-cli not on PATH", file=sys.stderr)
        return False

    do_route = bool(require_route)
    if do_route and jar is None:
        print(
            "FAIL: FreeRouting JAR required for production claim "
            "(set FREEROUTING_JAR or pass --fetch-freerouting)",
            file=sys.stderr,
        )
        return False

    env = _env(OPENHAC_COMPILE_GOAL="fabrication")
    if do_route and jar is not None:
        env["FREEROUTING_JAR"] = str(jar)
        env["OPENHAC_FAB_STRICT_DRC"] = "1"

    with tempfile.TemporaryDirectory(prefix="openhac_prod_pcb_") as td:
        out = Path(td) / "out"
        out.mkdir()
        cmd = [
            sys.executable,
            "-m",
            "openhac.cli",
            "compile",
            str(_GOLDEN),
            "--name",
            "prod_pcb",
            "--production",
            "--compile-goal",
            "fabrication",
            "--strict-footprint-pads",
            "--require-verified-parts",
            "--no-schematic",
            "-o",
            str(out),
        ]
        if not do_route:
            cmd.append("--no-route")
            print("Place-only path (--no-route); PCB DRC deferred", flush=True)
        else:
            print(f"Routed fabrication path via {jar}", flush=True)

        rc = _run(cmd, env=env)
        if rc != 0:
            print("FAIL: production PCB compile", file=sys.stderr)
            return False

        pcb = out / "prod_pcb.kicad_pcb"
        if not pcb.is_file():
            print("FAIL: missing .kicad_pcb", file=sys.stderr)
            return False
        if not _assert_fab_audit(out / "prod_pcb.openhac-manifest.json"):
            return False

        from openhac.compiler.pcb_metrics import compute_pcb_metrics

        m = compute_pcb_metrics(pcb)
        if not m:
            print("FAIL: empty pcb_metrics", file=sys.stderr)
            return False
        fc = int(m.get("footprint_count") or 0)
        if fc < 2:
            print(f"FAIL: footprint_count={fc} expected >= 2", file=sys.stderr)
            return False
        print(f"OK: V5 place footprint_count={fc}")

        if do_route:
            ur = int(m.get("unrouted_net_count") or 0)
            tc = int(m.get("track_count") or 0)
            if ur > 0:
                print(f"FAIL: FAB-021 unrouted_net_count={ur}", file=sys.stderr)
                return False
            if tc < 1:
                print(f"FAIL: track_count={tc} after route", file=sys.stderr)
                return False
            print(f"OK: V6 routing metrics track_count={tc} unrouted=0")

            drc_out = out / "prod_pcb.kicad_pcb.drc.txt"
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
                if drc_out.is_file():
                    print(drc_out.read_text(encoding="utf-8", errors="replace")[:4000], file=sys.stderr)
                print("FAIL: V6 KiCad PCB DRC", file=sys.stderr)
                return False
            print("OK: V6 KiCad PCB DRC clean")

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
            print("FAIL: V7 Gerber export", file=sys.stderr)
            return False
        fab_zip = out / "fab.zip"
        if not fab_zip.is_file() and not any(fab_out.glob("*")):
            print("FAIL: V7 no fab outputs", file=sys.stderr)
            return False
        print("OK: V7 Gerber / drill / pos export")
    return True


def stage_gld001_spice_island() -> bool:
    """GLD-001: bundled Apache physics on the SPICE-island golden. Not --require-all."""
    script = _REPO / "examples" / "spice_island_golden.py"
    overlay = _REPO / "openhac" / "database" / "spice_model_overlays" / "bundled_openhac.json"
    if not script.is_file():
        print("FAIL: GLD-001 missing examples/spice_island_golden.py", file=sys.stderr)
        return False
    text = script.read_text(encoding="utf-8")
    for token in ("D_1N4007", "OPTO_PC817", "AD620"):
        if token not in text:
            print(f"FAIL: GLD-001 golden missing {token}", file=sys.stderr)
            return False
    if "fundi_mig" in text.lower():
        print("FAIL: GLD-001 golden must not be Fundi MIG", file=sys.stderr)
        return False
    names = {m.get("generic_name") for m in json.loads(overlay.read_text(encoding="utf-8")).get("models") or []}
    if not {"D_1N4007", "OPTO_PC817", "AD620"} <= names:
        print("FAIL: GLD-001 bundled overlay missing physics decks", file=sys.stderr)
        return False
    print("OK: GLD-001 spice-island golden uses bundled Apache physics (not --require-all)")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--logic-only",
        action="store_true",
        help="V0–V3 only (no pcbnew / kicad schematic ERC / Gerbers)",
    )
    ap.add_argument(
        "--require-all",
        action="store_true",
        help="Full claim on the 2R golden only (FAB-051): V0–V7 including FreeRouting + PCB DRC",
    )
    ap.add_argument(
        "--require-layout",
        action="store_true",
        help="Fail if pcbnew unavailable (place/Gerber stages)",
    )
    ap.add_argument(
        "--require-route",
        action="store_true",
        help="Require FreeRouting + PCB DRC (implied by --require-all)",
    )
    ap.add_argument(
        "--skip-schematic-erc",
        action="store_true",
        help="Skip V4 KiCad schematic ERC",
    )
    ap.add_argument(
        "--fetch-freerouting",
        action="store_true",
        help=f"Download pinned FreeRouting {_FREEROUTING_VERSION} jar into ~/.cache/openhac/",
    )
    ap.add_argument(
        "--spice-island-golden",
        action="store_true",
        help="GLD-001: check examples/spice_island_golden.py uses bundled Apache physics. "
        "Not implied by --require-all (FAB-051 remains 2R).",
    )
    args = ap.parse_args()

    require_all = bool(args.require_all)
    require_route = bool(args.require_route) or require_all
    require_layout = bool(args.require_layout) or require_all or require_route
    logic_only = bool(args.logic_only) and not require_all

    jar: Path | None = _freerouting_jar()
    if args.fetch_freerouting or (require_route and jar is None):
        if args.fetch_freerouting or require_all:
            try:
                jar = fetch_freerouting()
                os.environ["FREEROUTING_JAR"] = str(jar)
            except Exception as e:
                print(f"FAIL: FreeRouting fetch: {e}", file=sys.stderr)
                if require_route:
                    return 1

    ok = True
    if not stage_v0_unit_gates():
        ok = False
    if not stage_v1_v2_native_erc_drc():
        ok = False
    if not stage_v3_negatives(require_layout=require_layout and not logic_only):
        ok = False

    if getattr(args, "spice_island_golden", False):
        if not stage_gld001_spice_island():
            ok = False

    if not logic_only:
        if not args.skip_schematic_erc:
            if not stage_v4_schematic_erc():
                ok = False
        if require_layout or _pcbnew_ok():
            if not stage_v5_v6_v7_pcb(require_route=require_route, jar=jar):
                ok = False
        elif require_layout:
            print("FAIL: pcbnew required", file=sys.stderr)
            ok = False

    if ok:
        if require_all:
            print(
                "\nPRODUCTION VALIDATION PASSED "
                "(software fabrication-ready for the 2×0805 resistor golden only)."
            )
        else:
            print("\nProduction validation checks passed (requested subset).")
        return 0
    print("\nPRODUCTION VALIDATION FAILED.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
