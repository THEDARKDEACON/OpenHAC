"""
OpenHaC CLI — compile declarative hardware Python into KiCad projects.

Usage:
    openhac compile board.py                     # compile to KiCad project
    openhac compile board.py --no-route        # skip autorouter
    openhac compile board.py --name my_board     # custom project name
    openhac compile board.py --allow-risky-parts # allow low-confidence JIT parts
    openhac compile board.py --kicad-erc        # run kicad-cli sch erc after .kicad_sch
    openhac compile board.py --strict-kicad     # no synthetic parts if libs missing
    openhac compile board.py -o dist/build      # artifacts + manifest under dist/build (MFG-005)
    openhac simulate board.py                    # generate SPICE netlist
    openhac simulate board.py --spice-analysis-json analysis.json  # SIM-002 JSON analysis bundle
    openhac sync                                 # sync JLCPCB catalog
    openhac seed                                 # seed database with samples
    openhac export fab board.kicad_pcb -o gerbers/ [--zip] [--ipc2581]
    openhac compile board.py --strict-jit   # block medium-confidence JIT (LIB-003)
    openhac compile board.py --production  # strict KiCad + strict JIT (LIB-004)
    openhac compile board.py --strict       # same as --production (LIB-003 umbrella)
    openhac compile board.py -o out/ --zip-release --release-tag v1.0.0
    openhac export assembly board.kicad_pcb -o pos/

When using ``openhac compile`` or ``openhac simulate``, define a top-level variable
named ``board`` (an :class:`openhac.core.board.Board` instance). Do not call
``board.compile()`` at import time — use ``if __name__ == "__main__":`` for direct
``python board.py`` runs, or rely on the CLI to invoke ``compile()``/``simulate()``.

Environment (optional):

- ``OPENHAC_DB_PATH`` — SQLite catalog path (default: ``openhac/database/openhac.db`` under the install).
- ``OPENHAC_SKIP_LAYOUT`` — if ``1``/``true``/``yes``, ``compile`` skips ``pcbnew`` layout and autoroute
  (netlist + BOM + manifest only; for headless CI / SW-006).
- ``OPENHAC_MANIFEST_SHA256_SIDECAR`` — if set, write ``*.openhac-manifest.json.sha256`` (STR-002 / MFG-005).
"""

from __future__ import annotations

import argparse
import importlib.util
import logging
import os
import sys
import shutil
import json

# Pre-import skidl to avoid logger initialization conflicts
try:
    import skidl  # noqa: F401
except ImportError:
    pass

logger = logging.getLogger("openhac")


def _load_user_script(script_path: str):
    """Import a user's hardware description script by path."""
    if not os.path.isfile(script_path):
        logger.error(f"File not found: {script_path}")
        sys.exit(1)

    spec = importlib.util.spec_from_file_location("__user_board__", script_path)
    if spec is None or spec.loader is None:
        logger.error(f"Cannot load: {script_path}")
        sys.exit(1)

    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as e:
        logger.error(f"Error executing {script_path}: {e}")
        raise
    return module


def _find_board_instance(user_module):
    """Return the Board instance exported by a user script (prefers the name ``board``)."""
    from openhac.core.board import Board

    preferred = getattr(user_module, "board", None)
    if isinstance(preferred, Board):
        return preferred

    found: list[tuple[str, object]] = []
    for name in dir(user_module):
        if name.startswith("_"):
            continue
        try:
            val = getattr(user_module, name)
        except Exception:
            continue
        if isinstance(val, Board):
            found.append((name, val))
    if not found:
        return None
    if len(found) > 1:
        logger.warning(
            "Multiple Board instances found (%s); using %r",
            [n for n, _ in found],
            found[0][0],
        )
    return found[0][1]


def _default_project_name(script_path: str) -> str:
    return os.path.splitext(os.path.basename(script_path))[0]


