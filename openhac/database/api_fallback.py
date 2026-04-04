"""
JIT (Just-In-Time) API Fallback Engine.

When a parametric search misses locally, this module queries the live
jlcsearch API, maps the raw response to KiCad-compatible footprints
and symbols, and caches the result in the SQLite database so subsequent
lookups are instant.
"""

import json
import re
import urllib.parse
import urllib.request
import warnings

API_BASE = "https://jlcsearch.tscircuit.com"
HEADERS = {"User-Agent": "OpenHaC/2.0", "Accept": "application/json"}
TIMEOUT_SECONDS = 5


class OfflineCompilationError(EnvironmentError):
    """Raised when the network is unavailable and local fallback is exhausted."""


# -----------------------------------------------------------------------
# KiCad footprint translation dictionary
# -----------------------------------------------------------------------

_FOOTPRINT_MAP = {
    "resistors": {
        "0201": "Resistor_SMD:R_0201_0603Metric",
        "0402": "Resistor_SMD:R_0402_1005Metric",
        "0603": "Resistor_SMD:R_0603_1608Metric",
        "0805": "Resistor_SMD:R_0805_2012Metric",
        "1206": "Resistor_SMD:R_1206_3216Metric",
        "1210": "Resistor_SMD:R_1210_3225Metric",
        "2010": "Resistor_SMD:R_2010_5025Metric",
        "2512": "Resistor_SMD:R_2512_6332Metric",
    },
    "capacitors": {
        "0201": "Capacitor_SMD:C_0201_0603Metric",
        "0402": "Capacitor_SMD:C_0402_1005Metric",
        "0603": "Capacitor_SMD:C_0603_1608Metric",
        "0805": "Capacitor_SMD:C_0805_2012Metric",
        "1206": "Capacitor_SMD:C_1206_3216Metric",
        "1210": "Capacitor_SMD:C_1210_3225Metric",
    },
    "leds": {
        "0402": "LED_SMD:LED_0402_1005Metric",
        "0603": "LED_SMD:LED_0603_1608Metric",
        "0805": "LED_SMD:LED_0805_2012Metric",
        "1206": "LED_SMD:LED_1206_3216Metric",
    },
    "voltage_regulators": {
        "SOT-223": "Package_TO_SOT_SMD:SOT-223-3_TabPin2",
        "SOT-23": "Package_TO_SOT_SMD:SOT-23",
        "TO-252": "Package_TO_SOT_SMD:TO-252-2",
        "TO-263": "Package_TO_SOT_SMD:TO-263-3_TabPin2",
        "TO-220": "Package_TO_SOT_THT:TO-220-3_Horizontal_TabDown",
    },
    "mosfets": {
        "SOT-23": "Package_TO_SOT_SMD:SOT-23",
        "SOT-23-3": "Package_TO_SOT_SMD:SOT-23",
        "SOT-23-6": "Package_TO_SOT_SMD:SOT-23-6_Handsoldering",
        "SOT-223": "Package_TO_SOT_SMD:SOT-223-3_TabPin2",
        "TO-252": "Package_TO_SOT_SMD:TO-252-2",
    },
    "diodes": {
        "SOD-123": "Diode_SMD:D_SOD-123",
        "SOD-323": "Diode_SMD:D_SOD-323",
        "SOD-523": "Diode_SMD:D_SOD-523",
        "SOT-23": "Diode_SMD:D_SOT-23",
        "SMA": "Diode_SMD:D_SMA",
        "SMB": "Diode_SMD:D_SMB",
    },
    "connectors": {
        "USB-C": "Connector_USB:USB_C_Receptacle_USB2.0_16P",
    },
    "accelerometers": {
        "LGA-14": "Package_LGA:LGA-14_3x5mm_P0.8mm",
        "LGA-16": "Package_LGA:LGA-16_3x3mm_P0.5mm",
    },
}

# Category → default KiCad symbol
_SYMBOL_MAP = {
    "resistors": "Device:R",
    "capacitors": "Device:C",
    "leds": "Device:LED",
    "mosfets": "Device:Q_NMOS_GDS",
    "voltage_regulators": "Regulator_Linear:AMS1117-3.3",
    "diodes": "Device:D",
    "connectors": "Connector_Generic:Conn_01x02",
    "microcontrollers": "MCU_ST_STM32:STM32F407VETx",
    "accelerometers": "Sensor:BMI160",
}


