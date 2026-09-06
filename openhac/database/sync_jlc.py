"""
Sync real in-stock JLCPCB/LCSC components from the jlcsearch API
(https://jlcsearch.tscircuit.com) into the local OpenHaC database.

No API key required. Data sourced from the jlcparts project which
mirrors the official JLCPCB component catalog.
"""

import json
import logging
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Iterable

from openhac.core.dotenv_load import load_repo_dotenv

load_repo_dotenv(quiet=True)

from openhac.version_info import user_agent

from .db_manager import DatabaseManager

logger = logging.getLogger("openhac.sync")

# Make CLI runs observable by default (without requiring app-level logging config).
if __name__ == "__main__":
    try:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )
    except Exception:
        pass

API_BASE = "https://jlcsearch.tscircuit.com"
HEADERS = {"User-Agent": user_agent(), "Accept": "application/json"}

# Each entry: category -> (endpoint_path, response_key)
# Typed jlcsearch routes. Probe-first extras (CAT-002) are listed here but
# probed at sync time; HTTP 404 / empty list is skipped, not a crash.
CATEGORY_ENDPOINTS = {
    "resistors":          ("/resistors/list.json?in_stock=true&is_basic=true",          "resistors"),
    "capacitors":         ("/capacitors/list.json?in_stock=true&is_basic=true",         "capacitors"),
    "leds":               ("/leds/list.json?in_stock=true&is_basic=true",               "leds"),
    "mosfets":            ("/mosfets/list.json?in_stock=true&is_basic=true",            "mosfets"),
    "microcontrollers":   ("/microcontrollers/list.json?in_stock=true",                 "microcontrollers"),
    "voltage_regulators": ("/voltage_regulators/list.json?in_stock=true",               "regulators"),
    "diodes":             ("/diodes/list.json?in_stock=true&is_basic=true",             "diodes"),
    "switches":           ("/switches/list.json?in_stock=true&is_basic=true",           "switches"),
    "accelerometers":     ("/accelerometers/list.json?in_stock=true",                   "accelerometers"),
    "inductors":          ("/inductors/list.json?in_stock=true&is_basic=true",          "inductors"),
    "crystals":           ("/crystals/list.json?in_stock=true&is_basic=true",           "crystals"),
    "connectors":         ("/connectors/list.json?in_stock=true",                       "connectors"),
    "fuses":              ("/fuses/list.json?in_stock=true&is_basic=true",              "fuses"),
    "beads":              ("/beads/list.json?in_stock=true&is_basic=true",              "beads"),
    "bjts":               ("/bjts/list.json?in_stock=true&is_basic=true",               "bjts"),
}

PROBE_FIRST_CATEGORIES = frozenset(
    {"inductors", "crystals", "connectors", "fuses", "beads", "bjts"}
)

PASSIVE_BASIC_CATEGORIES = frozenset(
    {
        "resistors",
        "capacitors",
        "leds",
        "diodes",
        "switches",
        "inductors",
        "crystals",
        "fuses",
        "beads",
        "mosfets",
        "bjts",
    }
)

KICAD_SYMBOL_MAP = {
    "resistors":          "Device:R",
    "capacitors":         "Device:C",
    "leds":               "Device:LED",
    "mosfets":            "Transistor_FET:BSS138",
    "microcontrollers":   "MCU_Module:Generic_MCU",
    "voltage_regulators": "Regulator_Linear:AMS1117-5.0",
    # diodes: per-item via _diode_kicad_symbol()
    "switches":           "Switch:SW_Push",
    "accelerometers":     "Sensor_Motion:Generic_Accelerometer",
    "inductors":          "Device:L",
    "crystals":           "Device:Crystal",
    "connectors":         "Connector_Generic:Conn_01x02",
    "fuses":              "Device:Fuse",
    "beads":              "Device:L",
    "bjts":               "Transistor_BJT:BC847",
}


def _format_resistance(r: float) -> str:
    if r >= 1_000_000:
        v = r / 1_000_000
        return f"{int(v)}M" if v == int(v) else f"{v}M"
    if r >= 1000:
        v = r / 1000
        if v == int(v):
            return f"{int(v)}k"
        whole = int(v)
        frac = round((v - whole) * 10)
        return f"{whole}k{frac}"
    return f"{int(r)}R"


def _format_capacitance(c: float) -> str:
    if c >= 1e-3:
        return f"{c * 1e3:.0f}mF"
    if c >= 1e-6:
        v = c * 1e6
        return f"{v:.0f}uF" if v == int(v) else f"{v:.1f}uF"
    if c >= 1e-9:
        v = c * 1e9
        return f"{v:.0f}nF" if v == int(v) else f"{v:.1f}nF"
    v = c * 1e12
    return f"{v:.0f}pF" if v == int(v) else f"{v:.1f}pF"


def _format_inductance(l: float) -> str:
    if l >= 1:
        return f"{int(l)}H" if l == int(l) else f"{l}H"
    if l >= 1e-3:
        v = l * 1e3
        return f"{int(v)}mH" if v == int(v) else f"{v:.1f}mH"
    if l >= 1e-6:
        v = l * 1e6
        return f"{int(v)}uH" if v == int(v) else f"{v:.1f}uH"
    v = l * 1e9
    return f"{int(v)}nH" if v == int(v) else f"{v:.1f}nH"


import json
import logging
import os
from pathlib import Path

logger = logging.getLogger("openhac.database.sync_jlc")

_FOOTPRINT_MAP_CACHE = None

def _load_footprint_map() -> dict:
    global _FOOTPRINT_MAP_CACHE
    if _FOOTPRINT_MAP_CACHE is not None:
        return _FOOTPRINT_MAP_CACHE
        
    map_path = Path(__file__).parent / "footprint_map.json"
    if map_path.is_file():
        try:
            with open(map_path, "r", encoding="utf-8") as f:
                _FOOTPRINT_MAP_CACHE = json.load(f)
        except Exception as e:
            logger.warning("Failed to load footprint_map.json: %s", e)
            _FOOTPRINT_MAP_CACHE = {}
    else:
        _FOOTPRINT_MAP_CACHE = {}
    return _FOOTPRINT_MAP_CACHE

def _lookup_package_map(cat_map: dict | None, pkg: str) -> str | None:
    """Exact map key, then JLC ``SMA(DO-214AC)`` / ``DO-214AC(SMA)`` aliases."""
    if not cat_map or not pkg:
        return None
    hit = cat_map.get(pkg)
    if hit:
        return hit
    base = pkg.split("(", 1)[0].strip()
    if base and base != pkg:
        hit = cat_map.get(base)
        if hit:
            return hit
    if "(" in pkg and pkg.endswith(")"):
        inner = pkg[pkg.find("(") + 1 : -1].strip()
        if inner and inner.lower() not in {"mm", "mil"} and len(inner) >= 3:
            hit = cat_map.get(inner)
            if hit:
                return hit
    return None