def cmd_compile(args):
    """Compile a hardware description to KiCad output."""
    from pathlib import Path

    from openhac.core.base import Component

    _prev_req_sym = Component.require_kicad_symbols
    _prev_sjit_comp = Component.strict_jit_lookups
    _prev_strict_jit = os.environ.get("OPENHAC_STRICT_JIT")
    _prev_strict_kicad_env = os.environ.get("OPENHAC_STRICT_KICAD")
    _prev_manifest_sha = os.environ.get("OPENHAC_MANIFEST_SHA256_SIDECAR")
    _prev_deterministic = os.environ.get("OPENHAC_DETERMINISTIC")
    _prev_req_verified = os.environ.get("OPENHAC_REQUIRE_VERIFIED_PARTS")
    _prev_skip_layout = os.environ.get("OPENHAC_SKIP_LAYOUT")
    _prev_db_path = os.environ.get("OPENHAC_DB_PATH")
    _prev_kicad_sym = os.environ.get("KICAD8_SYMBOL_DIR")
    _prev_kicad_fp = os.environ.get("KICAD8_FOOTPRINT_DIR")

    Component.allow_risky_part_lookups = bool(getattr(args, "allow_risky_parts", False))
    Component.require_kicad_symbols = bool(getattr(args, "strict_kicad", False))

    if getattr(args, "production", False) or getattr(args, "strict", False):
        os.environ["OPENHAC_STRICT_KICAD"] = "1"
        os.environ["OPENHAC_STRICT_JIT"] = "1"
        os.environ["OPENHAC_REQUIRE_VERIFIED_PARTS"] = "1"
        Component.require_kicad_symbols = True
        Component.strict_jit_lookups = True
    elif getattr(args, "strict_jit", False):
        os.environ["OPENHAC_STRICT_JIT"] = "1"

    if getattr(args, "manifest_sha256_sidecar", False):
        os.environ["OPENHAC_MANIFEST_SHA256_SIDECAR"] = "1"

    if getattr(args, "deterministic", False):
        os.environ["OPENHAC_DETERMINISTIC"] = "1"

    if getattr(args, "skip_layout", False):
        os.environ["OPENHAC_SKIP_LAYOUT"] = "1"

    if getattr(args, "require_verified_parts", False):
        os.environ["OPENHAC_REQUIRE_VERIFIED_PARTS"] = "1"

    if getattr(args, "db_path", None):
        os.environ["OPENHAC_DB_PATH"] = str(getattr(args, "db_path"))
    if getattr(args, "kicad_symbol_dir", None):
        os.environ["KICAD8_SYMBOL_DIR"] = str(getattr(args, "kicad_symbol_dir"))
    if getattr(args, "kicad_footprint_dir", None):
        os.environ["KICAD8_FOOTPRINT_DIR"] = str(getattr(args, "kicad_footprint_dir"))

    try:
        logger.info("Compiling: %s", args.script)
        user_module = _load_user_script(args.script)
        board = _find_board_instance(user_module)
        if board is None:
            logger.error(
                "No openhac.core.board.Board instance found. Assign your design to a variable "
                "named `board`, or expose exactly one Board at module level."
            )
            sys.exit(2)

        name = args.name or _default_project_name(args.script)
        export_schematic = not args.no_schematic
        kicad_erc = bool(getattr(args, "kicad_erc", False))
        if kicad_erc and not export_schematic:
            logger.error("--kicad-erc requires a schematic export (omit --no-schematic).")
            sys.exit(2)

        rt = getattr(args, "release_tag", None)
        if rt:
            board.release_tag = rt
        bp = getattr(args, "build_profile", None)
        if bp:
            board.build_profile = bp
        bmp = getattr(args, "bom_profile", None)
        if bmp:
            board.bom_profile = bmp

        if getattr(args, "strict_kicad", False):
            board.strict_kicad = True
        if getattr(args, "production", False) or getattr(args, "strict", False):
            board.strict_kicad = True
            board.strict_jit_lookups = True
        elif getattr(args, "strict_jit", False):
            board.strict_jit_lookups = True

        erc_fmt = "json" if getattr(args, "kicad_erc_json", False) else "report"

        zip_path = None
        if getattr(args, "zip_release", False):
            od = getattr(args, "output_dir", None)
            zrp = getattr(args, "zip_release_path", None)
            if zrp:
                zip_path = zrp
            elif od:
                zip_path = str(Path(od) / f"{name}-release.zip")
            else:
                zip_path = f"{name}-release.zip"

        board.compile(
            project_name=name,
            generate_bom=True,
            auto_route=not args.no_route,
            export_schematic=export_schematic,
            allow_risky_part_lookups=Component.allow_risky_part_lookups,
            kicad_sch_erc=kicad_erc,
            kicad_sch_erc_format=erc_fmt,
            source_script_path=os.path.abspath(args.script),
            output_dir=getattr(args, "output_dir", None),
            release_zip_path=zip_path,
        )
        logger.info("Compilation complete.")
    finally:
        if _prev_skip_layout is None:
            os.environ.pop("OPENHAC_SKIP_LAYOUT", None)
        else:
            os.environ["OPENHAC_SKIP_LAYOUT"] = _prev_skip_layout
        if _prev_deterministic is None:
            os.environ.pop("OPENHAC_DETERMINISTIC", None)
        else:
            os.environ["OPENHAC_DETERMINISTIC"] = _prev_deterministic
        if _prev_req_verified is None:
            os.environ.pop("OPENHAC_REQUIRE_VERIFIED_PARTS", None)
        else:
            os.environ["OPENHAC_REQUIRE_VERIFIED_PARTS"] = _prev_req_verified
        if _prev_db_path is None:
            os.environ.pop("OPENHAC_DB_PATH", None)
        else:
            os.environ["OPENHAC_DB_PATH"] = _prev_db_path
        if _prev_kicad_sym is None:
            os.environ.pop("KICAD8_SYMBOL_DIR", None)
        else:
            os.environ["KICAD8_SYMBOL_DIR"] = _prev_kicad_sym
        if _prev_kicad_fp is None:
            os.environ.pop("KICAD8_FOOTPRINT_DIR", None)
        else:
            os.environ["KICAD8_FOOTPRINT_DIR"] = _prev_kicad_fp
        if _prev_strict_jit is None:
            os.environ.pop("OPENHAC_STRICT_JIT", None)
        else:
            os.environ["OPENHAC_STRICT_JIT"] = _prev_strict_jit
        if _prev_strict_kicad_env is None:
            os.environ.pop("OPENHAC_STRICT_KICAD", None)
        else:
            os.environ["OPENHAC_STRICT_KICAD"] = _prev_strict_kicad_env
        if _prev_manifest_sha is None:
            os.environ.pop("OPENHAC_MANIFEST_SHA256_SIDECAR", None)
        else:
            os.environ["OPENHAC_MANIFEST_SHA256_SIDECAR"] = _prev_manifest_sha
        Component.require_kicad_symbols = _prev_req_sym
        Component.strict_jit_lookups = _prev_sjit_comp


