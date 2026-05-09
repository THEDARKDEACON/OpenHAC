import logging
import os
import urllib.request
from pathlib import Path
from typing import Optional

logger = logging.getLogger("openhac.threed_downloader")

def get_global_3d_cache_dir() -> Path:
    """Return the global directory for 3D models."""
    home = Path.home()
    p = home / ".kiro" / "openhac" / "3d_models"
    p.mkdir(parents=True, exist_ok=True)
    return p

def download_3d_model(sku: str, uuid: Optional[str] = None) -> Optional[str]:
    """Download a 3D model (.step) for a given SKU or EasyEDA UUID.
    
    Args:
        sku: LCSC SKU (e.g. 'C6396158')
        uuid: Optional EasyEDA 3D model UUID. If not provided, will try to resolve via SKU.
        
    Returns:
        Absolute path to the downloaded .step file, or None on failure.
    """
    if not sku and not uuid:
        return None
        
    cache_dir = get_global_3d_cache_dir()
    # Use SKU as filename if possible for easier manual audit
    filename = f"{sku}.step" if sku else f"{uuid}.step"
    local_path = cache_dir / filename
    
    if local_path.exists():
        return str(local_path)
        
    # If no UUID, we need to resolve it via EasyEDA API (indirectly)
    if not uuid:
        try:
            from easyeda2kicad.easyeda.easyeda_api import EasyedaApi
            api = EasyedaApi()
            cad_data = api.get_cad_data_of_component(sku)
            if cad_data and "3dmodel" in cad_data:
                # EasyEDA cad_data contains '3dmodel' field which is often the UUID
                uuid = cad_data.get("3dmodel")
            elif cad_data and "footprint" in cad_data:
                # Sometimes it is nested in footprint JSON string
                import json
                fp_data = json.loads(cad_data["footprint"])
                # The 3D model UUID is often in the footer or a specific field
                # For now, let easyeda2kicad handle the heavy lifting if we can't find it easily
                pass
        except Exception as e:
            logger.debug("Failed to resolve 3D model UUID for %s: %s", sku, e)

    # Fallback to easyeda2kicad's internal downloader if we can't get direct URL
    try:
        from easyeda2kicad.easyeda.easyeda_importer import Easyeda3dModelImporter, EasyedaApi
        from easyeda2kicad.kicad.export_kicad_3d_model import Exporter3dModelKicad
        
        api = EasyedaApi()
        data = api.get_cad_data_of_component(sku)
        if data:
            model = Easyeda3dModelImporter(data, download_raw_3d_model=True).create_3d_model()
            if model:
                Exporter3dModelKicad(model).export(str(local_path))
                logger.info("Successfully downloaded 3D model for %s to %s", sku, local_path)
                return str(local_path)
    except Exception as e:
        logger.warning("Failed to download 3D model for %s: %s", sku, e)
        
    return None