def _footprint_compatible_with_request(requested: str, found: str) -> bool:
    """True if *found* is *requested* or a more specific variant of that name.

    ``SOP-8`` may become ``SOP-8_3.9x4.9mm_P1.27mm``. It must not become
    ``Texas_HSOP-8-1EP_...`` or ``Fuseholder_Keystone_...``.
    """
    req = (requested or "").strip()
    got = (found or "").strip()
    if ":" in req:
        req = req.split(":", 1)[1].strip()
    if ":" in got:
        got = got.split(":", 1)[1].strip()
    if not req or not got:
        return False
    req_core = req.split("(", 1)[0].strip().lower()
    gl = got.lower()
    if gl == req_core:
        return True
    if gl.startswith(req_core) and len(gl) > len(req_core) and gl[len(req_core)] in "-_":
        return True
    return False


def _package_reflected_in_footprint(pkg: str, fp: str) -> bool:
    """Require the JLC package token to appear as a name token in the footprint id."""
    core = (pkg or "").split("(", 1)[0].strip()
    if len(core) < 2:
        return True
    needle = re.escape(core.lower().replace("_", "-"))
    hay = (fp or "").lower().replace("_", "-")
    return re.search(rf"(^|[^a-z0-9]){needle}([^a-z0-9]|$)", hay) is not None


_UNKNOWN_PACKAGE_WARNED: set[tuple[str, str]] = set()


def _warn_unknown_package(pkg: str, category: str) -> None:
    key = (category, pkg)
    if key in _UNKNOWN_PACKAGE_WARNED:
        return
    _UNKNOWN_PACKAGE_WARNED.add(key)
    logger.warning(
        "Unknown package %r for category %r, using generic fallback. "
        "Add to overlay or footprint_map.json if needed.",
        pkg,
        category,
    )


def _package_to_footprint(
    category: str,
    package: str,
    lcsc: str = "",
    *,
    extra_fields: dict | None = None,
    allow_easyeda: bool = True,
) -> str:
    pkg = package or ""
    fmap = _load_footprint_map()
    
    # 1. Check JSON map
    cat_map = fmap.get(category)
    mapped = _lookup_package_map(cat_map, pkg)
    if mapped:
        return mapped

    # Helper to attempt introspection and return if valid
    def try_resolve(candidate_fp: str) -> str | None:
        chosen, ok, res, notes = _verify_and_resolve_kicad_footprint(candidate_fp)
        if not ok or not res:
            return None
        requested_name = candidate_fp.split(":", 1)[-1]
        found_name = str(res).split(":", 1)[-1]
        if not _footprint_compatible_with_request(requested_name, found_name):
            return None
        if not _package_reflected_in_footprint(pkg, str(res)):
            return None
        logger.info(
            "Resolved %r via KiCad library scan: %s (consider adding to footprint_map.json)",
            pkg,
            res,
        )
        return res

    # 3. Try intelligent construction (which feeds into step 2: Introspection)
    candidate = None
    if category == "resistors":
        candidate = f"Resistor_SMD:R_{pkg}"
    elif category == "capacitors":
        candidate = f"Capacitor_SMD:C_{pkg}"
    elif category == "leds":
        candidate = f"LED_SMD:LED_{pkg}"
    elif category == "mosfets":
        candidate = f"Package_TO_SOT_SMD:{pkg}"
    elif category == "bjts":
        candidate = f"Package_TO_SOT_SMD:{pkg}"
    elif category == "inductors":
        candidate = f"Inductor_SMD:L_{pkg}"
    elif category == "fuses":
        candidate = f"Fuse:Fuse_{pkg}"
    elif category in ("beads", "ferrite_beads"):
        candidate = f"RF_Inductor:L_{pkg}"
    elif category == "voltage_regulators":
        candidate = f"Package_TO_SOT_SMD:{pkg}"
    elif category == "diodes":
        candidate = f"Diode_SMD:D_{pkg}"
    elif category == "crystals":
        candidate = f"Crystal:Crystal_{pkg}"
    elif category == "microcontrollers":
        if "LQFP" in pkg or "TQFP" in pkg or "QFP" in pkg:
            candidate = f"Package_QFP:{pkg}"
        elif "QFN" in pkg or "DFN" in pkg:
            candidate = f"Package_DFN_QFN:{pkg}"
        elif "SOP" in pkg or "SOIC" in pkg:
            candidate = f"Package_SO:{pkg}"
        elif "BGA" in pkg:
            candidate = f"Package_BGA:{pkg}"
    elif category == "switches":
        candidate = f"Button_Switch_SMD:SW_{pkg}"
    elif category == "accelerometers" or category in ("gyroscopes", "magnetometers", "barometers"):
        if "LGA" in pkg:
            candidate = f"Package_LGA:{pkg}"
        elif "QFN" in pkg:
            candidate = f"Package_DFN_QFN:{pkg}"
        else:
            candidate = f"Sensor:Sensor_{pkg}"
    elif category == "connectors":
        # Try to extract pin count, e.g. "1x04" or just assume a fallback based on hints
        import re
        m = re.search(r"(\d+)", pkg)
        pins = int(m.group(1)) if m else 4
        if "2.54" in pkg:
            candidate = f"Connector_PinHeader_2.54mm:PinHeader_1x{pins:02d}_P2.54mm_Vertical"
        elif "1.27" in pkg:
            candidate = f"Connector_PinHeader_1.27mm:PinHeader_1x{pins:02d}_P1.27mm_Vertical"
        elif "USB-C" in pkg or "USBC" in pkg:
            candidate = "Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12"
        else:
            candidate = f"Connector:Connector_{pkg}"
    elif category == "flash":
        if "SOIC" in pkg or "SOP" in pkg:
            candidate = f"Package_SO:{pkg}"
        elif "WSON" in pkg:
            candidate = f"Package_SON:{pkg}"
    elif category == "buck_converters":
        if "SOT" in pkg:
            candidate = f"Package_TO_SOT_SMD:{pkg}"
        elif "QFN" in pkg:
            candidate = f"Package_DFN_QFN:{pkg}"

    if candidate:
        # 2. Introspection
        res = try_resolve(candidate)
        if res:
            return res

    # 3. EasyEDA Fallback — unpack (footprint_id, model_3d_path); never store the tuple.
    # Bulk catalog sync leaves this off (allow_easyeda=False). Board enrich / prefetch keep it on.
    if allow_easyeda and lcsc:
        from openhac.database.easyeda_integration import generate_footprint_from_lcsc
        fp_id, model_path = generate_footprint_from_lcsc(lcsc)
        if fp_id:
            if extra_fields is not None and model_path:
                extra_fields["model_3d_local"] = str(model_path)
                extra_fields["model_3d_source"] = "easyeda"
                extra_fields["model_3d_license"] = "EasyEDA"
            return str(fp_id)

    # 4. Generic Fallback
    _warn_unknown_package(pkg, category)
    if category == "microcontrollers":
        return "Package_QFP:Generic_QFP"
    if category == "connectors":
        return "Connector_Generic:Conn_01x02"
    if category == "flash":
        return "Package_SO:SOIC-8"
    if category == "switches":
        return "Button_Switch_SMD:SW_Push"

    return pkg