def cmd_simulate(args):
    """Generate SPICE netlist from a hardware description."""
    import json

    from openhac.core.base import Component

    _prev_deterministic = os.environ.get("OPENHAC_DETERMINISTIC")
    _prev_db_path = os.environ.get("OPENHAC_DB_PATH")
    _prev_kicad_sym = os.environ.get("KICAD8_SYMBOL_DIR")
    _prev_kicad_fp = os.environ.get("KICAD8_FOOTPRINT_DIR")
    Component.allow_risky_part_lookups = bool(getattr(args, "allow_risky_parts", False))
    if getattr(args, "deterministic", False):
        os.environ["OPENHAC_DETERMINISTIC"] = "1"
    if getattr(args, "db_path", None):
        os.environ["OPENHAC_DB_PATH"] = str(getattr(args, "db_path"))
    if getattr(args, "kicad_symbol_dir", None):
        os.environ["KICAD8_SYMBOL_DIR"] = str(getattr(args, "kicad_symbol_dir"))
    if getattr(args, "kicad_footprint_dir", None):
        os.environ["KICAD8_FOOTPRINT_DIR"] = str(getattr(args, "kicad_footprint_dir"))
    logger.info("Simulating: %s", args.script)
    user_module = _load_user_script(args.script)
    board = _find_board_instance(user_module)
    if board is None:
        logger.error(
            "No Board instance found. Assign your design to `board` for `openhac simulate`."
        )
        sys.exit(2)

    name = args.name or _default_project_name(args.script)
    sl = getattr(args, "spice_lines", None)
    preset = getattr(args, "spice_preset", None)
    jpath = getattr(args, "spice_analysis_json", None)
    analysis_lines = list(sl) if sl else None
    if analysis_lines is None and jpath:
        from pathlib import Path

        from openhac.compiler.spice_analysis_config import (
            load_spice_analysis_raw,
            resolve_spice_analysis_from_mapping,
        )

        try:
            raw = load_spice_analysis_raw(Path(jpath))
            al2, preset_from_file = resolve_spice_analysis_from_mapping(raw)
        except (OSError, ValueError, ImportError, json.JSONDecodeError) as e:
            logger.error("Could not read spice analysis file %s: %s", jpath, e)
            sys.exit(2)
        if al2 is not None:
            analysis_lines = al2
        else:
            from openhac.compiler.spice_presets import preset_analysis_lines

            try:
                analysis_lines = preset_analysis_lines(preset_from_file)  # type: ignore[arg-type]
            except ValueError as e:
                logger.error("%s", e)
                sys.exit(2)
    if analysis_lines is None and preset:
        from openhac.compiler.spice_presets import preset_analysis_lines

        analysis_lines = preset_analysis_lines(preset)
    board.simulate(
        project_name=name,
        allow_risky_part_lookups=Component.allow_risky_part_lookups,
        spice_analysis_lines=analysis_lines,
        output_dir=getattr(args, "output_dir", None),
    )
    logger.info("Simulation complete.")
    if _prev_deterministic is None:
        os.environ.pop("OPENHAC_DETERMINISTIC", None)
    else:
        os.environ["OPENHAC_DETERMINISTIC"] = _prev_deterministic
    if _prev_db_path is None:
        os.environ.pop("OPENHAC_DB_PATH", None)
    else:
        os.environ["OPENHAC_DB_PATH"] = _prev_db_path
    if _prev_kicad_sym is None:
        os.environ.pop("KICAD8_SYMBOL_DIR", None)
    else:
        os.environ["KICAD8_SYMBOL_DIR"] = _prev_kicad_sym
    if _prev_kicad_fp is None:
        os.environ.pop("KICAD8_FOOTPRINT_DIR", None)
    else:
        os.environ["KICAD8_FOOTPRINT_DIR"] = _prev_kicad_fp