def _resolve_footprint(category: str, package: str) -> str:
    """Map raw package string to KiCad footprint."""
    cat_map = _FOOTPRINT_MAP.get(category, {})
    if package in cat_map:
        return cat_map[package]
    # Fuzzy: try stripping whitespace / case
    pkg_clean = package.strip().upper() if package else ""
    for key, val in cat_map.items():
        if key.upper() == pkg_clean:
            return val
    # Generic fallback
    if package:
        return f"Package_TO_SOT_SMD:{package}"
    return "Package_TO_SOT_SMD:SOT-23"


def _resolve_symbol(category: str, description: str = "") -> str:
    """Pick the best KiCad symbol for a given category."""
    return _SYMBOL_MAP.get(category, "Device:Q")


def _infer_category(query_params: dict) -> str:
    """Infer the JLCPCB category slug from query params."""
    cat = query_params.get("category", "")
    if cat:
        return cat
    # Heuristics from param names
    if "value" in query_params:
        val = query_params["value"].lower()
        if any(u in val for u in ("k", "r", "ohm", "ω")):
            return "resistors"
        if any(u in val for u in ("f", "pf", "nf", "uf", "µf")):
            return "capacitors"
    if "v_out" in query_params:
        return "voltage_regulators"
    if "connector_type" in query_params:
        return "connectors"
    return "components"


def _build_search_query(query_params: dict) -> str:
    """Build a search string from parametric params."""
    parts = []
    for key in ("value", "mpn", "family", "connector_type", "v_out"):
        val = query_params.get(key)
        if val is not None:
            parts.append(str(val))
    pkg = query_params.get("package")
    if pkg:
        parts.append(pkg)
    return " ".join(parts) if parts else ""


def fetch_and_map_part(query_params: dict) -> dict | None:
    """Query the live jlcsearch API and return a mapped component dict.

    Args:
        query_params: dict with keys like value, package, category, mpn, etc.

    Returns:
        A component dict ready for insert_component(), or None if not found.

    Raises:
        OfflineCompilationError: If the network is unreachable.
    """
    search_query = _build_search_query(query_params)
    if not search_query:
        return None

    category = _infer_category(query_params)

    url = f"{API_BASE}/components/list.json?search={urllib.parse.quote(search_query)}&limit=5&full=true"

    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            data = json.loads(resp.read().decode())
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise OfflineCompilationError(
            f"Cannot reach supply chain API ({API_BASE}). "
            f"Compile offline by pre-populating the DB with sync_catalog(). "
            f"Error: {exc}"
        ) from exc
    except Exception:
        return None

    items = data.get("components", [])
    if not items:
        return None

    # Pick best match
    best = None
    query_lower = search_query.lower()
    for item in items:
        mfr = (item.get("mfr") or "").lower()
        desc = (item.get("description") or "").lower()
        if query_lower in mfr or query_lower in desc:
            best = item
            break
    if best is None:
        best = items[0]

    # Extract fields
    lcsc = best.get("lcsc", "")
    mpn = best.get("mfr") or str(lcsc)
    package = best.get("package") or ""
    description = best.get("description") or ""

    footprint = _resolve_footprint(category, package)
    symbol = _resolve_symbol(category, description)

    # Build generic_name from query
    generic_name = search_query.replace(" ", "_").replace(".", "p")

    # Extract parametric values from API response
    extra = best.get("extra", {})
    if isinstance(extra, str):
        try:
            extra = json.loads(extra)
        except (json.JSONDecodeError, TypeError):
            extra = {}

    comp_data = {
        "generic_name": generic_name,
        "kicad_symbol": symbol,
        "kicad_footprint": footprint,
        "manufacturer": best.get("manufacturer", ""),
        "mpn": mpn,
        "supplier_sku": f"C{lcsc}" if lcsc else "",
        "description": description,
        "category": category,
        "attributes_json": json.dumps({
            k: v for k, v in best.items()
            if k not in ("lcsc", "mfr", "description", "package", "manufacturer")
        }),
        "jlc_class": best.get("stock", 0) > 1000 and "Basic" or "Extended",
    }

    # Emit visible terminal notice
    sku = comp_data["supplier_sku"]
    print(
        f"\033[96m[JIT]\033[0m Fetched '{generic_name}' from live API → "
        f"{mpn} ({sku}), footprint: {footprint}"
    )

    return comp_data