def _diode_kicad_symbol(item: dict) -> str:
    if item.get("is_schottky"): return "Device:D_Schottky"
    if item.get("is_zener"):    return "Device:D_Zener"
    if item.get("is_tvs"):      return "Device:D_TVS"
    return "Device:D"


def _derive_generic_name(category: str, item: dict) -> str | None:
    """Return the generic_name key for an item, or None if it can't be derived."""
    try:
        if category == "resistors":
            r = float(item.get("resistance") or 0)
            pkg = item.get("package", "")
            return f"R_{_format_resistance(r)}_{pkg}"

        if category == "capacitors":
            c = float(item.get("capacitance") or 0)
            pkg = item.get("package", "")
            return f"C_{_format_capacitance(c)}_{pkg}"

        if category == "leds":
            color = (item.get("color") or "").upper()
            pkg = item.get("package", "")
            return f"LED_{color}_{pkg}"

        if category == "mosfets":
            desc = item.get("description") or ""
            ch = "P" if "P-Channel" in desc else "N"
            pkg = item.get("package", "")
            return f"MOSFET_{ch}_{pkg}"

        if category == "microcontrollers":
            import re
            mfr_clean = re.sub(r"[^\w\-]", "", (item.get("mfr") or "").replace(" ", "_"))
            lcsc = item.get("lcsc", "")
            return f"MCU_{mfr_clean}_C{lcsc}"

        if category == "voltage_regulators":
            vout = item.get("output_voltage_min")
            if vout is not None:
                v = round(float(vout), 1)
                vstr = str(int(v)) if v == int(v) else str(v)
            else:
                vstr = "ADJ"
            pkg = item.get("package", "")
            return f"LDO_{vstr}V_{pkg}"

        if category == "diodes":
            pkg = item.get("package", "")
            if item.get("is_schottky"):
                dtype = "SCH"
            elif item.get("is_zener"):
                dtype = "ZEN"
            elif item.get("is_tvs"):
                dtype = "TVS"
            else:
                dtype = "GEN"
            return f"DIODE_{dtype}_{pkg}"

        if category == "switches":
            switch_type = item.get("switch_type")
            if switch_type:
                sw = switch_type.replace(" ", "_").upper()
            else:
                sw = "TACT"
            mounting_style = item.get("mounting_style") or ""
            mounting = "SMD" if ("SMD" in mounting_style or "Surface" in mounting_style) else "THT"
            return f"SW_{sw}_{mounting}"

        if category == "accelerometers":
            axes = item.get("axes", "")
            pkg = item.get("package", "")
            return f"ACCEL_{axes}AXIS_{pkg}"

        if category == "inductors":
            lval = item.get("inductance") or item.get("value") or 0
            pkg = item.get("package", "")
            return f"L_{_format_inductance(float(lval))}_{pkg}"

        if category == "crystals":
            freq = item.get("frequency") or item.get("freq") or ""
            pkg = item.get("package", "")
            if freq:
                return f"XTAL_{freq}_{pkg}"
            lcsc = item.get("lcsc", "")
            return f"XTAL_{pkg}_C{lcsc}" if lcsc else f"XTAL_{pkg}"

        if category == "connectors":
            pkg = (item.get("package") or "CONN").replace(" ", "_")
            lcsc = item.get("lcsc", "")
            return f"CONN_{pkg}_C{lcsc}" if lcsc else f"CONN_{pkg}"

        if category == "fuses":
            pkg = item.get("package", "")
            return f"FUSE_{pkg}"

        if category == "beads":
            pkg = item.get("package", "")
            return f"BEAD_{pkg}"

        if category == "bjts":
            desc = item.get("description") or ""
            pol = "PNP" if "PNP" in desc.upper() else "NPN"
            pkg = item.get("package", "")
            return f"BJT_{pol}_{pkg}"

    except (TypeError, ValueError, KeyError):
        return None

    return None


# Maximum components to fetch per category in a single sync run.
# Set high to populate a comprehensive local database.
SYNC_LIMIT = 5000


def _strip_is_basic(endpoint_path: str) -> str:
    import re

    out = re.sub(r"[&?]is_basic=true", "", endpoint_path)
    out = out.replace("?&", "?").replace("&&", "&")
    if out.endswith("?") or out.endswith("&"):
        out = out[:-1]
    return out


def endpoint_path_for_sync(category: str, *, include_extended: bool = False) -> tuple[str, str]:
    """Return (path, response_key). CAT-003: ``include_extended`` drops ``is_basic=true``."""
    path, key = CATEGORY_ENDPOINTS[category]
    if include_extended:
        path = _strip_is_basic(path)
    return path, key


def probe_typed_category(category: str, *, opener=None) -> bool:
    """Probe ``/{cat}/list.json`` before adding (CAT-002). 404 / empty → False, no crash."""
    import urllib.error

    opener = opener or urllib.request.urlopen
    url = f"{API_BASE}/{category}/list.json?in_stock=true&limit=1"
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with opener(req, timeout=15) as resp:
            code = int(getattr(resp, "status", None) or getattr(resp, "code", 200) or 200)
            if code != 200:
                logger.warning("Skipping category %s: HTTP %s (no typed schema)", category, code)
                return False
            raw = resp.read().decode()
            data = json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        logger.warning("Skipping category %s: HTTP %s (no typed schema)", category, e.code)
        return False
    except Exception as e:
        logger.warning("Skipping category %s: %s", category, e)
        return False
    items: list = []
    if isinstance(data, dict):
        if isinstance(data.get(category), list):
            items = data[category]
        else:
            for v in data.values():
                if isinstance(v, list):
                    items = v
                    break
    elif isinstance(data, list):
        items = data
    if not items:
        logger.warning("Skipping category %s: empty list", category)
        return False
    return True