def cmd_doctor(args):
    """Print a toolchain readiness report."""
    from openhac.compiler.kicad_sym_pinpos import symbol_library_search_paths
    from openhac.compiler.pcb_placement import footprint_search_roots

    _prev_db_path = os.environ.get("OPENHAC_DB_PATH")
    if getattr(args, "db_path", None):
        os.environ["OPENHAC_DB_PATH"] = str(getattr(args, "db_path"))

    kicad_cli = shutil.which("kicad-cli")
    kicad_cli_version = None
    kicad_cli_ok = None
    if kicad_cli:
        try:
            import subprocess

            cp = subprocess.run([kicad_cli, "--version"], capture_output=True, text=True)
            kicad_cli_ok = bool(cp.returncode == 0)
            out = (cp.stdout or cp.stderr or "").strip()
            kicad_cli_version = out.splitlines()[0].strip() if out else None
        except Exception:
            kicad_cli_ok = False

    pcbnew = shutil.which("pcbnew")
    java = shutil.which("java")
    freerouting_jar = os.environ.get("FREEROUTING_JAR")
    freerouting_jar_exists = bool((freerouting_jar or "").strip() and os.path.isfile(freerouting_jar or ""))

    cwd = os.getcwd()
    fp_lib_table_local = os.path.join(cwd, "fp-lib-table")
    sym_lib_table_local = os.path.join(cwd, "sym-lib-table")
    kicad_cfg_candidates = [
        os.path.expanduser(p)
        for p in (
            "~/.config/kicad/9.0",
            "~/.config/kicad/8.0",
            "~/.config/kicad/7.0",
            "~/.config/kicad/6.0",
            "~/.config/kicad",
        )
    ]
    fp_lib_table_candidates = sorted(
        dict.fromkeys(
            [fp_lib_table_local] + [os.path.join(d, "fp-lib-table") for d in kicad_cfg_candidates]
        )
    )
    sym_lib_table_candidates = sorted(
        dict.fromkeys(
            [sym_lib_table_local] + [os.path.join(d, "sym-lib-table") for d in kicad_cfg_candidates]
        )
    )

    report = {
        "python_executable": sys.executable,
        "kicad_cli_path": kicad_cli,
        "kicad_cli_ok": kicad_cli_ok,
        "kicad_cli_version": kicad_cli_version,
        "pcbnew_path": pcbnew,
        "pcbnew_present": bool(pcbnew),
        "java_path": java,
        "java_present": bool(java),
        "freerouting_jar": freerouting_jar,
        "freerouting_jar_exists": freerouting_jar_exists,
        "fp_lib_table_present": any(os.path.isfile(p) for p in fp_lib_table_candidates),
        "sym_lib_table_present": any(os.path.isfile(p) for p in sym_lib_table_candidates),
        "fp_lib_table_candidates": fp_lib_table_candidates,
        "sym_lib_table_candidates": sym_lib_table_candidates,
        "kicad_symbol_search_paths": [str(p) for p in symbol_library_search_paths()],
        "kicad_footprint_search_paths": list(footprint_search_roots()),
        "openhac_db_path": os.environ.get("OPENHAC_DB_PATH"),
        "openhac_deterministic": os.environ.get("OPENHAC_DETERMINISTIC"),
        "openhac_allow_risky_parts": os.environ.get("OPENHAC_ALLOW_RISKY_PARTS"),
        "openhac_require_verified_parts": os.environ.get("OPENHAC_REQUIRE_VERIFIED_PARTS"),
    }
    missing = []

    if getattr(args, "print_env", False):
        sym_pick = next((p for p in report["kicad_symbol_search_paths"] if os.path.isdir(p)), None)
        fp_pick = next((p for p in report["kicad_footprint_search_paths"] if os.path.isdir(p)), None)
        if sym_pick:
            print(f'export KICAD8_SYMBOL_DIR="{sym_pick}"')
        if fp_pick:
            print(f'export KICAD8_FOOTPRINT_DIR="{fp_pick}"')
        if report.get("openhac_db_path"):
            print(f'export OPENHAC_DB_PATH="{report.get("openhac_db_path")}"')

    strict_headless = bool(getattr(args, "strict_headless", False))
    strict_layout = bool(getattr(args, "strict_layout", False))
    strict_any = bool(getattr(args, "strict", False) or strict_headless or strict_layout)
    if strict_any:
        strict_default = bool(getattr(args, "strict", False))

        sym_env_configured = any(
            (os.environ.get(k) or "").strip()
            for k in (
                "OPENHAC_KICAD_SYMBOL_DIRS",
                "KICAD9_SYMBOL_DIR",
                "KICAD8_SYMBOL_DIR",
                "KICAD7_SYMBOL_DIR",
                "KICAD6_SYMBOL_DIR",
                "KICAD_SYMBOL_DIR",
            )
        )
        fp_env_configured = any(
            (os.environ.get(k) or "").strip()
            for k in ("KICAD9_FOOTPRINT_DIR", "KICAD8_FOOTPRINT_DIR", "KICAD_FOOTPRINT_DIR")
        )

        # Headless: KiCad CLI is the key dependency (ERC/export).
        if (strict_default or strict_headless) and not kicad_cli:
            missing.append("kicad-cli")

        # Layout: pcbnew is required.
        if (strict_default or strict_layout) and not pcbnew:
            missing.append("pcbnew")

        # If we're asking for strictness and there's no obvious KiCad library table or env config,
        # make it explicit to reduce "it runs but can't find libraries" confusion.
        if (strict_default or strict_headless) and (not report["sym_lib_table_present"]) and (not sym_env_configured):
            missing.append("sym-lib-table-or-KICAD*_SYMBOL_DIR")
        if (strict_default or strict_layout) and (not report["fp_lib_table_present"]) and (not fp_env_configured):
            missing.append("fp-lib-table-or-KICAD*_FOOTPRINT_DIR")

        if (freerouting_jar or "").strip():
            if not java:
                missing.append("java")
            if not freerouting_jar_exists:
                missing.append("freerouting_jar_exists")

    if strict_any and missing:
        if getattr(args, "as_json", False):
            report["ok"] = False
            report["missing"] = missing
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            for k, v in report.items():
                print(f"{k}: {v}")
            print(f"missing: {missing}")
        if _prev_db_path is None:
            os.environ.pop("OPENHAC_DB_PATH", None)
        else:
            os.environ["OPENHAC_DB_PATH"] = _prev_db_path
        raise SystemExit(2)
    if getattr(args, "as_json", False):
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        for k, v in report.items():
            print(f"{k}: {v}")
    if _prev_db_path is None:
        os.environ.pop("OPENHAC_DB_PATH", None)
    else:
        os.environ["OPENHAC_DB_PATH"] = _prev_db_path


