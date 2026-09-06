"""
OpenHaC CLI — compile declarative hardware Python into KiCad projects.

Usage:
    openhac compile board.py                     # compile to KiCad project
    openhac compile board.py --freerouting-gui  # FreeRouting Java window (default is headless)
    openhac compile board.py --name my_board     # custom project name
    openhac compile board.py --allow-risky-parts # allow low-confidence JIT parts
    openhac compile board.py --kicad-erc        # run kicad-cli sch erc after .kicad_sch
    openhac compile board.py --strict-kicad     # no synthetic parts if libs missing
    openhac compile board.py -o dist/build      # artifacts + manifest under dist/build (MFG-005)
    openhac compile board.py --schematic-signoff --spice-signoff  # SSO + SPS after compile
    openhac simulate board.py                    # generate SPICE netlist
    openhac simulate board.py --spice-signoff    # fail-closed analog gate (also on compile)
    openhac simulate board.py --spice-analysis-json analysis.json  # SIM-002 JSON analysis bundle
    openhac sync                                 # sync JLCPCB catalog
    openhac seed                                 # seed database with samples
    openhac export fab board.kicad_pcb -o gerbers/ [--zip] [--ipc2581]
    openhac compile board.py --strict-jit   # block medium-confidence JIT (LIB-003)
    openhac compile board.py --production   # strict KiCad + strict JIT (same: --strict)
    openhac compile board.py -o out/ --zip-release --release-tag v1.0.0
    openhac export dsn board.kicad_pcb          # re-export Specctra DSN with IPC widths (no re-place)

When using ``openhac compile`` or ``openhac simulate``, define a top-level variable
named ``board`` (an :class:`openhac.core.board.Board` instance). Do not call
``board.compile()`` at import time — use ``if __name__ == "__main__":`` for direct
``python board.py`` runs, or rely on the CLI to invoke ``compile()``/``simulate()``.

Environment (optional):

- ``OPENHAC_DB_PATH`` — SQLite catalog path (default: ``openhac/database/openhac.db`` under the install).
- ``OPENHAC_SKIP_LAYOUT`` — if ``1``/``true``/``yes``, ``compile`` skips ``pcbnew`` layout and autoroute
  (netlist + BOM + manifest only; for headless CI / SW-006).
- ``OPENHAC_MANIFEST_SHA256_SIDECAR`` — if set, write ``*.openhac-manifest.json.sha256`` (STR-002 / MFG-005).
- ``OPENHAC_COMPILE_GOAL`` — ``handoff`` (KiCad-openable handoff) or ``fabrication`` (stricter gates).
"""

from __future__ import annotations

import argparse
import importlib.util
import logging
import os
import sys
import shutil
import json

from openhac.core.dotenv_load import apply_kicad_env_aliases, load_repo_dotenv

# Repo .env + KiCad paths must load before component libraries.
load_repo_dotenv(quiet=True)
apply_kicad_env_aliases()

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
    _quiet_skidl_logging(verbose=False)
    return module


def _find_board_instance(user_module):
    """Return the Board instance exported by a user script (prefers the name ``board``)."""
    from openhac.core.board import Board

    preferred = getattr(user_module, "board", None)
    if isinstance(preferred, Board):
        return preferred

    # Support a lazy factory to avoid constructing large boards at import time.
    build = getattr(user_module, "build_board", None)
    if callable(build):
        try:
            candidate = build()
            if isinstance(candidate, Board):
                return candidate
        except Exception:
            # Fall through to other discovery; caller will show the real exception
            # when importing/constructing if needed.
            raise

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


def _preview_artifact(out_dir: str, name: str, suffix: str) -> str:
    p = os.path.join(out_dir, f"{name}{suffix}")
    if os.path.isfile(p):
        return p
    nested = os.path.join(out_dir, name, f"{name}{suffix}")
    return nested if os.path.isfile(nested) else p


def _preview_compile_once(args, *, name: str, out_dir: str, overlay_paths: list):
    """Write schematic (and SVG if kicad-cli exists). Return ``(sch, sch_svg, pcb_svg)``."""
    from pathlib import Path

    from openhac.compiler.kicad_sch_svg import export_schematic_svg
    from openhac.compiler.svg_preview import export_pcb_preview_svg
    from openhac.core.base import Component
    from openhac.core.exceptions import KiCadCliNotFoundError

    user_mod = _load_user_script(args.script)
    board = _find_board_instance(user_mod)
    if board is None:
        raise RuntimeError(f"No Board instance named 'board' (or build_board()) in {args.script}")
    board.compile(
        project_name=name,
        generate_bom=False,
        auto_route=False,
        export_schematic=True,
        allow_risky_part_lookups=Component.allow_risky_part_lookups,
        kicad_sch_erc=False,
        source_script_path=os.path.abspath(args.script),
        output_dir=out_dir,
        catalog_overlay_paths=tuple(overlay_paths) if overlay_paths else (),
        schematic_signoff=False,
        compile_profile="preview_pcb" if bool(getattr(args, "pcb", False)) else "preview",
    )
    sch = _preview_artifact(out_dir, name, ".kicad_sch")
    if not os.path.isfile(sch):
        raise FileNotFoundError(f"preview did not write a schematic at {sch}")
    live = getattr(board, "_live_kicad_artwork", None) or {}
    if live.get("merged"):
        print(
            "Merged last-saved KiCad overlay: "
            f"{live.get('symbol_uuid_count', 0)} symbol poses, "
            f"{live.get('footprint_count', 0)} footprints.",
            flush=True,
        )
    svg_dir = Path(out_dir) / "openhac-preview"
    sch_svg = None
    pcb_svg = None
    try:
        sch_svg = export_schematic_svg(sch, output_dir=svg_dir)
        print(f"Preview SVG: {sch_svg}", flush=True)
    except KiCadCliNotFoundError as e:
        logger.warning("%s (schematic is still at %s)", e, sch)
    except RuntimeError as e:
        logger.warning("%s", e)
    if sch_svg is not None and bool(getattr(args, "pcb", False)):
        pcb = _preview_artifact(out_dir, name, ".kicad_pcb")
        if os.path.isfile(pcb):
            try:
                pcb_svg = export_pcb_preview_svg(pcb, svg_dir / "board.svg")
                print(f"Preview PCB SVG: {pcb_svg}", flush=True)
            except (KiCadCliNotFoundError, RuntimeError) as e:
                logger.warning("PCB SVG skipped: %s", e)
    return sch, sch_svg, pcb_svg