def _component_row_from_jlc_item(
    category: str,
    item: dict,
    *,
    allow_easyeda: bool = False,
) -> dict | None:
    from openhac.database.kicad_3d import library_3d_fields_for_row
    from openhac.database.pin_policy import pinout_for_sync_category

    generic_name = _derive_generic_name(category, item)
    if not generic_name:
        return None
    lcsc = item.get("lcsc", "")
    mpn = item.get("mfr") or str(lcsc)
    supplier_sku = f"C{lcsc}" if lcsc else ""
    description = item.get("description") or ""
    package = item.get("package") or ""
    if category == "diodes":
        kicad_symbol = _diode_kicad_symbol(item)
    else:
        kicad_symbol = KICAD_SYMBOL_MAP.get(category, "Device:R")
    easyeda_3d: dict = {}
    fp = _package_to_footprint(
        category, package, lcsc=supplier_sku, extra_fields=easyeda_3d, allow_easyeda=allow_easyeda
    )
    pinout = pinout_for_sync_category(category)
    row = {
        "generic_name": generic_name,
        "kicad_symbol": kicad_symbol,
        "kicad_footprint": fp,
        "manufacturer": "",
        "mpn": mpn,
        "supplier_sku": supplier_sku,
        "description": description,
        "category": category,
        "package": package,
        "catalog_tier": "warehouse",
        "pinout_source": "jlcpcb" if pinout else "",
        "attributes_json": json.dumps(
            {
                k: v
                for k, v in item.items()
                if k not in ("lcsc", "mfr", "description", "package", "stock")
            }
        ),
    }
    if pinout:
        row["pinout_json"] = json.dumps(pinout)
    row.update(library_3d_fields_for_row(row))
    if easyeda_3d and not row.get("model_3d_local"):
        row.update(easyeda_3d)
    return row


def _fetch_category(endpoint_path: str, response_key: str, limit: int = SYNC_LIMIT) -> list[dict]:
    """Fetch up to limit in-stock components from a typed endpoint."""
    sep = "&" if "?" in endpoint_path else "?"
    url = API_BASE + endpoint_path + f"{sep}limit={limit}"
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode())
    return data.get(response_key, [])


def _fetch_all_pages(endpoint_path: str, response_key: str, max_items: int = 10000) -> list[dict]:
    """Fetch all available components with pagination support.

    Some JLC API endpoints support offset/limit pagination.
    This fetches until no more items or max_items reached.
    """
    all_items = []
    offset = 0
    page_size = 1000

    while len(all_items) < max_items:
        sep = "&" if "?" in endpoint_path else "?"
        url = API_BASE + endpoint_path + f"{sep}limit={page_size}&offset={offset}"
        req = urllib.request.Request(url, headers=HEADERS)

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode())
                items = data.get(response_key, [])
        except Exception:
            break

        if not items:
            break

        all_items.extend(items)
        offset += len(items)

        if len(items) < page_size:
            break

    return all_items[:max_items]


def sync_catalog(
    categories: list[str] = None,
    verbose: bool = True,
    *,
    include_extended: bool = False,
    max_per_category: int | None = None,
    fetch_easyeda: bool = False,
) -> int:
    """Sync real in-stock JLCPCB parts from jlcsearch API into the local database.

    Args:
        categories: list of category names to sync, or None for all
        verbose: print progress
        include_extended: CAT-003 — drop ``is_basic=true`` (default stays Basic)
        max_per_category: cap inserts/fetches per typed category
        fetch_easyeda: if True, EasyEDA CAD for unmapped packages (rate-limited).
            Default False so bulk sync does not hammer easyeda.com.

    Returns:
        number of new components inserted
    """
    targets = categories if categories is not None else list(CATEGORY_ENDPOINTS.keys())
    db = DatabaseManager()
    total_inserted = 0
    any_success = False
    fetch_attempted = False
    limit = int(max_per_category or SYNC_LIMIT)

    for category in targets:
        if category not in CATEGORY_ENDPOINTS:
            if verbose:
                logger.warning(f"Unknown category '{category}', skipping.")
            continue

        if category in PROBE_FIRST_CATEGORIES:
            if not probe_typed_category(category):
                continue

        if verbose:
            logger.info(f"Fetching {category}...")

        endpoint_path, response_key = endpoint_path_for_sync(
            category, include_extended=include_extended
        )
        fetch_attempted = True

        try:
            items = _fetch_category(endpoint_path, response_key, limit=limit)
        except Exception as e:
            if verbose:
                logger.warning(f"Failed to fetch {category}: {e}")
            continue

        if not items:
            if verbose:
                logger.warning(f"No items returned for {category}, skipping.")
            continue

        any_success = True
        items.sort(key=lambda x: int(x.get("stock") or 0), reverse=True)
        items = items[:limit]

        inserted = 0
        for item in items:
            component = _component_row_from_jlc_item(
                category, item, allow_easyeda=fetch_easyeda
            )
            if not component:
                continue
            row_id = db.insert_component(component, ignore_duplicate=True)
            if row_id:
                inserted += 1

        total_inserted += inserted
        if verbose:
            logger.info(f"Inserted {inserted} new components from {category}")

    if not any_success and fetch_attempted:
        raise RuntimeError(
            "All category fetches failed. Check your network connection or the "
            "jlcsearch API at https://jlcsearch.tscircuit.com."
        )

    if verbose:
        logger.info(f"Sync complete. {total_inserted} new components inserted.")

    return total_inserted


def search_and_add_components(queries: list[str], verbose: bool = True) -> int:
    """Search for specific components by keyword and add them to the database.

    Args:
        queries: List of search terms (MPN, SKU, or keywords like "STM32F405")
        verbose: Print progress

    Returns:
        Number of components added
    """
    db = DatabaseManager()
    total_inserted = 0

    for query in queries:
        if verbose:
            logger.info(f"Searching for: {query}")

        try:
            # Use the search endpoint
            sep = "&" if "?" in "/search" else "?"
            url = API_BASE + f"/search{sep}q={urllib.parse.quote(query)}&limit=10"
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
                items = data.get("results", data.get("items", []))
        except Exception as e:
            if verbose:
                logger.warning(f"Search failed for '{query}': {e}")
            continue

        inserted = 0
        for item in items:
            lcsc = item.get("lcsc", "")
            if not lcsc:
                continue

            # Determine category from item data
            category = item.get("category", "unknown")
            generic_name = item.get("generic_name") or _derive_generic_name(category, item) or lcsc

            kicad_footprint = item.get("kicad_footprint", "")
            if not kicad_footprint:
                kicad_footprint = _package_to_footprint(
                    category, item.get("package", ""), lcsc=lcsc, allow_easyeda=False
                )

            component = {
                "generic_name": generic_name,
                "kicad_symbol": item.get("kicad_symbol", "Device:R"),
                "kicad_footprint": kicad_footprint,
                "manufacturer": item.get("mfr", ""),
                "mpn": item.get("mfr_part", ""),
                "supplier_sku": lcsc,
                "description": item.get("description", ""),
                "category": category,
                "package": item.get("package", ""),
                "stock": item.get("stock", 0),
                "jlc_class": item.get("class", "Extended"),
                "attributes_json": json.dumps({
                    k: v for k, v in item.items()
                    if k not in ("lcsc", "mfr", "description", "package", "stock")
                }),
            }

            row_id = db.insert_component(component, ignore_duplicate=True)
            if row_id:
                inserted += 1

        if verbose and inserted:
            logger.info(f"Added {inserted} components for '{query}'")
        total_inserted += inserted

    if verbose:
        logger.info(f"Search sync complete. {total_inserted} components added.")
    return total_inserted


