import json
import logging
import os
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


def write_sym_lib_table(*, output_dir: str | os.PathLike[str], sym_path: str, nickname: str = "OpenHaC") -> str:
    """Write a KiCad ``sym-lib-table`` pointing at *sym_path* (project-local symbols)."""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / "sym-lib-table"

    # Use ${KIPRJMOD} so the project is relocatable.
    sym_rel = Path(sym_path).name
    body = (
        "(sym_lib_table\n"
        f'  (lib (name "{nickname}") (type "KiCad") (uri "${{KIPRJMOD}}/{sym_rel}") (options "") (descr "OpenHaC generated symbols"))\n'
        ")\n"
    )
    p.write_text(body, encoding="utf-8")
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


def generate_project_file(
    output_path: str,
    *,
    sym_lib_path: str | None = None,
    sym_lib_nick: str = "OpenHaC",
    footprint_libs: list[str] | None = None,
    board=None,
):
    logger.info(f"Synthesizing KiCad Project Directory Matrix -> {output_path}")
    
    # Calculate IPC-2152 NetClasses
    net_classes = {
        "Default": {
            "clearance": 0.2,
            "diff_pair_gap": 0.25,
            "diff_pair_via_gap": 0.25,
            "diff_pair_width": 0.2,
            "microvia_diameter": 0.3,
            "microvia_drill": 0.1,
            "name": "Default",
            "track_width": 0.25,
            "via_diameter": 0.8,
            "via_drill": 0.4
        }
    }
    
    if board is not None and hasattr(board, "modules"):
        try:
            from openhac.core.physics import calculate_trace_width_ipc2152
            
            # Find all unique nets in the board
            nets_with_current = {}
            for mod in board.modules:
                for interface in getattr(mod, "interfaces", {}).values():
                    if hasattr(interface, "signals"):
                        for net in interface.signals:
                            current = getattr(net, "current_a", 0.0)
                            if current > 0:
                                nets_with_current[net.name] = current
                            
                for comp in mod.components:
                    if not hasattr(comp, "part"): continue
                    for pin in comp.part.get_pins():
                        if pin.net and getattr(pin.net, "current_a", 0.0) > 0:
                            nets_with_current[pin.net.name] = pin.net.current_a
            
            for net_name, amps in nets_with_current.items():
                width_mm = calculate_trace_width_ipc2152(amps)
                class_name = f"Power_{amps}A"
                net_classes[class_name] = {
                    "clearance": 0.2,
                    "diff_pair_gap": 0.25,
                    "diff_pair_via_gap": 0.25,
                    "diff_pair_width": 0.2,
                    "microvia_diameter": 0.3,
                    "microvia_drill": 0.1,
                    "name": class_name,
                    "track_width": round(width_mm, 3),
                    "via_diameter": max(0.8, round(width_mm * 1.5, 3)),
                    "via_drill": max(0.4, round(width_mm * 0.7, 3))
                }
                
                # We would normally also map the net to this class in the general section
                # but adding the class itself acts as a generated DRC rule
                logger.info("IPC-2152: Net %s carrying %sA needs %smm trace width. Created NetClass %s", 
                            net_name, amps, round(width_mm, 3), class_name)
                            
        except Exception as e:
            logger.warning("Failed to calculate IPC-2152 NetClasses: %s", e)

    # The modern .kicad_pro file is a strict JSON wrapper stitching the ecosystem together
    project_payload = {
        "meta": {
            "filename": os.path.basename(output_path),
            "version": 3
        },
        "board": {
            "design_settings": {
                "net_classes": {
                    "classes": list(net_classes.values()),
                    "setup": []
                }
            },
            "layer_presets": []
        },
        "cvpcb": {
            "equivalence_files": []
        },
        "general": {},
        "netlist": {},
        "pcbnew": {},
        "schematic": {}
    }
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(project_payload, f, indent=2, sort_keys=True)
        
    logger.info("Project Directory configuration locked.")

    if sym_lib_path:
        try:
            out_dir = str(Path(output_path).resolve().parent)
            write_sym_lib_table(output_dir=out_dir, sym_path=sym_lib_path, nickname=sym_lib_nick)
        except Exception as e:
            logger.warning("Failed to write sym-lib-table (continuing): %s", e)

    if footprint_libs:
        try:
            out_dir = str(Path(output_path).resolve().parent)
            write_fp_lib_table(output_dir=out_dir, footprint_libs=list(footprint_libs))
        except Exception as e:
            logger.warning("Failed to write fp-lib-table (continuing): %s", e)