def cmd_preview(args):
    """SSO-012: generate schematic + KiCad SVG. Never runs ``kicad-cli sch erc``.

    ``--watch`` serves a localhost SVG viewer of that export (LIVE-008) and rebuilds
    on Python save. ``--kicad`` still opens eeschema for pose edits (Save, then Revert).
    Preview is not ERC-stamped. ``--pcb`` adds a place-only board (LIVE-007).
    """
    import time

    from openhac.compiler.kicad_live import (
        prefer_kicad_open_path,
        reset_preview_runtime,
        spawn_kicad,
        watch_debounce_s,
    )
    from openhac.compiler.svg_preview import (
        SvgPreviewServer,
        open_preview_browser,
        want_preview_browser,
    )

    name = getattr(args, "name", None) or _default_project_name(args.script)
    out_dir = getattr(args, "output_dir", None) or os.path.join(
        os.path.dirname(os.path.abspath(args.script)), name
    )
    os.makedirs(out_dir, exist_ok=True)
    overlay_paths = getattr(args, "catalog_overlay", None) or []
    want_pcb = bool(getattr(args, "pcb", False))
    print(
        "OpenHaC preview: KiCad schematic from library symbols. "
        "This is NOT ERC-stamped. Stamp remains: openhac compile --schematic-signoff",
        flush=True,
    )
    if want_pcb:
        print("LIVE-007: place-only PCB (no autoroute, no ERC).", flush=True)
    sch, sch_svg, pcb_svg = None, None, None
    try:
        sch, sch_svg, pcb_svg = _preview_compile_once(
            args, name=name, out_dir=out_dir, overlay_paths=overlay_paths
        )
    except (RuntimeError, FileNotFoundError) as e:
        logger.error("%s", e)
        sys.exit(1)
    if want_pcb:
        from openhac.compiler.kicad_live import try_pcb_revert_via_ipc

        pcb = _preview_artifact(out_dir, name, ".kicad_pcb")
        if os.path.isfile(pcb):
            ipc = try_pcb_revert_via_ipc(pcb)
            if ipc.get("reloaded"):
                print("LIVE-010: asked KiCad to revert/reload the PCB via IPC.", flush=True)
            elif ipc.get("attempted"):
                print(
                    f"LIVE-010: KiCad IPC present but PCB revert skipped ({ipc.get('reason')}). "
                    "File → Revert still works. Schematic IPC is KiCad 11 and is not faked.",
                    flush=True,
                )
    open_kicad = bool(getattr(args, "kicad", False))
    watch = bool(getattr(args, "watch", False))
    svg_ok = sch_svg is not None
    if not svg_ok and not open_kicad:
        sys.exit(2)
    if open_kicad:
        target = prefer_kicad_open_path(out_dir, name)
        proc = spawn_kicad(target)
        if proc is None:
            sys.exit(2)
        print(
            f"KiCad opened on {target}. Save in KiCad first (unsaved nudges never reach disk), "
            "then save the Python board script to merge. KiCad 9 usually will not prompt Reload "
            "while the sheet is open — File → Revert, or close and reopen the sheet.",
            flush=True,
        )
    viewer = None
    if watch and sch_svg is not None:
        viewer = SvgPreviewServer(title=name)
        viewer.update(sch_svg=sch_svg, pcb_svg=pcb_svg)
        url = viewer.start()
        print(
            f"SVG viewer: {url}  (KiCad's drawing of the .kicad_sch; refreshes on .py save). "
            "This is not an editor — nudge pose in KiCad, then Save there.",
            flush=True,
        )
        if want_preview_browser(no_browser=bool(getattr(args, "no_browser", False))):
            if not open_preview_browser(url):
                print(f"Open {url} in a browser.", flush=True)
        else:
            print("Browser launch skipped (--no-browser / OPENHAC_PREVIEW_NO_BROWSER).", flush=True)
    if not watch:
        return
    script = os.path.abspath(args.script)
    last = os.path.getmtime(script)
    debounce = watch_debounce_s(pcb=want_pcb)
    print(f"Watching {script} (debounce {debounce:.1f}s, Ctrl+C to stop)…", flush=True)
    try:
        while True:
            time.sleep(min(0.4, debounce))
            try:
                mtime = os.path.getmtime(script)
            except OSError:
                continue
            if mtime <= last:
                continue
            time.sleep(debounce)
            try:
                mtime2 = os.path.getmtime(script)
            except OSError:
                continue
            if mtime2 != mtime:
                continue
            last = mtime2
            print("Script changed; regenerating (merge last-saved KiCad artwork)…", flush=True)
            try:
                reset_preview_runtime()
                sch, sch_svg, pcb_svg = _preview_compile_once(
                    args, name=name, out_dir=out_dir, overlay_paths=overlay_paths
                )
                if want_pcb:
                    from openhac.compiler.kicad_live import try_pcb_revert_via_ipc

                    pcb = _preview_artifact(out_dir, name, ".kicad_pcb")
                    if os.path.isfile(pcb):
                        try_pcb_revert_via_ipc(pcb)
                if viewer is not None:
                    viewer.update(sch_svg=sch_svg or viewer.sch_svg, pcb_svg=pcb_svg or viewer.pcb_svg)
                print(
                    f"Wrote {sch}. SVG viewer refreshes on its own. "
                    "If KiCad is open: File → Revert, or close and reopen the sheet.",
                    flush=True,
                )
            except Exception as e:
                logger.error("Preview rebuild failed: %s", e)
    except KeyboardInterrupt:
        print("Preview watch stopped.", flush=True)
    finally:
        if viewer is not None:
            viewer.stop()


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
    _prev_compile_goal = os.environ.get("OPENHAC_COMPILE_GOAL")
    _prev_fr_gui = os.environ.get("OPENHAC_FREEROUTING_GUI")
    _prev_db_path = os.environ.get("OPENHAC_DB_PATH")
    _prev_symbol_dirs = os.environ.get("OPENHAC_KICAD_SYMBOL_DIRS")
    _prev_schematic_strict = os.environ.get("OPENHAC_SCHEMATIC_STRICT")
    _prev_no_network = os.environ.get("OPENHAC_NO_NETWORK")
    _prev_strict_fp_pad = os.environ.get("OPENHAC_STRICT_FOOTPRINT_PIN_PAD")
    _prev_spice_signoff = os.environ.get("OPENHAC_SPICE_SIGNOFF")
    _prev_spice_vendor = os.environ.get("OPENHAC_SPICE_VENDOR_DIR")
    _kicad_sym_keys = ("KICAD9_SYMBOL_DIR", "KICAD8_SYMBOL_DIR", "KICAD7_SYMBOL_DIR", "KICAD6_SYMBOL_DIR")
    _kicad_fp_keys = ("KICAD9_FOOTPRINT_DIR", "KICAD8_FOOTPRINT_DIR", "KICAD_FOOTPRINT_DIR")
    _prev_kicad_sym = {k: os.environ.get(k) for k in _kicad_sym_keys}
    _prev_kicad_fp = {k: os.environ.get(k) for k in _kicad_fp_keys}

    Component.allow_risky_part_lookups = bool(getattr(args, "allow_risky_parts", False))
    Component.require_kicad_symbols = bool(getattr(args, "strict_kicad", False))

    if getattr(args, "production", False):
        # FAB-030: --production implies the full fabrication gate set.
        os.environ["OPENHAC_STRICT_KICAD"] = "1"
        os.environ["OPENHAC_STRICT_JIT"] = "1"
        os.environ["OPENHAC_REQUIRE_VERIFIED_PARTS"] = "1"
        os.environ["OPENHAC_STRICT_FOOTPRINT_PIN_PAD"] = "1"
        if not getattr(args, "compile_goal", None):
            os.environ["OPENHAC_COMPILE_GOAL"] = "fabrication"
        if not os.environ.get("OPENHAC_ALLOW_NETWORK", "").strip():
            os.environ["OPENHAC_NO_NETWORK"] = "1"
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

    if getattr(args, "freerouting_gui", False):
        os.environ["OPENHAC_FREEROUTING_GUI"] = "1"
    elif getattr(args, "no_freerouting_gui", False):
        os.environ["OPENHAC_FREEROUTING_GUI"] = "0"

    if getattr(args, "compile_goal", None):
        os.environ["OPENHAC_COMPILE_GOAL"] = str(getattr(args, "compile_goal"))

    if getattr(args, "compile_goal", None):
        os.environ["OPENHAC_COMPILE_GOAL"] = str(getattr(args, "compile_goal"))

    if getattr(args, "require_verified_parts", False):
        os.environ["OPENHAC_REQUIRE_VERIFIED_PARTS"] = "1"

    if getattr(args, "db_path", None):
        os.environ["OPENHAC_DB_PATH"] = str(getattr(args, "db_path"))
    if getattr(args, "kicad_symbol_dirs", None):
        os.environ["OPENHAC_KICAD_SYMBOL_DIRS"] = str(getattr(args, "kicad_symbol_dirs"))
    if getattr(args, "kicad_symbol_dir", None):
        v = str(getattr(args, "kicad_symbol_dir"))
        for k in _kicad_sym_keys:
            os.environ[k] = v
        os.environ.setdefault("OPENHAC_KICAD_SYMBOL_DIRS", v)
    if getattr(args, "kicad_footprint_dir", None):
        v = str(getattr(args, "kicad_footprint_dir"))
        for k in _kicad_fp_keys:
            os.environ[k] = v

    if getattr(args, "schematic_strict", False):
        os.environ["OPENHAC_SCHEMATIC_STRICT"] = "1"

    try:
        logger.info("Compiling: %s", args.script)
        # Seed KiCad/SKiDL environment before user script import to reduce noisy warnings
        # and ensure symbol/footprint path defaults are available as early as possible.
        try:
            from openhac.core.env_setup import bootstrap_environment

            bootstrap_environment()
        except Exception:
            pass

        if getattr(args, "sync_jlc_before", False):
            from openhac.database.sync_jlc import sync_catalog

            cats = getattr(args, "sync_jlc_categories", None)
            categories = cats.split(",") if cats else None
            logger.info("Pipeline: syncing JLC catalog (categories=%s)...", categories or "default")
            n = sync_catalog(categories=categories, verbose=True)
            logger.info("Pipeline: JLC sync wrote %s components.", n)

        if getattr(args, "pre_seed_file", None):
            from openhac.database.sync_jlc import seed_from_file

            logger.info("Pipeline: seeding DB from %s", args.pre_seed_file)
            seed_from_file(str(args.pre_seed_file), verbose=True)

        if getattr(args, "pre_enrich_json", None):
            from openhac.database.db_manager import DatabaseManager
            from openhac.database.enrich import batch_enrich_from_json_file

            logger.info("Pipeline: enriching parts from %s", args.pre_enrich_json)
            db = DatabaseManager()
            attempted, updated = batch_enrich_from_json_file(
                str(args.pre_enrich_json),
                db=db,
                vendor=str(getattr(args, "pre_enrich_vendor", "auto") or "auto"),
                limit=int(getattr(args, "pre_enrich_limit", 0) or 0),
                quiet=False,
            )
            logger.info("Pipeline: batch enrich attempted=%s updated=%s", attempted, updated)

        user_module = _load_user_script(args.script)
        board = _find_board_instance(user_module)
        if board is None:
            logger.error(
                "No openhac.core.board.Board instance found. Assign your design to a variable "
                "named `board`, or expose exactly one Board at module level."
            )
            sys.exit(2)

        if getattr(args, "auto_enrich_board", False):
            from openhac.database.db_manager import DatabaseManager
            from openhac.database.enrich import batch_enrich_targets, discover_enrich_targets_from_board, network_allowed

            if not network_allowed():
                logger.warning(
                    "Auto-enrich-board: skipping online enrichment (network disabled via "
                    "OPENHAC_NO_NETWORK or deterministic mode without OPENHAC_ALLOW_NETWORK)."
                )
            else:
                db = DatabaseManager()
                targets = discover_enrich_targets_from_board(board)
                logger.info(
                    "Auto-enrich-board: %s unique part(s) lack pinout/symbol metadata in the DB; running vendor enrich.",
                    len(targets),
                )
                if targets:
                    attempted, updated = batch_enrich_targets(
                        targets,
                        db=db,
                        vendor=str(getattr(args, "auto_enrich_vendor", "auto") or "auto"),
                        limit=int(getattr(args, "auto_enrich_limit", 0) or 0),
                        quiet=False,
                    )
                    logger.info("Auto-enrich-board: attempted=%s updated=%s", attempted, updated)
                    
                    # Refresh components to pull in newly downloaded 3D model paths
                    if updated:
                        for mod in board._get_all_modules():
                            for comp in getattr(mod, "components", []):
                                if hasattr(comp, "refresh_from_db"):
                                    comp.refresh_from_db()

        name = args.name or _default_project_name(args.script)
        schematic_signoff = bool(getattr(args, "schematic_signoff", False)) or os.environ.get(
            "OPENHAC_SCHEMATIC_SIGNOFF", ""
        ).strip().lower() in ("1", "true", "yes", "on")
        if schematic_signoff:
            board.schematic_signoff = True
        # FAB-040: --production defaults schematic off unless user explicitly wants it
        # (omit --no-schematic and set OPENHAC_PRODUCTION_SCHEMATIC=1 to keep sch).
        # SSO-040: --schematic-signoff forces export even under --production.
        if schematic_signoff:
            export_schematic = True
        elif getattr(args, "production", False) and not getattr(args, "no_schematic", False):
            if os.environ.get("OPENHAC_PRODUCTION_SCHEMATIC", "").strip().lower() not in (
                "1",
                "true",
                "yes",
                "on",
            ):
                export_schematic = False
            else:
                export_schematic = not args.no_schematic
        else:
            export_schematic = not args.no_schematic
        kicad_erc = bool(getattr(args, "kicad_erc", False)) or schematic_signoff
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
        cg = getattr(args, "compile_goal", None)
        if cg:
            board.compile_goal = str(cg)
        elif getattr(args, "production", False):
            board.compile_goal = "fabrication"

        if getattr(args, "strict_footprint_pads", False) or getattr(args, "production", False):
            board.strict_footprint_pin_pad_match = True

        if getattr(args, "strict_kicad", False):
            board.strict_kicad = True
        if getattr(args, "production", False):
            board.strict_kicad = True
            board.strict_jit_lookups = True
        elif getattr(args, "strict_jit", False):
            board.strict_jit_lookups = True

        erc_fmt = "json" if getattr(args, "kicad_erc_json", False) else "report"

        cg = getattr(args, "compile_goal", None)
        if cg:
            board.compile_goal = str(cg)

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

        overlay_paths = getattr(args, "catalog_overlay", None) or []
        board.compile(
            project_name=name,
            generate_bom=True,
            auto_route=not args.no_route,
            export_schematic=export_schematic,
            allow_risky_part_lookups=Component.allow_risky_part_lookups,
            kicad_sch_erc=kicad_erc,
            kicad_sch_erc_format=erc_fmt,
            source_script_path=os.path.abspath(args.script),
            output_dir=getattr(args, "output_dir", None) or os.path.join(os.path.dirname(os.path.abspath(args.script)), name),
            release_zip_path=zip_path,
            bbox_padding_mm=float(getattr(args, "bbox_padding_mm", 0.5) or 0.5),
            # None → layout reads OPENHAC_MODULE_CLEARANCE_MM (.env); explicit CLI wins.
            module_clearance_mm=(
                float(args.module_gap_mm)
                if getattr(args, "module_gap_mm", None) is not None
                else 0.0
            ),
            deoverlap_max_iters=int(getattr(args, "deoverlap_iters", 200) or 200),
            deoverlap_step_mm=float(getattr(args, "deoverlap_step_mm", 0.75) or 0.75),
            catalog_overlay_paths=tuple(overlay_paths) if overlay_paths else (),
            schematic_signoff=schematic_signoff,
            compile_profile=getattr(args, "compile_profile", None),
            keep_kicad_artwork=bool(getattr(args, "keep_kicad_artwork", False)),
            regenerate_artwork=bool(getattr(args, "regenerate_artwork", False)),
            require_lock=bool(getattr(args, "require_lock", False)),
            lock_file=getattr(args, "lock_file", None),
            placement_intent=bool(getattr(args, "placement_intent", False)),
            require_testpoints=bool(getattr(args, "require_testpoints", False)),
            variant=getattr(args, "variant", None),
        )
        logger.info("Compilation complete.")
        try:
            from openhac.core.base import _IMPLICIT_PIN_EVENTS

            n_inv = len({str(e.get("generic_name") or "") for e in _IMPLICIT_PIN_EVENTS if e.get("invented")})
            if n_inv:
                logger.warning("CODE-006: invented Pin_N parts in this compile: %s", n_inv)
        except Exception:
            pass

        spice_signoff = bool(getattr(args, "spice_signoff", False))
        if os.environ.get("OPENHAC_SPICE_SIGNOFF", "").strip().lower() in ("1", "true", "yes", "on"):
            spice_signoff = True
        run_ngspice = bool(getattr(args, "run_ngspice", False))
        if spice_signoff or run_ngspice:
            if spice_signoff:
                os.environ["OPENHAC_SPICE_SIGNOFF"] = "1"
                board.spice_signoff = True
            if getattr(args, "spice_vendor_dir", None):
                os.environ["OPENHAC_SPICE_VENDOR_DIR"] = str(args.spice_vendor_dir)
            sim_out = getattr(args, "output_dir", None) or os.path.join(
                os.path.dirname(os.path.abspath(args.script)), name
            )
            board.simulate(
                project_name=name,
                allow_risky_part_lookups=Component.allow_risky_part_lookups,
                output_dir=sim_out,
                run_ngspice=run_ngspice,
                ngspice_log_path=getattr(args, "ngspice_log", None),
                spice_signoff=spice_signoff,
                allow_behavioral_spice_models=bool(
                    getattr(args, "allow_behavioral_spice_models", False)
                ),
                require_vendor_models=bool(getattr(args, "require_vendor_models", False)),
                spice_islands=getattr(args, "spice_islands", None),
            )
            logger.info("SPICE %s complete.", "sign-off" if spice_signoff else "export")

        # --- Optional interactive webview ---
        if getattr(args, "webview", False):
            logger.warning(
                "FAB-041: --webview is deprecated. Use `openhac preview` for KiCad SVG. "
                "ERC stamp remains --schematic-signoff (kicad-cli sch erc)."
            )
            try:
                out_dir = getattr(args, "output_dir", None) or os.path.join(
                    os.path.dirname(os.path.abspath(args.script)), name
                )
                webview_path = os.path.join(out_dir, f"{name}.graph-explorer.html")
                board.export_webview(webview_path)
                logger.info("Webview written: %s", webview_path)
                import webbrowser
                webbrowser.open(f"file://{os.path.abspath(webview_path)}")
            except Exception as e:
                logger.warning("Webview generation failed: %s", e)
    finally:
        if _prev_skip_layout is None:
            os.environ.pop("OPENHAC_SKIP_LAYOUT", None)
        else:
            os.environ["OPENHAC_SKIP_LAYOUT"] = _prev_skip_layout
        if _prev_fr_gui is None:
            os.environ.pop("OPENHAC_FREEROUTING_GUI", None)
        else:
            os.environ["OPENHAC_FREEROUTING_GUI"] = _prev_fr_gui
        if _prev_compile_goal is None:
            os.environ.pop("OPENHAC_COMPILE_GOAL", None)
        else:
            os.environ["OPENHAC_COMPILE_GOAL"] = _prev_compile_goal
        if _prev_deterministic is None:
            os.environ.pop("OPENHAC_DETERMINISTIC", None)
        else:
            os.environ["OPENHAC_DETERMINISTIC"] = _prev_deterministic
        if _prev_req_verified is None:
            os.environ.pop("OPENHAC_REQUIRE_VERIFIED_PARTS", None)
        else:
            os.environ["OPENHAC_REQUIRE_VERIFIED_PARTS"] = _prev_req_verified
        if _prev_no_network is None:
            os.environ.pop("OPENHAC_NO_NETWORK", None)
        else:
            os.environ["OPENHAC_NO_NETWORK"] = _prev_no_network
        if _prev_strict_fp_pad is None:
            os.environ.pop("OPENHAC_STRICT_FOOTPRINT_PIN_PAD", None)
        else:
            os.environ["OPENHAC_STRICT_FOOTPRINT_PIN_PAD"] = _prev_strict_fp_pad
        if _prev_db_path is None:
            os.environ.pop("OPENHAC_DB_PATH", None)
        else:
            os.environ["OPENHAC_DB_PATH"] = _prev_db_path
        if _prev_symbol_dirs is None:
            os.environ.pop("OPENHAC_KICAD_SYMBOL_DIRS", None)
        else:
            os.environ["OPENHAC_KICAD_SYMBOL_DIRS"] = _prev_symbol_dirs
        if _prev_schematic_strict is None:
            os.environ.pop("OPENHAC_SCHEMATIC_STRICT", None)
        else:
            os.environ["OPENHAC_SCHEMATIC_STRICT"] = _prev_schematic_strict
        if _prev_spice_signoff is None:
            os.environ.pop("OPENHAC_SPICE_SIGNOFF", None)
        else:
            os.environ["OPENHAC_SPICE_SIGNOFF"] = _prev_spice_signoff
        if _prev_spice_vendor is None:
            os.environ.pop("OPENHAC_SPICE_VENDOR_DIR", None)
        else:
            os.environ["OPENHAC_SPICE_VENDOR_DIR"] = _prev_spice_vendor
        if _prev_compile_goal is None:
            os.environ.pop("OPENHAC_COMPILE_GOAL", None)
        else:
            os.environ["OPENHAC_COMPILE_GOAL"] = _prev_compile_goal
        for k, prev in _prev_kicad_sym.items():
            if prev is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = prev
        for k, prev in _prev_kicad_fp.items():
            if prev is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = prev
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
    _kicad_sym_keys = ("KICAD9_SYMBOL_DIR", "KICAD8_SYMBOL_DIR", "KICAD7_SYMBOL_DIR", "KICAD6_SYMBOL_DIR")
    _kicad_fp_keys = ("KICAD9_FOOTPRINT_DIR", "KICAD8_FOOTPRINT_DIR", "KICAD_FOOTPRINT_DIR")
    _prev_kicad_sym = {k: os.environ.get(k) for k in _kicad_sym_keys}
    _prev_kicad_fp = {k: os.environ.get(k) for k in _kicad_fp_keys}
    Component.allow_risky_part_lookups = bool(getattr(args, "allow_risky_parts", False))
    if getattr(args, "deterministic", False):
        os.environ["OPENHAC_DETERMINISTIC"] = "1"
    if getattr(args, "db_path", None):
        os.environ["OPENHAC_DB_PATH"] = str(getattr(args, "db_path"))
    if getattr(args, "kicad_symbol_dir", None):
        v = str(getattr(args, "kicad_symbol_dir"))
        for k in _kicad_sym_keys:
            os.environ[k] = v
    if getattr(args, "kicad_footprint_dir", None):
        v = str(getattr(args, "kicad_footprint_dir"))
        for k in _kicad_fp_keys:
            os.environ[k] = v
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
    spice_signoff = bool(getattr(args, "spice_signoff", False))
    if spice_signoff:
        os.environ["OPENHAC_SPICE_SIGNOFF"] = "1"
        board.spice_signoff = True
    if getattr(args, "spice_vendor_dir", None):
        os.environ["OPENHAC_SPICE_VENDOR_DIR"] = str(args.spice_vendor_dir)
    board.simulate(
        project_name=name,
        allow_risky_part_lookups=Component.allow_risky_part_lookups,
        spice_analysis_lines=analysis_lines,
        output_dir=getattr(args, "output_dir", None),
        run_ngspice=bool(getattr(args, "run_ngspice", False)),
        ngspice_log_path=getattr(args, "ngspice_log", None),
        spice_signoff=spice_signoff,
        allow_behavioral_spice_models=bool(getattr(args, "allow_behavioral_spice_models", False)),
        require_vendor_models=bool(getattr(args, "require_vendor_models", False)),
        spice_islands=getattr(args, "spice_islands", None),
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
    for k, prev in _prev_kicad_sym.items():
        if prev is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = prev
    for k, prev in _prev_kicad_fp.items():
        if prev is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = prev


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
    pcbnew_import_ok = None
    pcbnew_import_error = None
    pcbnew_version = None
    try:
        import importlib

        m = importlib.import_module("pcbnew")
        pcbnew_import_ok = True
        pcbnew_version = str(getattr(m, "GetBuildVersion", lambda: None)() or "") or None
    except Exception as e:
        pcbnew_import_ok = False
        pcbnew_import_error = str(e)


    java = shutil.which("java")
    freerouting_jar = os.environ.get("FREEROUTING_JAR")
    freerouting_jar_exists = bool((freerouting_jar or "").strip() and os.path.isfile(freerouting_jar or ""))

    try:
        from openhac.database.vendor_apis import vendor_apis_configured

        vendor_apis_ok = vendor_apis_configured()
    except Exception:
        vendor_apis_ok = None
    vendor_api_env_present = {
        "digikey": bool((os.environ.get("DIGIKEY_CLIENT_ID") or "").strip() and (os.environ.get("DIGIKEY_CLIENT_SECRET") or "").strip()),
        "mouser": bool((os.environ.get("MOUSER_API_KEY") or "").strip()),
        "tme": bool((os.environ.get("TME_API_TOKEN") or "").strip() and (os.environ.get("TME_API_SECRET") or "").strip()),
        "jlcpcb": bool((os.environ.get("JLCPCB_API_KEY") or "").strip()),
    }

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
        "pcbnew_import_ok": pcbnew_import_ok,
        "pcbnew_version": pcbnew_version,
        "pcbnew_import_error": pcbnew_import_error,

        "java_path": java,
        "java_present": bool(java),
        "freerouting_jar": freerouting_jar,
        "freerouting_jar_exists": freerouting_jar_exists,
        "vendor_apis_configured": vendor_apis_ok,
        "vendor_api_env_present": vendor_api_env_present,
        "fp_lib_table_present": any(os.path.isfile(p) for p in fp_lib_table_candidates),
        "sym_lib_table_present": any(os.path.isfile(p) for p in sym_lib_table_candidates),
        "fp_lib_table_candidates": fp_lib_table_candidates,
        "sym_lib_table_candidates": sym_lib_table_candidates,
        "kicad_symbol_search_paths": [str(p) for p in symbol_library_search_paths()],
        "kicad_footprint_search_paths": list(footprint_search_roots()),
        "kicad_env": {
            k: os.environ.get(k)
            for k in sorted(
                (
                    "OPENHAC_KICAD_SYMBOL_DIRS",
                    "KICAD9_SYMBOL_DIR",
                    "KICAD8_SYMBOL_DIR",
                    "KICAD7_SYMBOL_DIR",
                    "KICAD6_SYMBOL_DIR",
                    "KICAD_SYMBOL_DIR",
                    "KICAD9_FOOTPRINT_DIR",
                    "KICAD8_FOOTPRINT_DIR",
                    "KICAD_FOOTPRINT_DIR",
                )
            )
        },
        "openhac_db_path": os.environ.get("OPENHAC_DB_PATH"),
        "openhac_deterministic": os.environ.get("OPENHAC_DETERMINISTIC"),
        "openhac_allow_risky_parts": os.environ.get("OPENHAC_ALLOW_RISKY_PARTS"),
        "openhac_require_verified_parts": os.environ.get("OPENHAC_REQUIRE_VERIFIED_PARTS"),
    }
    report["ok"] = True
    report["missing"] = []
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
    strict_config = bool(getattr(args, "strict_config", False))
    strict_routing = bool(getattr(args, "strict_routing", False))
    strict_default = bool(getattr(args, "strict", False))

    # Legacy umbrella: --strict implies all of them.
    if strict_default:
        strict_headless = True
        strict_layout = True
        strict_config = True
        strict_routing = True

    strict_any = bool(strict_headless or strict_layout or strict_config or strict_routing)
    if strict_any:
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

        # Tools
        if strict_headless and not kicad_cli:
            missing.append("kicad-cli")

        # Layout: pcbnew Python bindings are required (binary presence is not enough).
        if strict_layout and not bool(report.get("pcbnew_import_ok")):
            missing.append("pcbnew")

        # Config (only if explicitly requested via strict-config, or via legacy --strict)
        if strict_config:
            if (not report["sym_lib_table_present"]) and (not sym_env_configured):
                missing.append("sym-lib-table-or-KICAD*_SYMBOL_DIR")
            if (not report["fp_lib_table_present"]) and (not fp_env_configured):
                missing.append("fp-lib-table-or-KICAD*_FOOTPRINT_DIR")

        # Routing: explicitly require java + jar.
        if strict_routing:
            if not java:
                missing.append("java")
            if not (freerouting_jar or "").strip():
                missing.append("FREEROUTING_JAR")
            elif not freerouting_jar_exists:
                missing.append("freerouting_jar_exists")

    if strict_any and missing:
        report["ok"] = False
        report["missing"] = missing
        if getattr(args, "as_json", False):
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
    count = sync_catalog(
        categories=categories,
        verbose=verbose,
        include_extended=bool(getattr(args, "include_extended", False)),
        max_per_category=getattr(args, "max_per_category", None),
    )
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