def cmd_sync(args):
    """Sync JLCPCB component catalog to local database."""
    from openhac.database.sync_jlc import sync_catalog

    _prev_db_path = os.environ.get("OPENHAC_DB_PATH")
    if getattr(args, "db_path", None):
        os.environ["OPENHAC_DB_PATH"] = str(getattr(args, "db_path"))

    categories = args.categories.split(",") if args.categories else None
    verbose = not args.quiet
    logger.info("Syncing JLCPCB catalog...")
    count = sync_catalog(categories=categories, verbose=verbose)
    logger.info("Synced %s components.", count)
    if _prev_db_path is None:
        os.environ.pop("OPENHAC_DB_PATH", None)
    else:
        os.environ["OPENHAC_DB_PATH"] = _prev_db_path


def cmd_seed(args):
    """Seed the database with sample components."""
    from openhac.database.seed_data import seed_database

    _prev_db_path = os.environ.get("OPENHAC_DB_PATH")
    if getattr(args, "db_path", None):
        os.environ["OPENHAC_DB_PATH"] = str(getattr(args, "db_path"))

    logger.info("Seeding database...")
    seed_database()
    logger.info("Seeding complete.")
    if _prev_db_path is None:
        os.environ.pop("OPENHAC_DB_PATH", None)
    else:
        os.environ["OPENHAC_DB_PATH"] = _prev_db_path


