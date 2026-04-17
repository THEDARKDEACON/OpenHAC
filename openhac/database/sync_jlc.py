"""
Sync real in-stock JLCPCB/LCSC components from the jlcsearch API
(https://jlcsearch.tscircuit.com) into the local OpenHaC database.

No API key required. Data sourced from the jlcparts project which
mirrors the official JLCPCB component catalog.
"""

import json
import logging
import os
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

# Debug: Show which API keys are configured
if __name__ == "__main__":
    print("\nAPI Keys configured:")
    print(f"  DIGIKEY_CLIENT_ID: {bool(os.environ.get('DIGIKEY_CLIENT_ID'))}")
    print(f"  MOUSER_API_KEY: {bool(os.environ.get('MOUSER_API_KEY'))}")
    print(f"  TME_API_TOKEN: {bool(os.environ.get('TME_API_TOKEN'))}")
    print(f"  JLCPCB_API_KEY: {bool(os.environ.get('JLCPCB_API_KEY'))}")
    print()

API_BASE = "https://jlcsearch.tscircuit.com"
HEADERS = {"User-Agent": user_agent(), "Accept": "application/json"}

# Each entry: category -> (endpoint_path, response_key)
CATEGORY_ENDPOINTS = {
    # Only these endpoints are confirmed to work at jlcsearch.tscircuit.com
    "resistors":          ("/resistors/list.json?in_stock=true&is_basic=true",          "resistors"),
    "capacitors":         ("/capacitors/list.json?in_stock=true&is_basic=true",         "capacitors"),
    "leds":               ("/leds/list.json?in_stock=true&is_basic=true",               "leds"),
    "mosfets":            ("/mosfets/list.json?in_stock=true&is_basic=true",            "mosfets"),
    "microcontrollers":   ("/microcontrollers/list.json?in_stock=true",                 "microcontrollers"),
    "voltage_regulators": ("/voltage_regulators/list.json?in_stock=true",               "regulators"),
    "diodes":             ("/diodes/list.json?in_stock=true&is_basic=true",             "diodes"),
    "switches":           ("/switches/list.json?in_stock=true&is_basic=true",           "switches"),
    "accelerometers":     ("/accelerometers/list.json?in_stock=true",                   "accelerometers"),
}

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


def _package_to_footprint(category: str, package: str) -> str:
    pkg = package or ""
    if category == "resistors":
        mapping = {
            "0201": "Resistor_SMD:R_0201_0603Metric",
            "0402": "Resistor_SMD:R_0402_1005Metric",
            "0603": "Resistor_SMD:R_0603_1608Metric",
            "0805": "Resistor_SMD:R_0805_2012Metric",
            "1206": "Resistor_SMD:R_1206_3216Metric",
        }
        return mapping.get(pkg, f"Resistor_SMD:R_{pkg}")

    if category == "capacitors":
        mapping = {
            "0201": "Capacitor_SMD:C_0201_0603Metric",
            "0402": "Capacitor_SMD:C_0402_1005Metric",
            "0603": "Capacitor_SMD:C_0603_1608Metric",
            "0805": "Capacitor_SMD:C_0805_2012Metric",
            "1206": "Capacitor_SMD:C_1206_3216Metric",
        }
        return mapping.get(pkg, f"Capacitor_SMD:C_{pkg}")

    if category == "leds":
        mapping = {
            "0402": "LED_SMD:LED_0402_1005Metric",
            "0603": "LED_SMD:LED_0603_1608Metric",
            "0805": "LED_SMD:LED_0805_2012Metric",
        }
        return mapping.get(pkg, f"LED_SMD:LED_{pkg}")

    if category == "mosfets":
        mapping = {
            "SOT-23":   "Package_TO_SOT_SMD:SOT-23",
            "SOT-23-3": "Package_TO_SOT_SMD:SOT-23",
            "SOT-23-6": "Package_TO_SOT_SMD:SOT-23-6_Handsoldering",
        }
        return mapping.get(pkg, f"Package_TO_SOT_SMD:{pkg}")

    if category == "microcontrollers":
        return f"RF_Module:{pkg}" if pkg else "RF_Module:Generic_MCU"

    if category == "voltage_regulators":
        mapping = {
            "SOT-223": "Package_TO_SOT_SMD:SOT-223-3_TabPin2",
            "SOT-23":  "Package_TO_SOT_SMD:SOT-23",
            "TO-252":  "Package_TO_SOT_SMD:TO-252-2",
            "TO-263":  "Package_TO_SOT_SMD:TO-263-3_TabPin2",
        }
        return mapping.get(pkg, f"Package_TO_SOT_SMD:{pkg}")

    if category == "diodes":
        mapping = {
            "SOD-123": "Diode_SMD:D_SOD-123",
            "SOD-323": "Diode_SMD:D_SOD-323",
            "SOT-23":  "Diode_SMD:D_SOT-23",
            "SOD-523": "Diode_SMD:D_SOD-523",
        }
        return mapping.get(pkg, f"Diode_SMD:D_{pkg}")

    if category == "switches":
        return f"Button_Switch_SMD:SW_SPST_SKQG" if not pkg else f"Button_Switch_SMD:SW_{pkg}"

    if category == "accelerometers":
        if pkg == "LGA-14":
            return "Package_LGA:LGA-14_3x5mm_P0.8mm"
        if pkg.startswith("QFN"):
            return f"Package_DFN_QFN:QFN-{pkg}"
        return f"Sensor:Sensor_{pkg}" if pkg else "Sensor:Sensor_Generic"

    if category == "crystals":
        mapping = {
            "HC-49S": "Crystal:Crystal_HC49-4H_Vertical",
            "3225": "Crystal:Crystal_SMD_3225-4Pin_3.2x2.5mm",
            "5032": "Crystal:Crystal_SMD_5032-2Pin_5.0x3.2mm",
            "7050": "Crystal:Crystal_SMD_7050-4Pin_7.0x5.0mm",
        }
        return mapping.get(pkg, f"Crystal:Crystal_{pkg}")

    if category == "connectors":
        if "USB-C" in pkg or "USBC" in pkg:
            return "Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12"
        if "2.54" in pkg:
            return "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical"
        if "1.27" in pkg:
            return "Connector_PinHeader_1.27mm:PinHeader_2x05_P1.27mm_Vertical"
        return f"Connector:Connector_{pkg}" if pkg else "Connector_Generic:Conn_01x04"

    if category == "flash":
        if "SOIC" in pkg:
            return "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm"
        if "WSON" in pkg:
            return "Package_SON:WSON-8_6x5mm"
        return f"Package_SO:SOIC-{pkg}" if pkg else "Package_SO:SOIC-8"

    if category in ("gyroscopes", "magnetometers", "barometers"):
        if pkg == "LGA-14":
            return "Package_LGA:LGA-14_3x5mm_P0.8mm"
        if pkg == "QFN-24":
            return "Package_DFN_QFN:QFN-24_4x4mm_P0.5mm"
        return f"Sensor:Sensor_{pkg}" if pkg else "Sensor:Sensor_Generic"

    if category == "buck_converters":
        if "SOT-23" in pkg:
            return "Package_TO_SOT_SMD:SOT-23-6"
        if "QFN" in pkg:
            return f"Package_DFN_QFN:QFN-{pkg}"
        return f"Package_TO_SOT_SMD:{pkg}" if pkg else "Package_TO_SOT_SMD:SOT-23-6"

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

    except (TypeError, ValueError, KeyError):
        return None

    return None


