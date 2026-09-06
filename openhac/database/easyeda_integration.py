import logging
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

logger = logging.getLogger("openhac.database.easyeda_integration")

# Process-wide EasyEDA CAD throttle / 403 breaker (no API key; public CAD endpoint).
_THROTTLE: dict = {
    "last_mono": 0.0,
    "fails": 0,
    "open": False,
    "logged_open": False,
}
_BLOCK_HTTP = frozenset({403, 429, 503})


def reset_easyeda_client_state() -> None:
    """Test helper: clear rate-limit / circuit-breaker state."""
    _THROTTLE["last_mono"] = 0.0
    _THROTTLE["fails"] = 0
    _THROTTLE["open"] = False
    _THROTTLE["logged_open"] = False


def _env_float(name: str, default: float) -> float:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _sleep_for_interval() -> None:
    interval = max(0.0, _env_float("OPENHAC_EASYEDA_MIN_INTERVAL_S", 1.0))
    now = time.monotonic()
    if interval > 0 and _THROTTLE["last_mono"] > 0:
        wait = interval - (now - _THROTTLE["last_mono"])
        if wait > 0:
            time.sleep(wait)
            now = time.monotonic()
    _THROTTLE["last_mono"] = now


def _note_block_status(code: int) -> None:
    max_fail = max(1, _env_int("OPENHAC_EASYEDA_MAX_CONSECUTIVE_FAILS", 3))
    _THROTTLE["fails"] = int(_THROTTLE["fails"]) + 1
    if int(_THROTTLE["fails"]) >= max_fail and not _THROTTLE["open"]:
        _THROTTLE["open"] = True
        if not _THROTTLE["logged_open"]:
            logger.warning(
                "EasyEDA CAD HTTP %s × %s; skipping further EasyEDA fetches this process. "
                "Wait and retry, or map packages in footprint_map.json. "
                "`openhac sync` does not call EasyEDA unless --fetch-easyeda.",
                code,
                _THROTTLE["fails"],
            )
            _THROTTLE["logged_open"] = True


def _call_easyeda_cad(api, lcsc_id: str):
    """Invoke easyeda2kicad CAD fetch; record HTTP 403/429/503 even when the library swallows them."""
    http_state: dict = {"code": None}
    real_urlopen = urllib.request.urlopen

    def wrapped(*args, **kwargs):
        try:
            resp = real_urlopen(*args, **kwargs)
            code = getattr(resp, "status", None) or getattr(resp, "code", None)
            if code is not None:
                http_state["code"] = int(code)
            return resp
        except urllib.error.HTTPError as e:
            http_state["code"] = int(e.code)
            raise

    urllib.request.urlopen = wrapped  # type: ignore[assignment]
    try:
        try:
            return api.get_cad_data_of_component(lcsc_id), http_state["code"]
        except urllib.error.HTTPError as e:
            return None, int(e.code)
        except Exception:
            return None, http_state["code"]
    finally:
        urllib.request.urlopen = real_urlopen


def _easyeda_backends():
    """Import easyeda2kicad lazily so tests can stub the CAD client."""
    from easyeda2kicad.easyeda.easyeda_api import EasyedaApi
    from easyeda2kicad.kicad.export_kicad_footprint import ExporterFootprintKicad
    from easyeda2kicad.easyeda.easyeda_importer import EasyedaFootprintImporter, Easyeda3dModelImporter
    from easyeda2kicad.kicad.export_kicad_3d_model import Exporter3dModelKicad

    return EasyedaApi, ExporterFootprintKicad, EasyedaFootprintImporter, Easyeda3dModelImporter, Exporter3dModelKicad

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

def generate_footprint_from_lcsc(lcsc_id: str) -> tuple[str | None, str | None]:
    """Fetch CAD data from EasyEDA and generate a KiCad footprint.

    Args:
        lcsc_id: The LCSC part number (e.g. 'C12345').

    Returns:
        ``(footprint_id, model_3d_path)``. Either element may be None.
        Always a 2-tuple so callers can unpack; never a bare ``None``.
    """
    if not lcsc_id or not str(lcsc_id).startswith("C"):
        return None, None
    if _THROTTLE["open"]:
        return None, None
    denied = (os.environ.get("OPENHAC_NO_NETWORK") or "").strip().lower()
    if denied in ("1", "true", "yes", "on"):
        return None, None

    out_dir = get_easyeda_library_dir()
    out_3d_dir = get_easyeda_3d_library_dir()

    try:
        EasyedaApi, ExporterFootprintKicad, EasyedaFootprintImporter, Easyeda3dModelImporter, Exporter3dModelKicad = (
            _easyeda_backends()
        )
    except ImportError:
        logger.warning("easyeda2kicad is not installed. Cannot fetch footprint for %s", lcsc_id)
        return None, None

    try:
        api = EasyedaApi()
        _sleep_for_interval()
        data, http_code = _call_easyeda_cad(api, lcsc_id)
        if http_code in _BLOCK_HTTP:
            _note_block_status(int(http_code))
            logger.warning("EasyEDA CAD HTTP %s for %s", http_code, lcsc_id)
            return None, None
        if data:
            _THROTTLE["fails"] = 0
        if not data:
            logger.warning("No CAD data found on EasyEDA for %s", lcsc_id)
            return None, None

        fp = EasyedaFootprintImporter(data).get_footprint()
        if not fp or not getattr(fp, "info", None) or not fp.info.name:
            logger.warning("Failed to parse footprint from EasyEDA data for %s", lcsc_id)
            return None, None
            
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
        return f"easyeda_generated:{safe_name}", (model_3d_path or None)

    except Exception as e:
        logger.warning("Error generating EasyEDA footprint for %s: %s", lcsc_id, e)
        return None, None