def cmd_export_assembly(args):
    """Pick-and-place CSV only (front + back) via ``kicad-cli`` (MFG-002)."""
    from openhac.compiler.export_fab import export_assembly_csv

    logger.info("Exporting assembly (pos CSV) → %s", args.output)
    export_assembly_csv(args.pcb, args.output)
    logger.info("Assembly export complete.")


def cmd_export_fab(args):
    """Gerbers + Excellon drill + CSV position files via ``kicad-cli``."""
    from openhac.compiler.export_fab import export_fabrication_bundle

    logger.info("Exporting fabrication bundle → %s", args.output)
    zip_path = None
    if getattr(args, "zip", False):
        from pathlib import Path

        zip_path = args.zip_file or str(Path(args.output).with_suffix(".zip"))

    export_fabrication_bundle(
        args.pcb,
        args.output,
        include_pos=not args.no_pos,
        include_ipc2581=bool(getattr(args, "ipc2581", False)),
        gerber_use_board_settings=args.board_plot_params,
        zip_path=zip_path,
    )
    logger.info("Fabrication export complete.")


def _setup_logging(verbose: bool = False):
    """Configure structured logging for the OpenHaC toolchain."""
    level = logging.DEBUG if verbose else logging.INFO
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    logging.basicConfig(level=level, format=fmt, datefmt="%H:%M:%S")
    if not verbose:
        logging.getLogger("skidl").setLevel(logging.WARNING)


