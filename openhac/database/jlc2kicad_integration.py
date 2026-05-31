import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger("openhac.database.jlc2kicad_integration")

def get_jlc2kicad_library_dir() -> Path:
    """Return the global directory for JLC2KiCAD generated symbols."""
    home = Path.home()
    p = home / ".kiro" / "openhac" / "jlc2kicad_generated"
    p.mkdir(parents=True, exist_ok=True)
    return p

def generate_symbol_from_lcsc(lcsc_id: str) -> str | None:
    """Fetch symbol data via JLC2KiCAD CLI.
    
    Args:
        lcsc_id: The LCSC part number (e.g. 'C12345').
        
    Returns:
        The generated symbol ID (e.g. 'jlc2kicad_generated:C12345') or None on failure.
    """
    if not lcsc_id or not str(lcsc_id).startswith("C"):
        return None
        
    out_dir = get_jlc2kicad_library_dir()
    
    # Try to find the jlc2kicad executable
    import shutil
    cmd = shutil.which("JLC2KiCadLib") or shutil.which("jlc2kicad")
    if not cmd:
        # Fallback to common pip install locations
        fallbacks = []
        for name in ["JLC2KiCadLib", "jlc2kicad"]:
            fallbacks.extend([
                Path.home() / ".local" / "bin" / name,
                Path("/usr/local/bin") / name,
                Path("/usr/bin") / name
            ])
        logger.info("Searching for JLC2KiCAD binary in: %s", [str(f) for f in fallbacks])
        for fb in fallbacks:
            if fb.exists():
                cmd = str(fb)
                logger.info("Found JLC2KiCAD binary at %s", cmd)
                break
    
    if not cmd:
        # Check if it can be run as a module (try both common namings)
        import sys
        logger.info("Checking if JLC2KiCAD/JLC2KiCadLib is available as a python module...")
        for mod_name in ["JLC2KiCAD", "JLC2KiCadLib"]:
            try:
                # Check for importability instead of --version
                subprocess.run([sys.executable, "-c", f"import {mod_name}"], capture_output=True, check=True)
                cmd = [sys.executable, "-m", mod_name]
                logger.info("Found JLC2KiCAD module: %s", mod_name)
                break
            except Exception as e:
                logger.debug("Module %s not found: %s", mod_name, e)
                continue
        
        if not cmd:
            logger.warning("JLC2KiCAD not found in PATH or as a module. Symbol generation will be best-effort.")
            cmd = "jlc2kicad" # Try raw and hope for the best
    
    try:
        # Universal retrieval: fetch everything (Symbol, Footprint, 3D Model)
        # JLC2KiCAD will place these in the directory structure.
        if isinstance(cmd, list):
            args = cmd + [
                lcsc_id,
                "-dir", str(out_dir),
                "-symbol_lib", "jlc2kicad_generated",
                "-footprint_lib", "jlc2kicad_generated"
            ]
        else:
            args = [
                cmd,
                lcsc_id,
                "-dir", str(out_dir),
                "-symbol_lib", "jlc2kicad_generated",
                "-footprint_lib", "jlc2kicad_generated"
            ]
        
        logger.info("Executing JLC2KiCAD command: %s", " ".join(args) if isinstance(args, list) else args)
        result = subprocess.run(args, capture_output=True, text=True, check=False)
        
        if result.returncode != 0:
            logger.warning("JLC2KiCAD failed for %s: %s", lcsc_id, result.stderr)
            return None
            
        # JLC2KiCAD may create the file directly or inside a subdirectory
        # We recursively search for the first .kicad_sym file created
        syms = list(out_dir.rglob("*.kicad_sym"))
        if syms:
            # Pick the most recently modified one or just the first one found
            sym_file = sorted(syms, key=lambda p: p.stat().st_mtime, reverse=True)[0]
            logger.info("Found generated symbol file: %s", sym_file)
        else:
            # Log what we DO see to help debug
            all_files = [str(p.relative_to(out_dir)) for p in out_dir.rglob("*")]
            logger.warning("JLC2KiCAD finished but no .kicad_sym found in %s. Seen files: %s", out_dir, all_files)
            return None
        
        # Return both the symbol ID and the path to the 3D model if found.
        # Format: (symbol_id, 3d_model_path)
        lib_name = sym_file.stem
        
        m3d_path = None
        # JLC2KiCAD usually puts 3D models in a 'packages3d' or '3d' subdirectory
        m3d_files = list(out_dir.rglob("*.step")) + list(out_dir.rglob("*.wrl"))
        if m3d_files:
            # Pick the one matching our lcsc_id or the most recent
            m3d_path = str(m3d_files[0].absolute())
            logger.info("Found generated 3D model file: %s", m3d_path)

        return f"jlc2kicad_generated:{lib_name}", m3d_path
        
    except Exception as e:
        logger.warning("Error running JLC2KiCAD for %s: %s", lcsc_id, e)
        return None, None
