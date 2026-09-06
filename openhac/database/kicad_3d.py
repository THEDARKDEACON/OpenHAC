"""KiCad library 3D pointers for JEDEC passives (3D-002).

Do not EasyEDA-JIT a second cube when a stock ``${KICAD*_3DMODEL_DIR}`` model
exists or the footprint uses a documented library path pattern.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

_JEDEC_IMPERIAL = {
    "0201": "0603Metric",
    "0402": "1005Metric",
    "0603": "1608Metric",
    "0805": "2012Metric",
    "1206": "3216Metric",
    "1210": "3225Metric",
    "1812": "4532Metric",
    "2010": "5025Metric",
    "2512": "6332Metric",
}

_LIB_DIR_ENVS = (
    "KICAD9_3DMODEL_DIR",
    "KICAD8_3DMODEL_DIR",
    "KICAD7_3DMODEL_DIR",
    "KICAD6_3DMODEL_DIR",
    "KICAD_3DMODEL_DIR",
)

_SOIC_RE = re.compile(r"^Package_SO:(SOIC-\d+.*)$", re.I)
_SOT_RE = re.compile(r"^Package_TO_SOT_SMD:(SOT-23(?:-\d+)?)$", re.I)


def kicad_3dmodel_dir() -> str | None:
    for key in _LIB_DIR_ENVS:
        raw = (os.environ.get(key) or "").strip()
        if raw:
            return raw
    return None


def kicad_3dmodel_env_token() -> str:
    for key in _LIB_DIR_ENVS:
        if (os.environ.get(key) or "").strip():
            return "${%s}" % key
    return "${KICAD8_3DMODEL_DIR}"


def _imperial_from_footprint(fp: str) -> str | None:
    m = re.search(r"(0201|0402|0603|0805|1206|1210|1812|2010|2512)", fp)
    return m.group(1) if m else None


def library_3d_relpath_for_footprint(footprint: str | None) -> str | None:
    """Return ``Lib.3dshapes/Name.wrl`` relative to KICAD*_3DMODEL_DIR, or None."""
    fp = str(footprint or "").strip()
    if not fp or ":" not in fp:
        return None
    lib, _, name = fp.partition(":")
    lib = lib.strip()
    name = name.strip()
    if not lib or not name:
        return None

    if lib in ("Resistor_SMD", "Capacitor_SMD", "Inductor_SMD", "LED_SMD", "Diode_SMD"):
        return f"{lib}.3dshapes/{name}.wrl"
    if lib == "Crystal" or lib.startswith("Crystal"):
        return f"{lib}.3dshapes/{name}.wrl"
    if lib == "Package_SO":
        return f"Package_SO.3dshapes/{name}.wrl"
    if lib == "Package_TO_SOT_SMD":
        return f"Package_TO_SOT_SMD.3dshapes/{name}.wrl"
    if lib == "Package_DIP":
        return f"Package_DIP.3dshapes/{name}.wrl"
    imperial = _imperial_from_footprint(name)
    if imperial and lib.startswith("Resistor"):
        metric = _JEDEC_IMPERIAL[imperial]
        return f"Resistor_SMD.3dshapes/R_{imperial}_{metric}.wrl"
    return None


def library_3d_pointer_for_footprint(footprint: str | None) -> str | None:
    rel = library_3d_relpath_for_footprint(footprint)
    if not rel:
        return None
    return f"{kicad_3dmodel_env_token()}/{rel}"


def library_3d_file_exists(footprint: str | None) -> bool:
    rel = library_3d_relpath_for_footprint(footprint)
    root = kicad_3dmodel_dir()
    if not rel or not root:
        return False
    base = Path(os.path.expanduser(root))
    wrl = base / rel
    step = wrl.with_suffix(".step")
    return wrl.is_file() or step.is_file()


def is_jedec_passive_footprint(footprint: str | None) -> bool:
    fp = str(footprint or "")
    if library_3d_relpath_for_footprint(fp):
        if fp.startswith(
            (
                "Resistor_SMD:",
                "Capacitor_SMD:",
                "Inductor_SMD:",
                "LED_SMD:",
                "Diode_SMD:",
                "Package_SO:SOIC",
                "Package_TO_SOT_SMD:SOT-23",
            )
        ):
            return True
    return bool(_imperial_from_footprint(fp))


def should_skip_easyeda_3d(row: dict) -> bool:
    """True when a KiCad library 3D pointer should win over EasyEDA JIT."""
    fp = str(row.get("kicad_footprint") or "").strip()
    if not is_jedec_passive_footprint(fp):
        return False
    src = str(row.get("model_3d_source") or "").strip().lower()
    if src == "kicad_lib":
        return True
    if library_3d_file_exists(fp):
        return True
    # Stock path pattern is enough even when the KiCad 3D pack is not installed.
    return library_3d_relpath_for_footprint(fp) is not None


def library_3d_fields_for_row(row: dict) -> dict:
    fp = str(row.get("kicad_footprint") or "").strip()
    pointer = library_3d_pointer_for_footprint(fp)
    if not pointer:
        return {}
    out = {
        "model_3d_local": pointer,
        "model_3d_source": "kicad_lib",
    }
    return out
