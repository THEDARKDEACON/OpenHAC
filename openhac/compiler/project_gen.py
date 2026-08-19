import json
import logging
import os
import re
from pathlib import Path

logger = logging.getLogger("openhac.project")


def footprint_library_names_from_board(board) -> list[str]:
    """Collect KiCad footprint library nicknames (``Lib`` in ``Lib:Footprint``) from placed parts."""
    libs: set[str] = set()
    try:
        modules = []
        if hasattr(board, "_get_all_modules"):
            modules = board._get_all_modules()
        else:
            modules = getattr(board, "modules", []) or []

        for mod in modules:
            for child in getattr(mod, "components", []) or []:
                p = getattr(child, "part", None)
                if p is None:
                    continue
                fp = str(getattr(p, "footprint", "") or "").strip()
                if ":" in fp:
                    lib = fp.split(":", 1)[0].strip()
                    if lib:
                        libs.add(lib)
    except Exception:
        return []
    logger.debug("Found footprint libraries in board: %s", sorted(libs))
    return sorted(libs)


def write_sym_lib_table(
    *,
    output_dir: str | os.PathLike[str],
    sym_path: str | None = None,
    nickname: str = "OpenHaC",
    extra_libs: list[str] | None = None,
) -> str:
    """Write a KiCad ``sym-lib-table`` for generated + system symbol libraries."""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / "sym-lib-table"

    lines = ["(sym_lib_table\n"]
    if sym_path:
        sym_rel = Path(sym_path).name
        lines.append(
            f'  (lib (name "{nickname}") (type "KiCad") '
            f'(uri "${{KIPRJMOD}}/{sym_rel}") (options "") '
            f'(descr "OpenHaC generated symbols"))\n'
        )
    root = "${KICAD9_SYMBOL_DIR}" if os.environ.get("KICAD9_SYMBOL_DIR") else "/usr/share/kicad/symbols"
    seen = {nickname} if sym_path else set()
    for lib in sorted({str(x).strip() for x in (extra_libs or []) if str(x).strip()}):
        if lib in seen or lib == nickname:
            continue
        seen.add(lib)
        lines.append(
            f'  (lib (name "{lib}") (type "KiCad") '
            f'(uri "{root}/{lib}.kicad_sym") (options "") (descr ""))\n'
        )
    lines.append(")\n")
    p.write_text("".join(lines), encoding="utf-8")
    return str(p)