def _read_json_file(path: str) -> object:
    p = Path(path)
    return json.loads(p.read_text(encoding="utf-8"))


def _normalize_jlc_sku(s: str) -> str:
    raw = (s or "").strip()
    if not raw:
        return ""
    up = raw.upper()
    if up.startswith("C") and up[1:].isdigit():
        return f"C{up[1:]}"
    if up.isdigit():
        return f"C{up}"
    return raw


def _verify_and_resolve_kicad_footprint(fp: str) -> tuple[str, int, str, str]:
    """Return (chosen_fp, verified, resolved_fp, notes) for KiCad footprint IDs."""
    import os
    from functools import lru_cache

    from openhac.compiler.pcb_placement import (
        footprint_search_roots,
        parse_footprint_id,
        resolve_pretty_directory,
    )

    raw = (fp or "").strip()
    if not raw:
        return ("", 0, "", "empty footprint")

    fpid = parse_footprint_id(raw)
    if fpid is None:
        return (raw, 0, "", "footprint is not in 'Library:Name' form")
    lib, name = fpid

    def _normalize_name_variants(n: str) -> list[str]:
        """Common KiCad naming variations: hyphen/underscore, mm tokens, pitch casing."""
        base = (n or "").strip()
        if not base:
            return []
        outs = {base}
        outs.add(base.replace("-", "_"))
        outs.add(base.replace("_", "-"))
        outs.add(base.replace("mm", "").replace("MM", ""))
        outs.add(base.replace("_P", "_p").replace("-P", "-p"))
        outs.add(base.replace("P0.", "p0.").replace("P1.", "p1."))
        # Some libs use "x" vs "X" or omit separators.
        outs.add(base.replace("x", "X"))
        outs.add(base.replace("X", "x"))
        return [s for s in dict.fromkeys(outs) if s]

    def _best_fuzzy_match_in_lib(lib_name: str, *, must_contain: list[str]) -> str | None:
        """Return a footprint name in lib that contains all substrings (case-insensitive)."""
        pretty = resolve_pretty_directory(lib_name)
        if not pretty:
            return None
        try:
            files = os.listdir(pretty)
        except Exception:
            return None
        needles = [s.lower() for s in must_contain if s]
        for fn in files:
            if not fn.endswith(".kicad_mod"):
                continue
            base = fn[: -len(".kicad_mod")]
            low = base.lower()
            if all(n in low for n in needles):
                return base
        return None

    def _best_variant_in_lib(lib_name: str, requested: str) -> str | None:
        """Same-library footprint whose name is *requested* or a more specific variant."""
        pretty = resolve_pretty_directory(lib_name)
        if not pretty or not requested:
            return None
        try:
            files = os.listdir(pretty)
        except Exception:
            return None
        core = requested.split("(", 1)[0].strip()
        inner = ""
        if "(" in requested and requested.endswith(")"):
            inner = requested[requested.find("(") + 1 : -1].strip().lower()
        hits: list[str] = []
        for fn in files:
            if not fn.endswith(".kicad_mod"):
                continue
            base = fn[: -len(".kicad_mod")]
            if _footprint_compatible_with_request(core, base):
                hits.append(base)
        if not hits:
            return None
        if inner and "x" in inner:
            dim_hits = [h for h in hits if inner in h.lower().replace("_", "")]
            if dim_hits:
                hits = dim_hits
        hits.sort(key=lambda s: (len(s), s))
        return hits[0]

    def _dim_tokens(n: str) -> list[str]:
        """Extract useful dimension tokens like '3x2.5' and 'p0.4' from a footprint name."""
        low = (n or "").lower()
        out: list[str] = []
        # pitch
        for tok in ("p0.4", "p0.5", "p1.27", "p0.8", "p0.65", "p0.35"):
            if tok in low or tok.replace(".", "_") in low:
                out.append(tok)
        # common 'AxB' dimensions with either x or _x_
        import re
        m = re.search(r"(\d+(?:\.\d+)?)\s*[x_]\s*(\d+(?:\.\d+)?)", low)
        if m:
            a, b = m.group(1), m.group(2)
            out.append(f"{a}x{b}")
            # alternate formatting often used in KiCad libs
            out.append(f"{a}.0x{b}" if "." not in a else f"{a}x{b}")
            out.append(f"{a}x{b}.0" if "." not in b else f"{a}x{b}")
        return [t for t in out if t]

    def _exists_in(lib_name: str) -> bool:
        pretty = resolve_pretty_directory(lib_name)
        if not pretty:
            return False
        for cand in _normalize_name_variants(name):
            if os.path.isfile(os.path.join(pretty, f"{cand}.kicad_mod")):
                return True
        return False

    if _exists_in(lib):
        # Prefer exact spelling when possible.
        pretty = resolve_pretty_directory(lib)
        if pretty and os.path.isfile(os.path.join(pretty, f"{name}.kicad_mod")):
            return (raw, 1, raw, "")
        for cand in _normalize_name_variants(name):
            if pretty and os.path.isfile(os.path.join(pretty, f"{cand}.kicad_mod")):
                resolved = f"{lib}:{cand}"
                return (resolved, 1, resolved, f"normalized from {raw} -> {resolved}")
        return (raw, 1, raw, "")

    # Curated heuristic: VSON/SON footprints often live under Package_SON in KiCad.
    if "vson" in name.lower() and lib != "Package_SON":
        if _exists_in("Package_SON"):
            pretty = resolve_pretty_directory("Package_SON")
            if pretty:
                for cand in [name] + _normalize_name_variants(name):
                    if os.path.isfile(os.path.join(pretty, f"{cand}.kicad_mod")):
                        resolved = f"Package_SON:{cand}"
                        return (resolved, 1, resolved, f"moved library from {lib} -> Package_SON")
        # If not exact, try fuzzy in Package_SON.
        hit = _best_fuzzy_match_in_lib("Package_SON", must_contain=["vson", "10", "p0.5"])
        if hit:
            resolved = f"Package_SON:{hit}"
            return (resolved, 1, resolved, f"fuzzy resolved {raw} -> {resolved}")

    # Curated heuristic: inductors sometimes differ by metric code vs dimensions.
    if lib == "Inductor_SMD" and any(x in name for x in ("2.5x2.0", "2.5X2.0", "2_5x2_0")):
        hit = _best_fuzzy_match_in_lib("Inductor_SMD", must_contain=["2520"])
        if hit:
            resolved = f"Inductor_SMD:{hit}"
            return (resolved, 1, resolved, f"fuzzy resolved {raw} -> {resolved}")

    # Same-library variant: SOP-8 → SOP-8_3.9x..., Fuse_1812 → Fuse_1812_4532Metric.
    # Do not accept unrelated names that only share a substring (Fuse → Fuseholder).
    hit = _best_variant_in_lib(lib, name)
    if hit:
        resolved = f"{lib}:{hit}"
        return (resolved, 1, resolved, f"variant resolved {raw} -> {resolved}")

    # Package_LGA special-case: footprints often encode dims/pitch slightly differently.
    if lib == "Package_LGA":
        prefix = name.split("_", 1)[0].strip()
        must = []
        # e.g. "LGA-14"
        if prefix:
            must.append(prefix)
        must.extend(_dim_tokens(name))
        # If we have at least 2 tokens, try a targeted fuzzy search.
        if len(must) >= 2:
            hit = _best_fuzzy_match_in_lib("Package_LGA", must_contain=must[:4])
            if hit and _footprint_compatible_with_request(prefix.split("(", 1)[0], hit):
                resolved = f"Package_LGA:{hit}"
                return (resolved, 1, resolved, f"fuzzy resolved {raw} -> {resolved}")
        # If pitch is missing from local KiCad, fall back to the closest common pitch variant.
        # Example: some parts specify P0.4 but KiCad library only has P0.5.
        if "p0.4" in name.lower():
            hit = _best_fuzzy_match_in_lib("Package_LGA", must_contain=[prefix or "lga-14", "3x2.5", "p0.5"])
            if hit:
                resolved = f"Package_LGA:{hit}"
                return (resolved, 1, resolved, f"pitch fallback resolved {raw} -> {resolved}")

    @lru_cache(maxsize=64)
    def _libs_containing(name0: str) -> list[str]:
        libs: list[str] = []
        for root in footprint_search_roots():
            try:
                kids = os.listdir(root)
            except Exception:
                continue
            for d in kids:
                if not d.endswith(".pretty"):
                    continue
                lib_name = d[: -len(".pretty")]
                for cand in _normalize_name_variants(name0):
                    if os.path.isfile(os.path.join(root, d, f"{cand}.kicad_mod")):
                        libs.append(lib_name)
                        break
        return libs

    # Try exact + normalized variants across all libs.
    libs = _libs_containing(name)
    if len(libs) == 1:
        # Choose the first matching candidate spelling we can find in that lib.
        chosen_lib = libs[0]
        pretty = resolve_pretty_directory(chosen_lib)
        if pretty:
            for cand in [name] + _normalize_name_variants(name):
                if os.path.isfile(os.path.join(pretty, f"{cand}.kicad_mod")):
                    resolved = f"{chosen_lib}:{cand}"
                    return (resolved, 1, resolved, f"resolved from {raw} -> {resolved}")
        resolved = f"{chosen_lib}:{name}"
        return (resolved, 1, resolved, f"resolved from {raw} -> {resolved}")
    if len(libs) > 1:
        return (
            raw,
            0,
            f"{libs[0]}:{name}",
            f"ambiguous footprint name {name!r} found in multiple libs: {', '.join(sorted(libs))}",
        )
    return (raw, 0, "", f"footprint not found locally: {raw}")


