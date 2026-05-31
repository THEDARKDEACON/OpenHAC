import logging
import os
from pathlib import Path

logger = logging.getLogger("openhac.database.easyeda_integration")

def get_easyeda_library_dir() -> Path:
    """Return the global directory for EasyEDA generated footprints."""
    # Place it in ~/.kiro/openhac/easyeda_generated.pretty
    home = Path.home()
    p = home / ".kiro" / "openhac" / "easyeda_generated.pretty"
    p.mkdir(parents=True, exist_ok=True)
    return p

def get_easyeda_3d_library_dir() -> Path:
    """Return the global directory for EasyEDA generated 3D models."""
    home = Path.home()
    p = home / ".kiro" / "openhac" / "easyeda_generated.3dshapes"
    p.mkdir(parents=True, exist_ok=True)
    return p

def generate_footprint_from_lcsc(lcsc_id: str) -> str | None:
    """Fetch CAD data from EasyEDA and generate a KiCad footprint.
    
    Args:
        lcsc_id: The LCSC part number (e.g. 'C12345').
        
    Returns:
        The generated footprint ID (e.g. 'easyeda_generated:LQFP-100...') or None on failure.
    """
    if not lcsc_id or not str(lcsc_id).startswith("C"):
        return None
        
    out_dir = get_easyeda_library_dir()
    out_3d_dir = get_easyeda_3d_library_dir()
    
    try:
        from easyeda2kicad.easyeda.easyeda_api import EasyedaApi
        from easyeda2kicad.kicad.export_kicad_footprint import ExporterFootprintKicad
        from easyeda2kicad.easyeda.easyeda_importer import EasyedaFootprintImporter, Easyeda3dModelImporter
        from easyeda2kicad.kicad.export_kicad_3d_model import Exporter3dModelKicad
    except ImportError:
        logger.warning("easyeda2kicad is not installed. Cannot fetch footprint for %s", lcsc_id)
        return None
        
    try:
        api = EasyedaApi()
        data = api.get_cad_data_of_component(lcsc_id)
        if not data:
            logger.warning("No CAD data found on EasyEDA for %s", lcsc_id)
            return None
            
        fp = EasyedaFootprintImporter(data).get_footprint()
        if not fp or not getattr(fp, "info", None) or not fp.info.name:
            logger.warning("Failed to parse footprint from EasyEDA data for %s", lcsc_id)
            return None
            
        # Clean the footprint name to avoid filesystem issues
        safe_name = str(fp.info.name).replace("/", "_").replace("\\", "_").strip()
        if not safe_name:
            safe_name = f"LCSC_{lcsc_id}"
            
        fp.info.name = safe_name
        out_path = out_dir / f"{safe_name}.kicad_mod"
        
        # 3D Model export
        model_3d_path = ""
        try:
            model = Easyeda3dModelImporter(data, download_raw_3d_model=True).create_3d_model()
            if model:
                # Use a consistent name for the 3D model that matches the footprint
                out_3d_path = out_3d_dir / f"{safe_name}.step"
                
                # Record files before
                before = set(out_3d_dir.glob("*.step"))
                Exporter3dModelKicad(model).export(str(out_3d_dir))
                # Record files after
                after = set(out_3d_dir.glob("*.step"))
                new_files = after - before
                
                if not out_3d_path.exists() and new_files:
                    # Rename the first new file found
                    new_file = list(new_files)[0]
                    import shutil
                    shutil.move(str(new_file), str(out_3d_path))
                    # Also move .wrl if it exists
                    new_wrl = new_file.with_suffix(".wrl")
                    if new_wrl.exists():
                        shutil.move(str(new_wrl), str(out_3d_path.with_suffix(".wrl")))
                
                if out_3d_path.exists():
                    model_3d_path = str(out_3d_path)
                    logger.info("Successfully exported 3D model for %s to %s", lcsc_id, model_3d_path)
        except Exception as e:
            logger.warning("Failed to export 3D model for %s: %s", lcsc_id, e)
        
        # easyeda2kicad exporter takes (output_path, model_3d_path, extension)
        exporter = ExporterFootprintKicad(fp)
        if model_3d_path:
            # We must pass the path to the exporter so it's written into the .kicad_mod
            exporter.export(str(out_path), model_3d_path, "step")
        else:
            exporter.export(str(out_path), "")
        
        logger.info("Successfully generated footprint %s for %s via EasyEDA (3D: %s)", 
                    safe_name, lcsc_id, "yes" if model_3d_path else "no")
        return f"easyeda_generated:{safe_name}", model_3d_path
        
    except Exception as e:
        logger.warning("Error generating EasyEDA footprint for %s: %s", lcsc_id, e)
        return None, None