# Maximum components to fetch per category in a single sync run.
# Set high to populate a comprehensive local database.
SYNC_LIMIT = 5000


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


def sync_catalog(categories: list[str] = None, verbose: bool = True) -> int:
    """Sync real in-stock JLCPCB parts from jlcsearch API into the local database.

    Args:
        categories: list of category names to sync, or None for all
        verbose: print progress

    Returns:
        number of new components inserted
    """
    targets = categories if categories is not None else list(CATEGORY_ENDPOINTS.keys())
    db = DatabaseManager()
    total_inserted = 0
    any_success = False

    for category in targets:
        if category not in CATEGORY_ENDPOINTS:
            if verbose:
                logger.warning(f"Unknown category '{category}', skipping.")
            continue

        if verbose:
            logger.info(f"Fetching {category}...")

        endpoint_path, response_key = CATEGORY_ENDPOINTS[category]

        try:
            items = _fetch_category(endpoint_path, response_key)
        except Exception as e:
            if verbose:
                logger.warning(f"Failed to fetch {category}: {e}")
            continue

        if not items:
            if verbose:
                logger.warning(f"No items returned for {category}, skipping.")
            continue

        any_success = True

        # Sort by stock descending so the most-stocked part wins on dedup
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

            # Diodes use a per-item symbol; all other categories use the map
            if category == "diodes":
                kicad_symbol = _diode_kicad_symbol(item)
            else:
                kicad_symbol = KICAD_SYMBOL_MAP[category]

            component = {
                "generic_name":    generic_name,
                "kicad_symbol":    kicad_symbol,
                "kicad_footprint": _package_to_footprint(category, package),
                "manufacturer":    "",
                "mpn":             mpn,
                "supplier_sku":    supplier_sku,
                "description":     description,
                "category":        category,
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
            logger.info(f"Inserted {inserted} new components from {category}")

    if not any_success and targets:
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
                kicad_footprint = _package_to_footprint(category, item.get("package", ""))

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

    # Generic fuzzy fallback within the same library (often dimension string mismatches).
    prefix = name.split("_", 1)[0].strip()
    if prefix and len(prefix) >= 4:
        # Add pitch token if present.
        must = [prefix]
        low = name.lower()
        if "p0.4" in low or "p0_4" in low:
            must.append("p0.4")
        if "p0.5" in low or "p0_5" in low:
            must.append("p0.5")
        if "p1.27" in low or "p1_27" in low:
            must.append("p1.27")
        hit = _best_fuzzy_match_in_lib(lib, must_contain=must)
        if hit:
            resolved = f"{lib}:{hit}"
            return (resolved, 1, resolved, f"fuzzy resolved {raw} -> {resolved}")

    # Package_LGA special-case: footprints often encode dims/pitch slightly differently.
    if lib == "Package_LGA":
        must = []
        # e.g. "LGA-14"
        if prefix:
            must.append(prefix)
        must.extend(_dim_tokens(name))
        # If we have at least 2 tokens, try a targeted fuzzy search.
        if len(must) >= 2:
            hit = _best_fuzzy_match_in_lib("Package_LGA", must_contain=must[:4])
            if hit:
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
        q = "SELECT generic_name, kicad_footprint FROM components WHERE kicad_footprint IS NOT NULL AND TRIM(kicad_footprint) != ''"
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
        chosen, ok, res, notes = _verify_and_resolve_kicad_footprint(fp)
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
            try:
                if part_info.pinout and all((p.get("name") or "") == (p.get("num") or "") for p in part_info.pinout if isinstance(p, dict)):
                    if verbose:
                        logger.warning(
                            "  %s: pinout appears numeric-only (no named pins). "
                            "For named-pin designs, prefer a vendor source with real pin names "
                            "(or provide a seed-file with pinout_json).",
                            generic_name,
                        )
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
