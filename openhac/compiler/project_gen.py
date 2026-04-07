import json
import logging
import os
from pathlib import Path

logger = logging.getLogger("openhac.project")

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


def generate_project_file(output_path: str, *, sym_lib_path: str | None = None, sym_lib_nick: str = "OpenHaC"):
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