def cmd_database_enrich(args):
    """Enrich missing part metadata (pinout, URLs, footprint verification) via vendor APIs."""
    import json
    from pathlib import Path

    from openhac.database.db_manager import DatabaseManager
    from openhac.database.enrich import (
        batch_enrich_targets,
        enrich_missing_pinouts_from_db,
        network_allowed,
        parse_enrich_targets_from_json,
    )

    _prev_db_path = os.environ.get("OPENHAC_DB_PATH")
    if getattr(args, "db_path", None):
        os.environ["OPENHAC_DB_PATH"] = str(getattr(args, "db_path"))

    if getattr(args, "no_network", False):
        os.environ["OPENHAC_NO_NETWORK"] = "1"

    db = DatabaseManager()

    skus_file = getattr(args, "skus_file", None)
    raw = json.loads(Path(skus_file).read_text(encoding="utf-8")) if skus_file else None
    targets = parse_enrich_targets_from_json(raw) if raw is not None else []

    limit = int(getattr(args, "limit", 0) or 0)
    vendor = str(getattr(args, "vendor", "auto") or "auto")
    missing = bool(getattr(args, "missing_pinouts", False))

    if missing:
        if not network_allowed():
            logger.error(
                "CAT-005: --missing-pinouts requires network; refused under "
                "OPENHAC_NO_NETWORK / fabrication."
            )
            raise SystemExit(2)
        attempted, updated = enrich_missing_pinouts_from_db(
            db, vendor=vendor, limit=limit, quiet=bool(getattr(args, "quiet", False))
        )
    else:
        if not targets:
            logger.error("No parts to enrich. Provide --skus-file or --missing-pinouts.")
            raise SystemExit(2)
        attempted, updated = batch_enrich_targets(
            targets,
            db=db,
            vendor=vendor,
            limit=limit,
            quiet=bool(getattr(args, "quiet", False)),
        )

    logger.info("Enrichment complete. attempted=%s updated=%s", attempted, updated)

    if _prev_db_path is None:
        os.environ.pop("OPENHAC_DB_PATH", None)
    else:
        os.environ["OPENHAC_DB_PATH"] = _prev_db_path


