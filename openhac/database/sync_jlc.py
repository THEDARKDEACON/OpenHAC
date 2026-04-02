"""
Sync real in-stock JLCPCB/LCSC components from the jlcsearch API
(https://jlcsearch.tscircuit.com) into the local OpenHaC database.

No API key required. Data sourced from the jlcparts project which
mirrors the official JLCPCB component catalog.
"""

import json
import urllib.request
from .db_manager import DatabaseManager

API_BASE = "https://jlcsearch.tscircuit.com"
HEADERS = {"User-Agent": "OpenHaC/1.0", "Accept": "application/json"}

# Each entry: category -> (endpoint_path, response_key)
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
# The live lookup fallback in Component._live_lookup handles anything not cached here.
SYNC_LIMIT = 500


def _fetch_category(endpoint_path: str, response_key: str) -> list[dict]:
    """Fetch up to SYNC_LIMIT in-stock components from a typed endpoint."""
    sep = "&" if "?" in endpoint_path else "?"
    url = API_BASE + endpoint_path + f"{sep}limit={SYNC_LIMIT}"
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode())
    return data.get(response_key, [])


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
                print(f"  [warn] Unknown category '{category}', skipping.")
            continue

        if verbose:
            print(f"  Fetching {category}...")

        endpoint_path, response_key = CATEGORY_ENDPOINTS[category]

        try:
            items = _fetch_category(endpoint_path, response_key)
        except Exception as e:
            if verbose:
                print(f"  [warn] Failed to fetch {category}: {e}")
            continue

        if not items:
            if verbose:
                print(f"  [warn] No items returned for {category}, skipping.")
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
            print(f"    → inserted {inserted} new components from {category}")

    if not any_success and targets:
        raise RuntimeError(
            "All category fetches failed. Check your network connection or the "
            "jlcsearch API at https://jlcsearch.tscircuit.com."
        )

    if verbose:
        print(f"Sync complete. {total_inserted} new components inserted.")

    return total_inserted


if __name__ == "__main__":
    sync_catalog()