def main():
    from openhac.version_info import get_version

    parser = argparse.ArgumentParser(
        prog="openhac",
        description="OpenHaC — compile declarative Python into manufacturable PCB designs",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {get_version()}",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug output")
    parser.add_argument(
        "--db-path",
        default=None,
        metavar="PATH",
        help="SQLite catalog path override (sets OPENHAC_DB_PATH for this run)",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    p_compile = subparsers.add_parser("compile", help="Compile hardware to KiCad project")
    p_compile.add_argument("script", help="Path to the hardware description .py file")
    p_compile.add_argument("--name", default=None, help="Project name (default: script basename)")
    p_compile.add_argument("--no-route", action="store_true", help="Skip auto-routing")
    p_compile.add_argument(
        "--skip-layout",
        action="store_true",
        help="Skip pcbnew layout generation and autoroute (sets OPENHAC_SKIP_LAYOUT=1 for the run)",
    )
    p_compile.add_argument(
        "--kicad-symbol-dir",
        default=None,
        metavar="DIR",
        help="Override KiCad symbol library root for this run (sets KICAD8_SYMBOL_DIR)",
    )
    p_compile.add_argument(
        "--kicad-footprint-dir",
        default=None,
        metavar="DIR",
        help="Override KiCad footprint library root for this run (sets KICAD8_FOOTPRINT_DIR)",
    )
    p_compile.add_argument(
        "--no-schematic",
        action="store_true",
        help="Skip schematic and .kicad_pro export",
    )
    p_compile.add_argument(
        "--allow-risky-parts",
        action="store_true",
        help="Allow low-confidence live/JIT KiCad symbol/footprint guesses (may be wrong)",
    )
    p_compile.add_argument(
        "--kicad-erc",
        action="store_true",
        help="After exporting the schematic, run `kicad-cli sch erc` (requires KiCad CLI)",
    )
    p_compile.add_argument(
        "--strict-kicad",
        action="store_true",
        help="Fail if KiCad symbols cannot load (no synthetic parts; LIB-004)",
    )
    p_compile.add_argument(
        "--strict-jit",
        action="store_true",
        help="Treat medium-confidence JIT/live lookups as errors unless --allow-risky-parts (LIB-003)",
    )
    p_compile.add_argument(
        "--production",
        action="store_true",
        help="Strict KiCad symbols + strict JIT (LIB-004 / LIB-003); sets OPENHAC_STRICT_KICAD + OPENHAC_STRICT_JIT for the compile",
    )
    p_compile.add_argument(
        "--require-verified-parts",
        action="store_true",
        help="Fail DRC if any JIT/unverified parts (medium/low confidence) are present (sets OPENHAC_REQUIRE_VERIFIED_PARTS=1)",
    )
    p_compile.add_argument(
        "--strict",
        action="store_true",
        help="Alias for --production: strict KiCad + strict JIT (LIB-003 umbrella on CLI)",
    )
    p_compile.add_argument(
        "--release-tag",
        default=None,
        metavar="TAG",
        help="Record in manifest as release_tag (STR-002); overrides OPENHAC_RELEASE_TAG for this run",
    )
    p_compile.add_argument(
        "--build-profile",
        default=None,
        metavar="NAME",
        help="Record in manifest as build_profile (e.g. production); OPENHAC_BUILD_PROFILE also supported",
    )
    p_compile.add_argument(
        "--bom-profile",
        default=None,
        metavar="NAME",
        help="Record in manifest as bom_profile (e.g. dev, prod) for BOM tier labeling (LIB-004)",
    )
    p_compile.add_argument(
        "--kicad-erc-json",
        action="store_true",
        help="With --kicad-erc, write ERC report as JSON (SCH-003); requires KiCad CLI json format support",
    )
    p_compile.add_argument(
        "--zip-release",
        action="store_true",
        help="After compile, zip known outputs into a single .zip (MFG-005)",
    )
    p_compile.add_argument(
        "--zip-release-path",
        default=None,
        metavar="ZIP",
        help="Path for --zip-release (default: OUTPUT_DIR/NAME-release.zip or ./NAME-release.zip)",
    )
    p_compile.add_argument(
        "--deterministic",
        action="store_true",
        help="Enable byte-stable artifacts for this run (sets OPENHAC_DETERMINISTIC=1)",
    )
    p_compile.add_argument(
        "-o",
        "--output-dir",
        default=None,
        metavar="DIR",
        help="Write netlist, BOM, PCB, manifest, and optional sch under this directory (MFG-005)",
    )
    p_compile.add_argument(
        "--manifest-sha256-sidecar",
        action="store_true",
        help="Write PROJECT.openhac-manifest.json.sha256 (STR-002); same as env OPENHAC_MANIFEST_SHA256_SIDECAR=1",
    )
    p_compile.set_defaults(func=cmd_compile)

    p_sim = subparsers.add_parser("simulate", help="Generate SPICE netlist")
    p_sim.add_argument("script", help="Path to the hardware description .py file")
    p_sim.add_argument("--name", default=None, help="Output base name (default: script basename)")
    p_sim.add_argument(
        "--allow-risky-parts",
        action="store_true",
        help="Allow low-confidence live/JIT part mapping",
    )
    p_sim.add_argument(
        "-o",
        "--output-dir",
        default=None,
        metavar="DIR",
        help="Directory for the generated .cir file",
    )
    p_sim.add_argument(
        "--spice-line",
        action="append",
        dest="spice_lines",
        help="SPICE directive line (repeatable). If set, overrides --spice-analysis-json, --spice-preset, and default .tran (SIM-002)",
    )
    p_sim.add_argument(
        "--spice-analysis-json",
        metavar="FILE",
        default=None,
        help='JSON or YAML file with {"analysis_lines": [...]} or {"preset": "op"} — used if --spice-line not set (SIM-002)',
    )
    from openhac.compiler.spice_presets import PRESETS as _SPICE_PRESETS

    p_sim.add_argument(
        "--spice-preset",
        choices=sorted(_SPICE_PRESETS.keys()),
        default=None,
        help="Named analysis bundle when --spice-line is not used (SIM-002): "
        + ", ".join(sorted(_SPICE_PRESETS.keys())),
    )
    p_sim.add_argument(
        "--deterministic",
        action="store_true",
        help="Enable deterministic mode for this run (sets OPENHAC_DETERMINISTIC=1)",
    )
    p_sim.add_argument(
        "--kicad-symbol-dir",
        default=None,
        metavar="DIR",
        help="Override KiCad symbol library root for this run (sets KICAD8_SYMBOL_DIR)",
    )
    p_sim.add_argument(
        "--kicad-footprint-dir",
        default=None,
        metavar="DIR",
        help="Override KiCad footprint library root for this run (sets KICAD8_FOOTPRINT_DIR)",
    )
    p_sim.set_defaults(func=cmd_simulate)

    p_sync = subparsers.add_parser("sync", help="Sync JLCPCB component catalog")
    p_sync.add_argument("--categories", default=None, help="Comma-separated categories")
    p_sync.add_argument("-q", "--quiet", action="store_true", help="Suppress verbose output")
    p_sync.set_defaults(func=cmd_sync)

    p_seed = subparsers.add_parser("seed", help="Seed database with sample components")
    p_seed.set_defaults(func=cmd_seed)

    p_export = subparsers.add_parser("export", help="Export fabrication outputs (requires kicad-cli)")
    export_sub = p_export.add_subparsers(dest="export_target", required=True)
    p_asm = export_sub.add_parser(
        "assembly",
        help="Pick-and-place CSV (front + back) only — same kicad-cli pos export as fab (MFG-002)",
    )
    p_asm.add_argument("pcb", help="Path to .kicad_pcb")
    p_asm.add_argument(
        "-o",
        "--output",
        required=True,
        help="Output directory (created if missing)",
    )
    p_asm.set_defaults(func=cmd_export_assembly)

    p_fab = export_sub.add_parser(
        "fab",
        help="Gerbers, Excellon drill, and CSV pick-and-place files",
    )
    p_fab.add_argument("pcb", help="Path to .kicad_pcb")
    p_fab.add_argument(
        "-o",
        "--output",
        required=True,
        help="Output directory (created if missing)",
    )
    p_fab.add_argument(
        "--no-pos",
        action="store_true",
        help="Skip position (pick-and-place) CSV export",
    )
    p_fab.add_argument(
        "--ipc2581",
        action="store_true",
        help="Also export IPC-2581 via kicad-cli pcb export ipc2581 (MFG-001)",
    )
    p_fab.add_argument(
        "--board-plot-params",
        action="store_true",
        help="Use Gerber plot settings stored in the board file",
    )
    p_fab.add_argument(
        "--zip",
        action="store_true",
        help="Also write a .zip of the output directory (default path: OUTPUT.zip)",
    )
    p_fab.add_argument(
        "--zip-file",
        default=None,
        metavar="PATH",
        help="Zip file path (overrides default when using --zip)",
    )
    p_fab.set_defaults(func=cmd_export_fab)

    p_doc = subparsers.add_parser("doctor", help="Check toolchain availability and configured paths")
    p_doc.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="Emit machine-readable JSON",
    )
    p_doc.add_argument(
        "--strict",
        action="store_true",
        help="Exit nonzero when required tools are missing",
    )
    p_doc.add_argument(
        "--print-env",
        action="store_true",
        help="Print best-effort `export ...` lines for a typical KiCad install (no side effects)",
    )
    p_doc.add_argument(
        "--strict-headless",
        action="store_true",
        help="Exit nonzero if headless-required tools are missing (kicad-cli)",
    )
    p_doc.add_argument(
        "--strict-layout",
        action="store_true",
        help="Exit nonzero if layout-required tools are missing (pcbnew)",
    )
    p_doc.set_defaults(func=cmd_doctor)

    args = parser.parse_args()
    _setup_logging(verbose=args.verbose)

    _prev_db_path = os.environ.get("OPENHAC_DB_PATH")
    if getattr(args, "db_path", None):
        os.environ["OPENHAC_DB_PATH"] = str(args.db_path)

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    try:
        args.func(args)
    finally:
        if getattr(args, "db_path", None):
            if _prev_db_path is None:
                os.environ.pop("OPENHAC_DB_PATH", None)
            else:
                os.environ["OPENHAC_DB_PATH"] = _prev_db_path


if __name__ == "__main__":
    main()