def cmd_export_dsn(args):
    """Export Specctra DSN from a saved PCB and patch IPC netclass widths."""
    from openhac.compiler.autoroute_cli import export_dsn_with_ipc_widths

    pcb = args.pcb
    out = getattr(args, "output", None)
    logger.info("Exporting Specctra DSN from %s (placement unchanged)", pcb)
    path = export_dsn_with_ipc_widths(
        pcb,
        dsn_path=out,
        require_dsn_widths=bool(getattr(args, "strict", False)),
    )
    logger.info("Wrote Specctra DSN with IPC netclass widths: %s", path)


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
        assembler=getattr(args, "assembler", None),
    )
    logger.info("Fabrication export complete.")


def cmd_export_jlc(args):
    """MFG-010: JLCPCB-shaped BOM + CPL. Does not invent LCSC SKUs."""
    from openhac.compiler.export_jlc import export_jlc_pack

    strict = bool(getattr(args, "strict", True))
    written = export_jlc_pack(
        args.source,
        args.output,
        strict=strict,
        bom_csv=getattr(args, "bom", None),
    )
    for kind, path in written.items():
        logger.info("JLC %s → %s", kind, path)


def cmd_lock(args):
    """LOCK-001: write a catalog lockfile from the local DB (no HTTP)."""
    from pathlib import Path

    from openhac.database.catalog_lock import collect_lock_entries, write_lockfile

    prev_nn = os.environ.get("OPENHAC_NO_NETWORK")
    os.environ["OPENHAC_NO_NETWORK"] = "1"
    logger.info("LOCK-001: writing lock from local catalog only (no network).")
    try:
        user_mod = _load_user_script(args.script)
        board = _find_board_instance(user_mod)
        if board is None:
            logger.error("No Board instance in %s", args.script)
            sys.exit(1)
        name = getattr(args, "name", None) or _default_project_name(args.script)
        entries = collect_lock_entries(board)
        dest = getattr(args, "output", None)
        if not dest:
            dest = str(Path(os.path.abspath(args.script)).parent / "openhac.lock")
        write_lockfile(dest, entries, project=name)
        print(f"Wrote {dest} ({len(entries)} parts)", flush=True)
    finally:
        if prev_nn is None:
            os.environ.pop("OPENHAC_NO_NETWORK", None)
        else:
            os.environ["OPENHAC_NO_NETWORK"] = prev_nn