def write_fp_lib_table(*, output_dir: str | os.PathLike[str], footprint_libs: list[str]) -> str:
    """Write a project-local KiCad ``fp-lib-table`` for the used footprint libraries.

    KiCad 8/9 uses fp-lib-table to resolve ``Library:Footprint`` strings to ``*.pretty`` dirs.
    We generate entries only for libraries actually used by the design, pointing at the
    local install footprint root via ${KICAD9_FOOTPRINT_DIR} (fallback to /usr/share/kicad/footprints).
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / "fp-lib-table"

    root_var = "${KICAD9_FOOTPRINT_DIR}"
    root_fallback = "/usr/share/kicad/footprints"
    root = root_var if os.environ.get("KICAD9_FOOTPRINT_DIR") else root_fallback

    libs = []
    for lib in sorted({str(x).strip() for x in (footprint_libs or []) if str(x).strip()}):
        if lib == "easyeda_generated":
            # Global easyeda generated footprints
            uri = "${HOME}/.kiro/openhac/easyeda_generated.pretty"
            libs.append(
                f'  (lib (name "{lib}") (type "KiCad") (uri "{uri}") (options "") (descr ""))\n'
            )
        else:
            libs.append(
                f'  (lib (name "{lib}") (type "KiCad") (uri "{root}/{lib}.pretty") (options "") (descr ""))\n'
            )
    body = "(fp_lib_table\n" + "".join(libs) + ")\n"
    p.write_text(body, encoding="utf-8")
    return str(p)


def _kicad9_netclass_entry(
    name: str,
    *,
    track_width: float,
    clearance: float,
    via_diameter: float,
    via_drill: float,
    diff_pair_width: float = 0.2,
    diff_pair_gap: float = 0.25,
    priority: int = 0,
) -> dict:
    """KiCad 9 ``net_settings.classes[]`` object (fields the GUI round-trips on save)."""
    is_default = name == "Default"
    return {
        "bus_width": 12,
        "clearance": round(float(clearance), 4),
        "diff_pair_gap": round(float(diff_pair_gap), 4),
        "diff_pair_via_gap": round(float(diff_pair_gap), 4),
        "diff_pair_width": round(float(diff_pair_width), 4),
        "line_style": 0,
        "microvia_diameter": 0.3,
        "microvia_drill": 0.1,
        "name": str(name),
        "pcb_color": "rgba(0, 0, 0, 0.000)",
        "priority": 2147483647 if is_default else int(priority),
        "schematic_color": "rgba(0, 0, 0, 0.000)",
        "track_width": round(float(track_width), 4),
        "via_diameter": round(float(via_diameter), 4),
        "via_drill": round(float(via_drill), 4),
        "wire_width": 6,
    }


def _ipc_class_tables(board) -> tuple[dict[str, dict], dict[str, str]]:
    """Build IPC-2152 class dicts and net→class assignments from the OpenHaC board."""
    from openhac.compiler.pcb_physics import (
        _ipc2152_width_mm,
        _netclass_for_current,
        collect_net_currents_a,
    )

    default_w = 0.25
    try:
        from openhac.compiler.fab_design_settings import resolve_fab_geometry_mm

        default_w = max(default_w, float(resolve_fab_geometry_mm(board).get("min_trace_width_mm") or 0.25))
    except Exception:
        pass

    net_classes: dict[str, dict] = {
        "Default": _kicad9_netclass_entry(
            "Default",
            track_width=default_w,
            clearance=0.2,
            via_diameter=0.8,
            via_drill=0.4,
        )
    }
    assignments: dict[str, str] = {}
    if board is None:
        return net_classes, assignments

    nets_with_current = collect_net_currents_a(board)
    class_max_a: dict[str, float] = {}
    for amps in nets_with_current.values():
        cn = _netclass_for_current(amps)
        class_max_a[cn] = max(class_max_a.get(cn, 0.0), float(amps))

    prio = 0
    for class_name, amps in sorted(class_max_a.items(), key=lambda kv: kv[0]):
        width_mm = _ipc2152_width_mm(amps)
        net_classes[class_name] = _kicad9_netclass_entry(
            class_name,
            track_width=width_mm,
            clearance=max(0.2, width_mm * 0.5),
            via_diameter=max(0.8, width_mm * 1.5),
            via_drill=max(0.4, width_mm * 0.7),
            priority=prio,
        )
        prio += 1
        logger.info(
            "IPC-2152: class %s (bucket max %.3fA) → %.3fmm track width",
            class_name,
            amps,
            round(width_mm, 3),
        )
    for net_name, amps in nets_with_current.items():
        assignments[str(net_name)] = _netclass_for_current(amps)

    for dp in getattr(board, "_diff_pair_intents", None) or []:
        if not isinstance(dp, dict):
            continue
        p = str(dp.get("net_p") or dp.get("p_net") or "").strip()
        n = str(dp.get("net_n") or dp.get("n_net") or "").strip()
        try:
            z0 = int(round(float(dp.get("z0_ohm") or dp.get("target_z0_ohms") or 90)))
        except (TypeError, ValueError):
            z0 = 90
        cls = f"DiffPair_{z0}ohm"
        if cls not in net_classes:
            net_classes[cls] = _kicad9_netclass_entry(
                cls,
                track_width=0.2,
                clearance=0.2,
                via_diameter=0.8,
                via_drill=0.4,
                diff_pair_width=0.2,
                diff_pair_gap=0.2,
                priority=prio,
            )
            prio += 1
        if p:
            assignments[p] = cls
        if n:
            assignments[n] = cls
    return net_classes, assignments


def _fab_board_rules(board) -> dict:
    """KiCad 9 ``board.design_settings.rules`` mins from the fab profile."""
    geo = {
        "min_trace_width_mm": 0.15,
        "min_trace_clearance_mm": 0.15,
        "min_via_drill_mm": 0.3,
        "min_edge_clearance_mm": 0.25,
    }
    try:
        from openhac.compiler.fab_design_settings import resolve_fab_geometry_mm

        geo.update(resolve_fab_geometry_mm(board))
    except Exception:
        pass
    return {
        "max_error": 0.005,
        "min_clearance": round(float(geo["min_trace_clearance_mm"]), 4),
        "min_connection": 0.0,
        "min_copper_edge_clearance": round(float(geo["min_edge_clearance_mm"]), 4),
        "min_groove_width": 0.0,
        "min_hole_clearance": round(float(geo["min_trace_clearance_mm"]), 4),
        "min_hole_to_hole": round(float(geo["min_via_drill_mm"]), 4),
        "min_microvia_diameter": 0.2,
        "min_microvia_drill": 0.1,
        "min_resolved_spokes": 2,
        "min_silk_clearance": 0.0,
        "min_text_height": 0.8,
        "min_text_thickness": 0.08,
        "min_through_hole_diameter": 0.2,
        "min_track_width": round(float(geo["min_trace_width_mm"]), 4),
        "min_via_annular_width": 0.1,
        "min_via_diameter": round(max(0.5, float(geo["min_via_drill_mm"]) + 0.2), 4),
        "solder_mask_to_copper_clearance": 0.0,
        "use_height_for_length_calcs": True,
    }


def netclasses_sidecar_path(pro_or_pcb: str | Path) -> Path:
    """Compile-time netclass map KiCad will not rewrite on PCB/project save."""
    p = Path(pro_or_pcb)
    return p.with_name(p.stem + ".openhac-netclasses.json")


def _merged_track_widths_mm(existing, class_list: list[dict]) -> list[float]:
    """KiCad Board Setup → Tracks dropdown; 0.0 means 'use netclass width'."""
    vals: list[float] = [0.0]
    if isinstance(existing, list):
        for x in existing:
            try:
                vals.append(round(float(x), 4))
            except (TypeError, ValueError):
                continue
    for cls in class_list:
        try:
            vals.append(round(float(cls.get("track_width")), 4))
        except (TypeError, ValueError):
            continue
    out: list[float] = []
    seen: set[float] = set()
    for v in vals:
        if v in seen:
            continue
        seen.add(v)
        out.append(v)
    return out


def _merged_via_dimensions(existing, class_list: list[dict]) -> list[dict]:
    rows: list[dict] = []
    seen: set[tuple[float, float]] = set()

    def _add(diameter, drill) -> None:
        try:
            d = round(float(diameter), 4)
            h = round(float(drill), 4)
        except (TypeError, ValueError):
            return
        key = (d, h)
        if key in seen or d <= 0 or h <= 0:
            return
        seen.add(key)
        rows.append({"diameter": d, "drill": h})

    if isinstance(existing, list):
        for row in existing:
            if isinstance(row, dict):
                _add(row.get("diameter"), row.get("drill"))
    for cls in class_list:
        _add(cls.get("via_diameter"), cls.get("via_drill"))
    return rows


def _dru_ident(prefix: str, raw: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_]+", "_", str(raw)).strip("_") or "x"
    return f"{prefix}_{safe}"[:80]


def write_kicad_custom_rules(
    dru_path: str | Path,
    *,
    net_classes: dict[str, dict],
    board=None,
) -> Path | None:
    """Emit KiCad 9 ``.kicad_dru`` so DRC keeps compile-time widths / pairs / skew."""
    path = Path(dru_path)
    rules: list[str] = ["(version 1)", ""]
    for name, cls in sorted(net_classes.items()):
        if name == "Default" or not isinstance(cls, dict):
            continue
        try:
            tw = round(float(cls["track_width"]), 4)
            cl = round(float(cls.get("clearance") or max(0.2, tw * 0.5)), 4)
            vd = round(float(cls.get("via_diameter") or 0.8), 4)
            vh = round(float(cls.get("via_drill") or 0.4), 4)
        except (TypeError, ValueError, KeyError):
            continue
        cond = f"A.NetClass == '{name}'"
        rules.append(f'(rule "{_dru_ident("OpenHaC_width", name)}"')
        rules.append(f"\t(constraint track_width (min {tw}mm) (opt {tw}mm) )")
        rules.append(f"\t(constraint clearance (min {cl}mm) )")
        rules.append(f"\t(constraint via_diameter (min {vd}mm) )")
        rules.append(f"\t(constraint hole_size (min {vh}mm) )")
        rules.append(f'\t(condition "{cond}" )')
        rules.append(")")
        rules.append("")
        dpw = cls.get("diff_pair_width")
        dpg = cls.get("diff_pair_gap")
        if str(name).startswith("DiffPair_") and dpw is not None and dpg is not None:
            try:
                w = round(float(dpw), 4)
                g = round(float(dpg), 4)
            except (TypeError, ValueError):
                w = g = None
            if w and g:
                rules.append(f'(rule "{_dru_ident("OpenHaC_diff", name)}"')
                rules.append(f"\t(constraint track_width (min {w}mm) (opt {w}mm) )")
                rules.append(f"\t(constraint diff_pair_gap (min {g}mm) (opt {g}mm) )")
                rules.append(f'\t(condition "{cond}" )')
                rules.append(")")
                rules.append("")

    for rec in getattr(board, "_length_match_intents", None) or []:
        if not isinstance(rec, dict):
            continue
        nets = [str(n) for n in (rec.get("nets") or []) if str(n).strip()]
        if len(nets) < 2:
            continue
        try:
            tol = float(rec.get("tolerance_mm") or 0.5)
        except (TypeError, ValueError):
            tol = 0.5
        cond = " || ".join(f"A.NetName == '{n}'" for n in nets)
        rules.append(f'(rule "{_dru_ident("OpenHaC_skew", rec.get("name") or "_".join(nets))}"')
        rules.append(f"\t(constraint skew (max {tol}mm) )")
        rules.append(f'\t(condition "{cond}" )')
        rules.append(")")
        rules.append("")

    body = "\n".join(rules).rstrip() + "\n"
    if "(rule " not in body:
        return None
    path.write_text(body, encoding="utf-8")
    logger.info("Wrote KiCad custom DRC rules: %s", path.name)
    return path


def restore_kicad_pro_net_settings(pro_or_pcb: str | Path) -> bool:
    """Re-inject compile-time ``net_settings`` after a KiCad GUI save.

    KiCad 9 Board Setup is ``net_settings.classes`` + ``netclass_patterns``.
    A save that never loaded those tables writes Default-only. The sidecar
    next to the project is not touched by pcbnew, so it can heal the ``.kicad_pro``.
    """
    target = Path(pro_or_pcb)
    pro = target if target.suffix == ".kicad_pro" else target.with_suffix(".kicad_pro")
    sidecar = netclasses_sidecar_path(pro if target.suffix == ".kicad_pro" else target)
    if not sidecar.is_file() or not pro.is_file():
        return False
    try:
        side = json.loads(sidecar.read_text(encoding="utf-8"))
        data = json.loads(pro.read_text(encoding="utf-8"))
    except Exception as e:
        logger.debug("KiCad net_settings restore skipped (parse): %s", e)
        return False
    if not isinstance(side, dict) or not isinstance(data, dict):
        return False
    classes_map = side.get("classes") if isinstance(side.get("classes"), dict) else {}
    assignments = side.get("assignments") if isinstance(side.get("assignments"), dict) else {}
    if not classes_map:
        return False

    ns = dict(data.get("net_settings") or {}) if isinstance(data.get("net_settings"), dict) else {}
    by_name: dict[str, dict] = {}
    for row in ns.get("classes") or []:
        if isinstance(row, dict) and row.get("name"):
            by_name[str(row["name"])] = dict(row)
    for name, cls in classes_map.items():
        if isinstance(cls, dict):
            by_name[str(name)] = dict(cls)
            by_name[str(name)]["name"] = str(name)
    class_list = []
    if "Default" in by_name:
        class_list.append(by_name["Default"])
    class_list.extend(by_name[k] for k in sorted(by_name) if k != "Default")

    patterns = [
        {"netclass": str(cls), "pattern": str(net)}
        for net, cls in sorted(assignments.items())
        if net and cls
    ]
    ns["classes"] = class_list
    ns["meta"] = ns.get("meta") if isinstance(ns.get("meta"), dict) else {"version": 4}
    ns.setdefault("meta", {})["version"] = int(ns["meta"].get("version") or 4)
    ns["net_colors"] = ns.get("net_colors", None)
    ns["netclass_assignments"] = None
    ns["netclass_patterns"] = patterns
    data["net_settings"] = ns

    board_block = dict(data.get("board") or {}) if isinstance(data.get("board"), dict) else {}
    ds = dict(board_block.get("design_settings") or {}) if isinstance(board_block.get("design_settings"), dict) else {}
    ds["track_widths"] = _merged_track_widths_mm(ds.get("track_widths"), class_list)
    ds["via_dimensions"] = _merged_via_dimensions(ds.get("via_dimensions"), class_list)
    ds["net_classes"] = {
        "classes": class_list,
        "setup": [{"class": str(c), "net": str(n)} for n, c in sorted(assignments.items())],
    }
    board_block["design_settings"] = ds
    data["board"] = board_block

    pro.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    logger.info("Restored KiCad 9 net_settings into %s from compile sidecar.", pro.name)
    return True


def _project_sheets(existing: dict, *, schematic_ir=None, board=None) -> list[list[str]]:
    """KiCad 9 ``sheets`` table: Root schematic UUID plus hierarchical boxes."""
    parts = None
    if schematic_ir is None and board is not None:
        try:
            from openhac.schematic.collect import collect_parts_and_nets

            parts, _ = collect_parts_and_nets(board)
        except Exception:
            parts = None
    try:
        from openhac.schematic.kicad_links import project_sheet_table

        rows = project_sheet_table(ir=schematic_ir, parts=parts)
        if rows:
            return rows
    except Exception:
        pass
    prev = existing.get("sheets") if isinstance(existing.get("sheets"), list) else []
    return [list(r) for r in prev if isinstance(r, (list, tuple)) and len(r) >= 2]


def generate_project_file(
    output_path: str,
    *,
    sym_lib_path: str | None = None,
    sym_lib_nick: str = "OpenHaC",
    footprint_libs: list[str] | None = None,
    symbol_libs: list[str] | None = None,
    board=None,
    schematic_ir=None,
):
    logger.info(f"Synthesizing KiCad Project Directory Matrix -> {output_path}")

    try:
        net_classes, net_class_assignments = _ipc_class_tables(board)
    except Exception as e:
        logger.warning("Failed to calculate IPC-2152 NetClasses: %s", e)
        net_classes, net_class_assignments = _ipc_class_tables(None)

    existing: dict = {}
    pro = Path(output_path)
    if pro.is_file():
        try:
            loaded = json.loads(pro.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                existing = loaded
        except Exception:
            existing = {}

    class_list = list(net_classes.values())
    patterns = [
        {"netclass": cls_name, "pattern": net_name}
        for net_name, cls_name in sorted(net_class_assignments.items())
        if net_name and cls_name
    ]
    legacy_setup = [
        {"class": cls_name, "net": net_name}
        for net_name, cls_name in sorted(net_class_assignments.items())
    ]

    sheets = _project_sheets(existing, schematic_ir=schematic_ir, board=board)

    board_block = dict(existing.get("board") or {}) if isinstance(existing.get("board"), dict) else {}
    ds = dict(board_block.get("design_settings") or {}) if isinstance(board_block.get("design_settings"), dict) else {}
    ds["rules"] = {**dict(ds.get("rules") or {}), **_fab_board_rules(board)}
    # Legacy path kept so older collectors still work; KiCad 9 ignores it.
    ds["net_classes"] = {
        "classes": class_list,
        "setup": legacy_setup,
    }
    ds["track_widths"] = _merged_track_widths_mm(ds.get("track_widths"), class_list)
    ds["via_dimensions"] = _merged_via_dimensions(ds.get("via_dimensions"), class_list)
    board_block["design_settings"] = ds
    board_block.setdefault("layer_presets", [])

    project_payload = {
        "board": board_block,
        "boards": list(existing.get("boards") or []),
        "cvpcb": existing.get("cvpcb") if isinstance(existing.get("cvpcb"), dict) else {"equivalence_files": []},
        "general": existing.get("general") if isinstance(existing.get("general"), dict) else {},
        "libraries": existing.get("libraries")
        if isinstance(existing.get("libraries"), dict)
        else {"pinned_footprint_libs": [], "pinned_symbol_libs": []},
        "meta": {
            "filename": os.path.basename(output_path),
            "version": 3,
        },
        "net_settings": {
            "classes": class_list,
            "meta": {"version": 4},
            "net_colors": None,
            # KiCad 9 round-trips assignments via netclass_patterns and writes
            # this field as null on save. A dict here can make the GUI drop the
            # whole net_settings table (Default 0.2 mm after File → Save).
            "netclass_assignments": None,
            "netclass_patterns": patterns,
        },
        "pcbnew": existing.get("pcbnew") if isinstance(existing.get("pcbnew"), dict) else {},
        "schematic": existing.get("schematic") if isinstance(existing.get("schematic"), dict) else {},
        "sheets": sheets,
        "text_variables": existing.get("text_variables")
        if isinstance(existing.get("text_variables"), dict)
        else {},
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(project_payload, f, indent=2, sort_keys=True)

    try:
        sidecar = Path(output_path).with_name(Path(output_path).stem + ".openhac-netclasses.json")
        widths_mm = {}
        for net_name, cls_name in net_class_assignments.items():
            cls = net_classes.get(cls_name) or {}
            tw = cls.get("track_width")
            if tw is not None:
                widths_mm[net_name] = float(tw)
        sidecar.write_text(
            json.dumps(
                {
                    "schema": "openhac.netclasses.v1",
                    "assignments": dict(net_class_assignments),
                    "classes": {n: dict(c) for n, c in net_classes.items()},
                    "widths_mm": widths_mm,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    except Exception as e:
        logger.debug("Netclass sidecar write skipped: %s", e)

    try:
        write_kicad_custom_rules(
            Path(output_path).with_suffix(".kicad_dru"),
            net_classes=net_classes,
            board=board,
        )
    except Exception as e:
        logger.debug("KiCad custom rules (.kicad_dru) write skipped: %s", e)

    logger.info("Project Directory configuration locked.")

    if sym_lib_path or symbol_libs:
        try:
            out_dir = str(Path(output_path).resolve().parent)
            write_sym_lib_table(
                output_dir=out_dir,
                sym_path=sym_lib_path,
                nickname=sym_lib_nick,
                extra_libs=list(symbol_libs or []),
            )
        except Exception as e:
            logger.warning("Failed to write sym-lib-table (continuing): %s", e)

    if footprint_libs:
        try:
            out_dir = str(Path(output_path).resolve().parent)
            write_fp_lib_table(output_dir=out_dir, footprint_libs=list(footprint_libs))
        except Exception as e:
            logger.warning("Failed to write fp-lib-table (continuing): %s", e)