def verify_footprints_in_db(*, apply_fixes: bool = True, limit: int = 0, verbose: bool = True) -> dict:
    """Scan DB components and verify/resolve kicad_footprint entries."""
    import sqlite3

    db = DatabaseManager()
    rows: list[dict] = []
    with sqlite3.connect(db.db_path) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        q = "SELECT generic_name, kicad_footprint, supplier_sku FROM components WHERE kicad_footprint IS NOT NULL AND TRIM(kicad_footprint) != ''"
        if limit and limit > 0:
            q += " LIMIT ?"
            cur.execute(q, (int(limit),))
        else:
            cur.execute(q)
        rows = [dict(r) for r in cur.fetchall()]

    verified = 0
    resolved = 0
    missing = 0
    ambiguous = 0
    updated = 0

    for r in rows:
        gn = str(r.get("generic_name") or "").strip()
        fp = str(r.get("kicad_footprint") or "").strip()
        lcsc = str(r.get("supplier_sku") or "").strip()
        chosen, ok, res, notes = _verify_and_resolve_kicad_footprint(fp)
        if not ok and lcsc:
            from openhac.database.easyeda_integration import generate_footprint_from_lcsc
            e_fp, e_3d = generate_footprint_from_lcsc(lcsc)
            if e_fp:
                chosen = e_fp
                ok = 1
                res = e_fp
                notes = "Generated via easyeda2kicad"
                if e_3d:
                    try:
                        db.update_component_fields(
                            gn,
                            {
                                "model_3d_local": str(e_3d),
                                "model_3d_source": "easyeda",
                                "model_3d_license": "EasyEDA",
                            },
                        )
                    except Exception:
                        pass
        
        if ok:
            verified += 1
        else:
            if "ambiguous" in (notes or ""):
                ambiguous += 1
            else:
                missing += 1
        if res and res != fp:
            resolved += 1
        if apply_fixes:
            updates = {
                "kicad_footprint": chosen or fp,
                "footprint_verified": int(ok),
                "footprint_resolved": str(res or ""),
                "footprint_notes": str(notes or ""),
            }
            try:
                if db.update_component_fields(gn, updates):
                    updated += 1
            except Exception:
                pass

    if verbose:
        logger.info(
            "Footprint verification: scanned=%s verified=%s missing=%s ambiguous=%s resolved=%s updated=%s",
            len(rows),
            verified,
            missing,
            ambiguous,
            resolved,
            updated,
        )
    return {
        "scanned": len(rows),
        "verified": verified,
        "missing": missing,
        "ambiguous": ambiguous,
        "resolved": resolved,
        "updated": updated,
    }