def cmd_pinout_init(args):
    """PIN-001: overlay JSON stub from catalog / KiCad symbol oracle. No datasheet scrape."""
    from openhac.compiler.pinout_init import build_pinout_stub, write_pinout_overlay

    stub = build_pinout_stub(args.query)
    dest = getattr(args, "output", None)
    if not dest:
        dest = f"{stub['generic_name']}.pinout.overlay.json"
    write_pinout_overlay(stub, dest)
    print(f"Wrote {dest} pinout_hash={stub.get('pinout_hash', '')}", flush=True)


def cmd_catalog_coverage(args):
    """CAT-006: catalog depth report. Does not fetch."""
    from openhac.database.catalog_coverage import (
        collect_catalog_coverage,
        coverage_text_report,
        write_coverage_json,
    )
    from openhac.database.db_manager import DatabaseManager

    db = DatabaseManager()
    report = collect_catalog_coverage(db)
    out = getattr(args, "output", None)
    if out:
        write_coverage_json(report, out)
        logger.info("Wrote coverage JSON: %s", out)
    if getattr(args, "as_json", False) or getattr(args, "json", False):
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(coverage_text_report(report), end="")


def cmd_catalog_prefetch_3d(args):
    """3D-003: prefetch EasyEDA 3D into ~/.kiro/openhac/. Forbidden under no-network / fab."""
    from openhac.database.db_manager import DatabaseManager
    from openhac.database.enrich import network_allowed, prefetch_3d_for_skus, prefetch_3d_from_board

    if not network_allowed():
        logger.error(
            "3D-003: catalog prefetch-3d is forbidden under OPENHAC_NO_NETWORK / fabrication."
        )
        raise SystemExit(2)

    db = DatabaseManager()
    script = getattr(args, "script", None)
    skus_raw = getattr(args, "skus", None) or ""
    skus = [s.strip() for s in str(skus_raw).split(",") if s.strip()]
    if script:
        user_mod = _load_user_script(script)
        board = _find_board_instance(user_mod)
        if board is None:
            logger.error("No Board instance in %s", script)
            raise SystemExit(1)
        attempted, updated = prefetch_3d_from_board(board, db=db)
    elif skus:
        attempted, updated = prefetch_3d_for_skus(skus, db=db)
    else:
        logger.error("Provide a board .py or --skus C123,C456")
        raise SystemExit(2)
    logger.info("prefetch-3d complete. attempted=%s updated=%s", attempted, updated)


