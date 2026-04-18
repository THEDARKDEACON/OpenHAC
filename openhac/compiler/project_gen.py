import json
import logging
import os
from pathlib import Path

logger = logging.getLogger("openhac.project")


def footprint_library_names_from_board(board) -> list[str]:
    """Collect KiCad footprint library nicknames (``Lib`` in ``Lib:Footprint``) from placed parts."""
    libs: set[str] = set()
    try:
        for mod in getattr(board, "modules", []) or []:
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
):
    logger.info(f"Synthesizing KiCad Project Directory Matrix -> {output_path}")
    
    # The modern .kicad_pro file is a strict JSON wrapper stitching the ecosystem together
    project_payload = {
        "meta": {
            "filename": os.path.basename(output_path),
            "version": 3
        },
        "board": {
            "design_settings": {},
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