def seed_from_file(seed_file: str, verbose: bool = True) -> int:
    """Seed/insert components from a user-provided JSON file (no hardcoded parts shipped)."""
    db = DatabaseManager()
    data = _read_json_file(seed_file)
    if not isinstance(data, list):
        raise ValueError("seed file must be a JSON list of component dicts")
    inserted = 0
    for row in data:
        if not isinstance(row, dict):
            continue
        row = dict(row)
        gn = str(row.get("generic_name") or "").strip()
        if not gn:
            continue
        row["generic_name"] = gn
        if not str(row.get("mpn") or "").strip():
            row["mpn"] = gn
        if not str(row.get("kicad_symbol") or "").strip():
            row["kicad_symbol"] = "Device:R"
        if row.get("kicad_footprint") is None:
            row["kicad_footprint"] = ""
        if "supplier_sku" in row:
            row["supplier_sku"] = _normalize_jlc_sku(str(row["supplier_sku"]))
        # Allow user files to provide richer pin metadata without requiring schema changes.
        # - `pinout`: list of {num,name,type} → stored into pinout_json
        # - `symbol_data`: dict or JSON → stored as JSON string
        if "pinout" in row and "pinout_json" not in row:
            try:
                row["pinout_json"] = json.dumps(row.pop("pinout"))
            except Exception:
                pass
        if "symbol_data" in row and not isinstance(row["symbol_data"], str):
            try:
                row["symbol_data"] = json.dumps(row["symbol_data"])
            except Exception:
                pass
        if "kicad_footprint" in row:
            chosen, verified, resolved, notes = _verify_and_resolve_kicad_footprint(str(row.get("kicad_footprint") or ""))
            row["kicad_footprint"] = chosen
            row["footprint_verified"] = int(verified)
            row["footprint_resolved"] = str(resolved or "")
            row["footprint_notes"] = str(notes or "")
        row_id = db.insert_component(row, ignore_duplicate=True)
        if row_id:
            inserted += 1
        elif verbose:
            logger.warning(
                "Seed skipped %s (already present, or a NOT NULL catalog field was missing)",
                gn,
            )
    if verbose:
        logger.info("Seed complete. %s component(s) inserted.", inserted)
    return inserted


def sync_all_jlcpcb(max_per_category: int = 10000, verbose: bool = True) -> int:
    """Comprehensive sync - fetch thousands of components from all working JLCPCB endpoints.

    This populates the database with real JLCPCB parts for offline use.
    Uses pagination to fetch up to max_per_category per endpoint.

    Args:
        max_per_category: Maximum items to fetch per category (default 10000)
        verbose: Print progress

    Returns:
        Total number of components inserted
    """
    db = DatabaseManager()
    total_inserted = 0

    for category, (endpoint_path, response_key) in CATEGORY_ENDPOINTS.items():
        if verbose:
            logger.info(f"Fetching {category} (up to {max_per_category})...")

        try:
            items = _fetch_all_pages(endpoint_path, response_key, max_per_category)
        except Exception as e:
            if verbose:
                logger.warning(f"Failed to fetch {category}: {e}")
            continue

        if not items:
            if verbose:
                logger.warning(f"No items returned for {category}, skipping.")
            continue

        # Sort by stock descending
        items.sort(key=lambda x: int(x.get("stock") or 0), reverse=True)

        inserted = 0
        for item in items:
            generic_name = _derive_generic_name(category, item)
            if not generic_name:
                continue

            lcsc = item.get("lcsc", "")
            mpn = item.get("mfr") or str(lcsc)
            supplier_sku = f"C{lcsc}" if lcsc else ""
            description = item.get("description") or ""
            package = item.get("package") or ""

            if category == "diodes":
                kicad_symbol = _diode_kicad_symbol(item)
            else:
                kicad_symbol = KICAD_SYMBOL_MAP.get(category, "Device:R")

            component = {
                "generic_name": generic_name,
                "kicad_symbol": kicad_symbol,
                "kicad_footprint": _package_to_footprint(category, package),
                "manufacturer": "",
                "mpn": mpn,
                "supplier_sku": supplier_sku,
                "description": description,
                "category": category,
                "attributes_json": json.dumps({
                    k: v for k, v in item.items()
                    if k not in ("lcsc", "mfr", "description", "package", "stock")
                }),
            }

            row_id = db.insert_component(component, ignore_duplicate=True)
            if row_id:
                inserted += 1

        total_inserted += inserted
        if verbose:
            logger.info(f"Inserted {inserted} new components from {category} (fetched {len(items)} total)")

    if verbose:
        logger.info(f"Full sync complete. {total_inserted} new components inserted from JLCPCB.")

    return total_inserted