def cmd_spice_coverage(args):
    """SPS-050: analog coverage without ngspice or HTTP fetch of .lib."""
    from openhac.compiler.spice_gen import _circuit_and_parts
    from openhac.compiler.spice_models import collect_spice_coverage

    user_mod = _load_user_script(args.script)
    board = _find_board_instance(user_mod)
    if board is None:
        logger.error("No Board instance in %s", args.script)
        raise SystemExit(1)
    _circuit, parts = _circuit_and_parts(signoff=False)
    rows = collect_spice_coverage(parts)
    report = {
        "schema": "openhac.spice_coverage.v1",
        "coverage": rows,
        "counts": {},
    }
    for r in rows:
        st = str(r.get("status") or "")
        report["counts"][st] = report["counts"].get(st, 0) + 1
    if getattr(args, "as_json", False):
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        for r in rows:
            extra = f" ({r['reason']})" if r.get("reason") else ""
            print(f"{r.get('ref')}: {r.get('status')}{extra}")
        print("counts:", json.dumps(report["counts"], sort_keys=True))
    # Report, not sign-off: exit 0 even when unmodeled.
    return 0


def cmd_spice_verify_vendor_dir(args):
    """SPS-052: local hash + .subckt arity for kind=vendor records. No network."""
    from pathlib import Path

    from openhac.compiler.spice_models import verify_vendor_dir_records
    from openhac.core.base import OpenHaCError

    extra = []
    ov = getattr(args, "overlay", None)
    if ov:
        extra.append(Path(ov))
    try:
        errors = verify_vendor_dir_records(extra_paths=extra or None)
    except OpenHaCError as e:
        logger.error("%s", e)
        raise SystemExit(1) from e
    if errors:
        for err in errors:
            logger.error("%s", err)
        raise SystemExit(1)
    print("spice verify-vendor-dir: ok")


def _setup_logging(verbose: bool = False):
    """Configure structured logging for the OpenHaC toolchain."""
    level = logging.DEBUG if verbose else logging.INFO
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    logging.basicConfig(level=level, format=fmt, datefmt="%H:%M:%S")
    # Do NOT call getLogger("skidl") before SKiDL imports — that creates a stdlib
    # Logger and breaks SkidlLogger (AttributeError: bare_error) on later import.


def _quiet_skidl_logging(verbose: bool = False) -> None:
    """Lower SKiDL log noise after SKiDL has been imported (optional)."""
    if verbose:
        return
    if "skidl" not in sys.modules:
        return
    logging.getLogger("skidl").setLevel(logging.WARNING)


def main():
    from openhac.version_info import get_version

    load_repo_dotenv(quiet=True)
    apply_kicad_env_aliases()

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
    p_compile.add_argument(
        "--no-route",
        "--no-autoroute",
        "--skip-autoroute",
        action="store_true",
        dest="no_route",
        help="Skip FreeRouting / auto-routing (PCB + Specctra DSN with IPC widths still written unless --skip-layout)",
    )
    p_fr_gui = p_compile.add_mutually_exclusive_group()
    p_fr_gui.add_argument(
        "--freerouting-gui",
        action="store_true",
        dest="freerouting_gui",
        help="Show the FreeRouting Java window while autorouting (sets OPENHAC_FREEROUTING_GUI=1). Default is headless.",
    )
    p_fr_gui.add_argument(
        "--no-freerouting-gui",
        action="store_true",
        dest="no_freerouting_gui",
        help="Force headless FreeRouting (overrides OPENHAC_FREEROUTING_GUI in .env).",
    )
    p_compile.add_argument(
        "--compile-goal",
        default=None,
        choices=("handoff", "fabrication"),
        help="Pipeline gating policy: 'handoff' (reviewable KiCad outputs) vs 'fabrication' (stricter pass/fail). "
        "Sets OPENHAC_COMPILE_GOAL for this run.",
    )
    p_compile.add_argument(
        "--skip-layout",
        action="store_true",
        help="Skip pcbnew layout generation and autoroute (sets OPENHAC_SKIP_LAYOUT=1 for the run)",
    )
    art = p_compile.add_mutually_exclusive_group()
    art.add_argument(
        "--keep-kicad-artwork",
        action="store_true",
        help="LIVE-006: merge last-saved .kicad_sch/.kicad_pcb pose and copper; fail if overlay is missing "
        "or KiCad connectivity shorts graph nets. Skips autoroute so user copper is not clobbered.",
    )
    art.add_argument(
        "--regenerate-artwork",
        action="store_true",
        help="LIVE-006: ignore saved KiCad overlay and fully rewrite schematic/PCB artwork",
    )
    p_compile.add_argument(
        "--placement-intent",
        action="store_true",
        help="PLC-001: fail if overlay footprint pose is outside the board or courtyards overlap catastrophically",
    )
    p_compile.add_argument(
        "--require-lock",
        action="store_true",
        help="LOCK-001: fail if openhac.lock is missing or disagrees with the resolved BOM",
    )
    p_compile.add_argument(
        "--lock-file",
        default=None,
        metavar="PATH",
        help="LOCK-001: catalog lockfile path (default: openhac.lock next to the board script)",
    )
    p_compile.add_argument(
        "--require-testpoints",
        action="store_true",
        help="TST-001: fail if Board.declare_testpoint nets are missing from the graph",
    )
    p_compile.add_argument(
        "--variant",
        default=None,
        metavar="NAME",
        help="VAR-001: select Board variant (DNP / include_in_variants)",
    )
    p_compile.add_argument(
        "--kicad-symbol-dirs",
        default=None,
        metavar="PATHS",
        help="Pathsep-separated extra KiCad symbol search dirs (sets OPENHAC_KICAD_SYMBOL_DIRS for the run)",
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
        "--schematic-signoff",
        action="store_true",
        help="SSO: require EE-stamped .kicad_sch (library/pinout symbols, graph parity, kicad-cli sch erc). "
        "Forces schematic export even under --production.",
    )
    p_compile.add_argument(
        "--spice-signoff",
        action="store_true",
        help="SPS: after compile, write a Kirchhoff .cir and fail-closed ngspice sign-off "
        "(same as `openhac simulate --spice-signoff`). Implies --run-ngspice.",
    )
    p_compile.add_argument(
        "--run-ngspice",
        action="store_true",
        help="After compile, write {name}.cir and run ngspice (handoff). "
        "Implied by --spice-signoff.",
    )
    p_compile.add_argument(
        "--allow-behavioral-spice-models",
        action="store_true",
        help="SPS-017: allow kind=behavioral models under --spice-signoff (not physics-correct).",
    )
    p_compile.add_argument(
        "--require-vendor-models",
        action="store_true",
        help="SPS-034: fail if OPENHAC_SPICE_VENDOR_DIR is unset.",
    )
    p_compile.add_argument(
        "--spice-vendor-dir",
        default=None,
        metavar="DIR",
        help="Vendor .lib directory (sets OPENHAC_SPICE_VENDOR_DIR for this run).",
    )
    p_compile.add_argument(
        "--spice-island",
        action="append",
        dest="spice_islands",
        metavar="MODULE",
        help="SPS-043: restrict spice_signoff to this module name (repeatable). "
        "Digital cores and connectors stay omitted. Analog ICs in the island still need models.",
    )
    p_compile.add_argument(
        "--ngspice-log",
        default=None,
        metavar="PATH",
        help="Optional ngspice log path when --run-ngspice or --spice-signoff is set.",
    )
    p_compile.add_argument(
        "--schematic-strict",
        action="store_true",
        help="Documentation-grade schematics: forbid implicit pins (sets OPENHAC_SCHEMATIC_STRICT=1).",
    )
    p_compile.add_argument(
        "--bbox-padding-mm",
        type=float,
        default=0.5,
        help="Extra padding (mm) applied to footprint bounding boxes for PCB fit / keepout checks and "
        "post-process clamping/de-overlap. Default: 0.5",
    )
    p_compile.add_argument(
        "--deoverlap-iters",
        type=int,
        default=200,
        help="Max iterations for PCB de-overlap post-process (default: 200).",
    )
    p_compile.add_argument(
        "--deoverlap-step-mm",
        type=float,
        default=0.75,
        help="Step size (mm) for PCB de-overlap post-process (default: 0.75).",
    )
    p_compile.add_argument(
        "--module-gap-mm",
        type=float,
        default=None,
        help="Minimum edge-to-edge gap (mm) between module bounding boxes in the Z3 placer "
        "(reduces footprint spill-over between regions). "
        "Omit to use OPENHAC_MODULE_CLEARANCE_MM from the environment / .env (typical 2–4 dense, 5+ roomy).",
    )
    p_compile.add_argument(
        "--strict-footprint-pads",
        action="store_true",
        help="Fail compile if any netted pin has no matching footprint pad (PCB-002); same as "
        "Board(strict_footprint_pin_pad_match=True) or OPENHAC_STRICT_FOOTPRINT_PIN_PAD=1",
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
        "--strict",
        action="store_true",
        dest="production",
        help="FAB-030: fabrication gate set — compile_goal=fabrication, strict KiCad/JIT, "
        "verified parts, strict footprint pads, OPENHAC_NO_NETWORK=1, schematic off by default "
        "(set OPENHAC_PRODUCTION_SCHEMATIC=1 to keep .kicad_sch)",
    )
    p_compile.add_argument(
        "--require-verified-parts",
        action="store_true",
        help="Fail DRC if any JIT/unverified parts (medium/low confidence) are present (sets OPENHAC_REQUIRE_VERIFIED_PARTS=1)",
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
    p_compile.add_argument(
        "--sync-jlc-before",
        action="store_true",
        help="Before compile, run JLC catalog sync (same as `openhac sync`; can be slow).",
    )
    p_compile.add_argument(
        "--sync-jlc-categories",
        default=None,
        metavar="LIST",
        help="With --sync-jlc-before, comma-separated category list (default: all configured categories).",
    )
    p_compile.add_argument(
        "--pre-seed-file",
        default=None,
        metavar="PATH",
        help="Before compile, seed the DB from JSON (same as `python -m openhac.database.sync_jlc --seed-file`).",
    )
    p_compile.add_argument(
        "--pre-enrich-json",
        default=None,
        metavar="PATH",
        help="Before compile, batch-enrich parts from JSON (same format as `openhac database enrich --skus-file`).",
    )
    p_compile.add_argument(
        "--pre-enrich-vendor",
        default="auto",
        choices=("auto", "jlcpcb", "digikey", "mouser", "tme"),
        help="Vendor preference for --pre-enrich-json (default: auto).",
    )
    p_compile.add_argument(
        "--pre-enrich-limit",
        default=0,
        type=int,
        help="Max enrichment attempts for --pre-enrich-json (0 = no limit).",
    )
    p_compile.add_argument(
        "--auto-enrich-board",
        action="store_true",
        help="After loading the board script, discover parts missing pinout/symbol_data in the DB, run batch enrich "
        "(requires vendor API env vars; see vendor_apis), then compile. "
        "Implicit-pin warnings during script import are unchanged unless the DB was already filled (e.g. sync + enrich).",
    )
    p_compile.add_argument(
        "--auto-enrich-vendor",
        default="auto",
        choices=("auto", "jlcpcb", "digikey", "mouser", "tme"),
        help="Vendor preference for --auto-enrich-board (default: auto).",
    )
    p_compile.add_argument(
        "--auto-enrich-limit",
        default=0,
        type=int,
        help="Max enrichment attempts for --auto-enrich-board (0 = no limit).",
    )
    p_compile.add_argument(
        "--catalog-overlay",
        action="append",
        default=None,
        metavar="PATH",
        help="JSON catalog overlay file or directory (*.json). Repeatable; merged after bundled overlays. "
        "Same as env OPENHAC_CATALOG_OVERLAY (pathsep-separated). See openhac/database/catalog_overlay.py.",
    )
    p_compile.add_argument(
        "--compile-profile",
        choices=("preview", "logic", "fabrication", "handoff"),
        default=None,
        help="PERF-006: preview=schematic+SVG path (skip enrich/layout/route/ERC); "
        "logic=skip-layout; fabrication=full gates.",
    )
    p_compile.add_argument(
        "--webview",
        action="store_true",
        help="Deprecated (FAB-041). Cytoscape HTML explorer; prefer `openhac preview`.",
    )
    p_compile.set_defaults(func=cmd_compile)

    p_preview = subparsers.add_parser(
        "preview",
        help="SSO-012: schematic + KiCad SVG (not ERC-stamped; never runs sch erc)",
    )
    p_preview.add_argument("script", help="Path to the hardware description .py file")
    p_preview.add_argument("--name", default=None, help="Output base name (default: script basename)")
    p_preview.add_argument("-o", "--output-dir", default=None, metavar="DIR")
    p_preview.add_argument(
        "--catalog-overlay",
        action="append",
        default=None,
        metavar="PATH",
    )
    p_preview.add_argument(
        "--kicad",
        action="store_true",
        help="Open KiCad GUI on the generated project (live session: use with --watch)",
    )
    p_preview.add_argument(
        "--watch",
        action="store_true",
        help="Rebuild on .py save; serve a localhost SVG viewer of the KiCad export (LIVE-008)",
    )
    p_preview.add_argument(
        "--pcb",
        action="store_true",
        help="LIVE-007: also emit a place-only .kicad_pcb (no autoroute, no ERC); merge saved artwork",
    )
    p_preview.add_argument(
        "--no-browser",
        action="store_true",
        help="With --watch, print the SVG viewer URL but do not open a browser",
    )
    p_preview.set_defaults(func=cmd_preview)

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
    p_sim.add_argument(
        "--run-ngspice",
        action="store_true",
        help="After generating the .cir file, run ngspice in batch mode (requires ngspice on PATH).",
    )
    p_sim.add_argument(
        "--ngspice-log",
        default=None,
        metavar="PATH",
        help="Optional path for ngspice log output (default: <name>.cir.ngspice.log in output dir).",
    )
    p_sim.add_argument(
        "--spice-signoff",
        action="store_true",
        help="SPS: fail-closed Kirchhoff + vendor/physics models + ngspice + probe/bench windows.",
    )
    p_sim.add_argument(
        "--allow-behavioral-spice-models",
        action="store_true",
        help="SPS-017: allow kind=behavioral models under --spice-signoff (not physics-correct).",
    )
    p_sim.add_argument(
        "--require-vendor-models",
        action="store_true",
        help="SPS-034: fail if OPENHAC_SPICE_VENDOR_DIR is unset (do not skip vendor goldens).",
    )
    p_sim.add_argument(
        "--spice-vendor-dir",
        default=None,
        metavar="DIR",
        help="Directory of vendor .lib files (sets OPENHAC_SPICE_VENDOR_DIR for this run).",
    )
    p_sim.add_argument(
        "--spice-island",
        action="append",
        dest="spice_islands",
        metavar="MODULE",
        help="SPS-043: restrict spice_signoff to this module name (repeatable).",
    )
    p_sim.set_defaults(func=cmd_simulate)

    p_sync = subparsers.add_parser("sync", help="Sync JLCPCB component catalog")
    p_sync.add_argument("--categories", default=None, help="Comma-separated categories")
    p_sync.add_argument("-q", "--quiet", action="store_true", help="Suppress verbose output")
    p_sync.add_argument(
        "--include-extended",
        action="store_true",
        help="CAT-003: drop is_basic=true (default stays Basic in-stock)",
    )
    p_sync.add_argument(
        "--max-per-category",
        type=int,
        default=None,
        metavar="N",
        help="Cap fetches/inserts per typed category (CAT-003)",
    )
    p_sync.set_defaults(func=cmd_sync)

    p_seed = subparsers.add_parser("seed", help="Seed database with sample components")
    p_seed.set_defaults(func=cmd_seed)

    p_db = subparsers.add_parser("database", help="Database utilities")
    db_sub = p_db.add_subparsers(dest="db_command", required=True)
    p_enrich = db_sub.add_parser("enrich", help="Enrich missing part metadata via vendor APIs")
    p_enrich.add_argument(
        "--skus-file",
        required=False,
        metavar="PATH",
        help="JSON list of parts to enrich (dicts with generic_name/mpn/supplier_sku, or simple names).",
    )
    p_enrich.add_argument(
        "--missing-pinouts",
        "--from-db",
        action="store_true",
        dest="missing_pinouts",
        help="CAT-005: walk catalog rows lacking a named pinout (never used by --production).",
    )
    p_enrich.add_argument(
        "--vendor",
        default="auto",
        choices=("auto", "jlcpcb", "digikey", "mouser", "tme", "nexar", "octopart"),
        help="Preferred vendor API (default: auto). nexar/octopart fail closed without keys.",
    )
    p_enrich.add_argument(
        "--limit",
        default=0,
        type=int,
        help="Optional limit on number of enrichment attempts (0 = no limit).",
    )
    p_enrich.add_argument("--no-network", action="store_true", help="Disable online lookups for this run.")
    p_enrich.add_argument("-q", "--quiet", action="store_true", help="Reduce per-part output.")
    p_enrich.set_defaults(func=cmd_database_enrich)

    p_export = subparsers.add_parser("export", help="Export fabrication outputs (requires kicad-cli)")
    export_sub = p_export.add_subparsers(dest="export_target", required=True)
    p_dsn = export_sub.add_parser(
        "dsn",
        help="Specctra DSN from a saved .kicad_pcb with IPC netclass widths patched (no re-placement)",
    )
    p_dsn.add_argument("pcb", help="Path to .kicad_pcb (use the board you edited in KiCad)")
    p_dsn.add_argument(
        "-o",
        "--output",
        default=None,
        help="Output .dsn path (default: same stem as the PCB)",
    )
    p_dsn.add_argument(
        "--strict",
        action="store_true",
        help="Fail if IPC width rules cannot be patched into the DSN",
    )
    p_dsn.set_defaults(func=cmd_export_dsn)
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
    p_fab.add_argument(
        "--assembler",
        default=None,
        choices=("jlc", "jlcpcb"),
        help="MFG-010: also write assembler-shaped BOM/CPL (jlc fails closed on missing LCSC)",
    )
    p_fab.set_defaults(func=cmd_export_fab)

    p_jlc = export_sub.add_parser(
        "jlc",
        help="JLCPCB-shaped BOM + CPL from an OpenHaC BOM CSV / .kicad_pcb (MFG-010)",
    )
    p_jlc.add_argument("source", help="BOM .csv or .kicad_pcb (sibling .csv required)")
    p_jlc.add_argument(
        "-o",
        "--output",
        required=True,
        help="Output directory",
    )
    p_jlc.add_argument(
        "--bom",
        default=None,
        help="Explicit OpenHaC BOM CSV (default: sibling of the PCB)",
    )
    p_jlc.add_argument(
        "--strict",
        action="store_true",
        default=True,
        help="Fail closed if LCSC C-codes are missing (default)",
    )
    p_jlc.add_argument(
        "--allow-missing-lcsc",
        action="store_false",
        dest="strict",
        help="Write empty LCSC cells instead of failing (still does not invent SKUs)",
    )
    p_jlc.set_defaults(func=cmd_export_jlc)

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
    p_doc.add_argument(
        "--strict-config",
        action="store_true",
        help="Exit nonzero if KiCad library configuration is missing (fp-lib-table/sym-lib-table or KICAD*_DIR hints)",
    )
    p_doc.add_argument(
        "--strict-routing",
        action="store_true",
        help="Exit nonzero if routing prerequisites are missing (java + FREEROUTING_JAR)",
    )
    p_doc.set_defaults(func=cmd_doctor)

    p_catalog = subparsers.add_parser("catalog", help="Catalog coverage and 3D prefetch (CAT/3D)")
    cat_sub = p_catalog.add_subparsers(dest="catalog_command", required=True)
    p_cov = cat_sub.add_parser("coverage", help="Depth report: compile_ready vs warehouse (no fetch)")
    p_cov.add_argument("--json", dest="as_json", action="store_true", help="Print JSON")
    p_cov.add_argument("-o", "--output", default=None, help="Write openhac.catalog_coverage.v1 JSON")
    p_cov.set_defaults(func=cmd_catalog_coverage)
    p_pf = cat_sub.add_parser(
        "prefetch-3d",
        help="Prefetch EasyEDA 3D into ~/.kiro/openhac/ (forbidden under no-network / fab)",
    )
    p_pf.add_argument("script", nargs="?", default=None, help="Board .py whose SKUs to prefetch")
    p_pf.add_argument("--skus", default=None, help="Comma-separated LCSC SKUs (Cxxxxx)")
    p_pf.set_defaults(func=cmd_catalog_prefetch_3d)

    p_spice = subparsers.add_parser("spice", help="SPICE coverage and vendor-dir verify (SPS-05x)")
    spice_sub = p_spice.add_subparsers(dest="spice_command", required=True)
    p_scov = spice_sub.add_parser(
        "coverage",
        help="List primitive/modeled/omitted/unmodeled without running ngspice",
    )
    p_scov.add_argument("script", help="Board .py")
    p_scov.add_argument("--json", dest="as_json", action="store_true", help="Print JSON")
    p_scov.set_defaults(func=cmd_spice_coverage)
    p_sver = spice_sub.add_parser(
        "verify-vendor-dir",
        help="Check kind=vendor files exist, sha256, .subckt arity (no network)",
    )
    p_sver.add_argument("--overlay", default=None, help="Extra spice overlay JSON or directory")
    p_sver.set_defaults(func=cmd_spice_verify_vendor_dir)

    p_lock = subparsers.add_parser("lock", help="Write catalog lockfile from the local DB (LOCK-001, no fetch)")
    p_lock.add_argument("script", help="Board .py")
    p_lock.add_argument("--name", default=None, help="Project name recorded in the lock")
    p_lock.add_argument(
        "-o",
        "--output",
        default=None,
        help="Lock path (default: openhac.lock next to the script)",
    )
    p_lock.set_defaults(func=cmd_lock)

    p_pin = subparsers.add_parser("pinout", help="Pinout overlay authoring (PIN-001)")
    pin_sub = p_pin.add_subparsers(dest="pinout_command", required=True)
    p_pinit = pin_sub.add_parser("init", help="Write overlay JSON stub from catalog / KiCad symbol oracle")
    p_pinit.add_argument("query", help="generic_name or LCSC SKU")
    p_pinit.add_argument("-o", "--output", default=None, help="Overlay JSON path")
    p_pinit.set_defaults(func=cmd_pinout_init)

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