def sync_by_sku(skus: list[tuple[str, str]], verbose: bool = True) -> int:
    """Sync specific components by JLCPCB SKU with hybrid API enrichment.
    
    Args:
        skus: List of (generic_name, jlcpcb_sku) tuples
        verbose: Print progress
        
    Returns:
        Number of components successfully synced
    """
    from openhac.database.vendor_apis import lookup_part_live
    
    db = DatabaseManager()
    success_count = 0
    
    for generic_name, jlcpcb_sku in skus:
        if verbose:
            logger.info(f"Syncing {generic_name} (SKU: {jlcpcb_sku})...")
        
        # Check if already has pinout
        existing = db.get_component(generic_name)
        if existing and existing.get("pinout_json"):
            if verbose:
                logger.info(f"  {generic_name} already has pinout, skipping")
            success_count += 1
            continue
        
        # Use hybrid API lookup
        try:
            # Extract MPN from SKU if needed
            mpn = jlcpcb_sku  # Will be resolved by lookup_part_live
            
            part_info = lookup_part_live(
                mpn, 
                preferred_vendor="auto",
                jlcpcb_sku=jlcpcb_sku
            )
            
            if not part_info:
                logger.warning(f"  {generic_name}: Not found in vendor APIs")
                continue
            
            if verbose:
                logger.info(f"  Found: {part_info.mpn} by {part_info.manufacturer}")
                logger.info(f"  Pinout: {part_info.pinout and len(part_info.pinout)} pins")
                logger.info(f"  Dimensions: {part_info.package_dimensions}")

            # Pinout quality check: JLC-only pinCount-derived pinouts are not named.
            # CAT-004: hard skip — do not store numeric-only IC pinouts.
            try:
                from openhac.database.pin_policy import should_store_vendor_pinout

                cat = (part_info.category or (existing or {}).get("category") or "").strip()
                if part_info.pinout and not should_store_vendor_pinout(
                    part_info.pinout, category=cat, generic_name=generic_name
                ):
                    if verbose:
                        logger.warning(
                            "  %s: CAT-004 hard-skip numeric-only pinout (not stored).",
                            generic_name,
                        )
                    part_info.pinout = None
            except Exception:
                pass
            
            # Update or insert component
            if existing:
                db.update_component_from_vendor(generic_name, part_info)
            else:
                # Create new component from vendor data
                cat = (part_info.category or "").strip()
                kicad_symbol = "Device:Q"
                if cat:
                    kicad_symbol = KICAD_SYMBOL_MAP.get(cat, KICAD_SYMBOL_MAP.get(cat.lower(), kicad_symbol))
                component = {
                    "generic_name": generic_name,
                    "kicad_symbol": kicad_symbol,
                    "kicad_footprint": part_info.package or "",
                    "manufacturer": part_info.manufacturer,
                    "mpn": part_info.mpn,
                    "supplier_sku": _normalize_jlc_sku(part_info.supplier_sku),
                    "description": part_info.description,
                    "category": cat,
                    "pinout_json": json.dumps(part_info.pinout) if part_info.pinout else None,
                    "thermal_json": json.dumps(part_info.thermal_data) if part_info.thermal_data else None,
                    "package_length_mm": part_info.package_dimensions.get("length") if part_info.package_dimensions else None,
                    "package_width_mm": part_info.package_dimensions.get("width") if part_info.package_dimensions else None,
                    "package_height_mm": part_info.package_dimensions.get("height") if part_info.package_dimensions else None,
                    "lifecycle_status": part_info.lifecycle_status,
                    "compliance_flags": ",".join(part_info.compliance_flags) if part_info.compliance_flags else None,
                    "lead_time_days": part_info.lead_time_days,
                    "attributes_json": json.dumps({
                        "datasheet_url": part_info.datasheet_url,
                        "product_url": part_info.product_url,
                        "rohs": part_info.rohs,
                    }),
                }
                try:
                    chosen, verified, resolved, notes = _verify_and_resolve_kicad_footprint(str(component.get("kicad_footprint") or ""))
                    component["kicad_footprint"] = chosen
                    component["footprint_verified"] = int(verified)
                    component["footprint_resolved"] = str(resolved or "")
                    component["footprint_notes"] = str(notes or "")
                except Exception:
                    pass
                db.insert_component(component)
            
            if verbose:
                logger.info(f"  Synced {generic_name}")
            success_count += 1
            
        except Exception as e:
            logger.error(f"  Error syncing {generic_name}: {e}")
    
    if verbose:
        logger.info(f"\nSync complete: {success_count}/{len(skus)} components")
    
    return success_count


def _load_skus_file(path: str) -> list[tuple[str, str]]:
    data = _read_json_file(path)
    if not isinstance(data, list):
        raise ValueError("skus file must be a JSON list (either [ [generic, sku], ... ] or objects)")
    out: list[tuple[str, str]] = []
    for item in data:
        if isinstance(item, (list, tuple)) and len(item) == 2:
            out.append((str(item[0]).strip(), _normalize_jlc_sku(str(item[1]))))
        elif isinstance(item, dict):
            gn = str(item.get("generic_name") or item.get("name") or "").strip()
            sku = _normalize_jlc_sku(str(item.get("sku") or item.get("supplier_sku") or item.get("lcsc") or ""))
            if gn and sku:
                out.append((gn, sku))
    return out


def _build_arg_parser():
    import argparse

    p = argparse.ArgumentParser(prog="python -m openhac.database.sync_jlc")
    p.add_argument("--full", action="store_true", help="Full sync: fetch many parts from working endpoints.")
    p.add_argument("--seed", action="store_true", help="Deprecated. Use --seed-file PATH.")
    p.add_argument("--seed-file", type=str, default="", help="Seed from user JSON file (list of component dicts).")
    p.add_argument("--skus", action="store_true", help="Deprecated. Use --skus-file PATH.")
    p.add_argument("--skus-file", type=str, default="", help="Sync/enrich by SKU from user JSON file.")
    p.add_argument("--verify-footprints", action="store_true", help="Verify/resolve all DB footprints against local KiCad libs.")
    p.add_argument("--verify-footprints-limit", type=int, default=0, help="Optional LIMIT for --verify-footprints.")
    p.add_argument("--verbose", action="store_true", help="Enable verbose progress logging.")
    p.add_argument("--quiet", action="store_true", help="Reduce output (warnings/errors only).")
    p.add_argument("--max-per-category", type=int, default=10000, help="Full sync max per category.")
    return p


if __name__ == "__main__":
    args = _build_arg_parser().parse_args()
    if getattr(args, "quiet", False):
        logging.getLogger().setLevel(logging.WARNING)
    elif getattr(args, "verbose", False):
        logging.getLogger().setLevel(logging.INFO)

    # Show which vendor API keys are configured
    if not getattr(args, "quiet", False):
        print("\nAPI Keys configured:")
        print(f"  DIGIKEY_CLIENT_ID: {bool(os.environ.get('DIGIKEY_CLIENT_ID'))}")
        print(f"  MOUSER_API_KEY: {bool(os.environ.get('MOUSER_API_KEY'))}")
        print(f"  TME_API_TOKEN: {bool(os.environ.get('TME_API_TOKEN'))}")
        print(f"  JLCPCB_API_KEY: {bool(os.environ.get('JLCPCB_API_KEY'))}")
        print()

    if args.full:
        logger.info("Starting full sync (max_per_category=%s).", int(args.max_per_category))
        sync_all_jlcpcb(max_per_category=int(args.max_per_category), verbose=not getattr(args, "quiet", False))
        raise SystemExit(0)

    if args.seed:
        raise SystemExit("`--seed` is deprecated. Provide `--seed-file PATH` (no hardcoded parts).")
    if args.skus:
        raise SystemExit("`--skus` is deprecated. Provide `--skus-file PATH` (no hardcoded parts).")

    if getattr(args, "verify_footprints", False):
        logger.info("Verifying DB footprints against local KiCad libs...")
        verify_footprints_in_db(apply_fixes=True, limit=int(getattr(args, "verify_footprints_limit", 0) or 0))
        raise SystemExit(0)

    if args.seed_file:
        logger.info("Seeding from file: %s", args.seed_file)
        seed_from_file(args.seed_file, verbose=not getattr(args, "quiet", False))
        raise SystemExit(0)

    if args.skus_file:
        logger.info("Syncing/enriching by SKU file: %s", args.skus_file)
        sync_by_sku(_load_skus_file(args.skus_file), verbose=not getattr(args, "quiet", False))
        raise SystemExit(0)

    logger.info("Starting catalog sync (default categories).")
    n = sync_catalog(verbose=not getattr(args, "quiet", False))
    logger.info("Catalog sync done. inserted=%s", n)
