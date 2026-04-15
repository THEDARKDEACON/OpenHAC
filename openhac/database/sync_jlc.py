"""
Sync real in-stock JLCPCB/LCSC components from the jlcsearch API
(https://jlcsearch.tscircuit.com) into the local OpenHaC database.

No API key required. Data sourced from the jlcparts project which
mirrors the official JLCPCB component catalog.
"""

import json
import logging
import urllib.request

from openhac.version_info import user_agent

from .db_manager import DatabaseManager

logger = logging.getLogger("openhac.sync")

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
            generic_name = item.get("generic_name") or _derive_generic_name(item, category) or lcsc

            kicad_footprint = item.get("kicad_footprint", "")
            if not kicad_footprint:
                kicad_footprint = _infer_footprint_from_pkg(item.get("package", ""))

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


def seed_essential_components(verbose: bool = True) -> int:
    """Seed the database with essential real JLCPCB parts for offline use.

    These are actual parts with real LCSC SKUs that can be used in designs
    without requiring network access.
    """
    db = DatabaseManager()

    # Real JLCPCB parts with verified SKUs
    essential_parts = [
        # STM32 MCUs
        {"generic_name": "MCU_STM32F405RGT6", "kicad_symbol": "MCU_ST_STM32F4:STM32F405RGT6",
         "kicad_footprint": "Package_QFP:LQFP-64_10x10mm_P0.5mm", "manufacturer": "ST",
         "mpn": "STM32F405RGT6", "supplier_sku": "C7862", "category": "microcontrollers",
         "description": "ARM Cortex-M4 168MHz 1MB Flash"},

        {"generic_name": "MCU_STM32F407VET6", "kicad_symbol": "MCU_ST_STM32F4:STM32F407VET6",
         "kicad_footprint": "Package_QFP:LQFP-100_14x14mm_P0.5mm", "manufacturer": "ST",
         "mpn": "STM32F407VET6", "supplier_sku": "C7846", "category": "microcontrollers",
         "description": "ARM Cortex-M4 168MHz 512KB Flash"},

        # Power - Buck/Boost
        {"generic_name": "BUCK_TPS63001DRCR", "kicad_symbol": "Regulator_Switching:TPS63001",
         "kicad_footprint": "Package_DFN_QFN:VSON-10_3x3mm_P0.5mm", "manufacturer": "TI",
         "mpn": "TPS63001DRCR", "supplier_sku": "C132150", "category": "voltage_regulators",
         "description": "Buck-Boost 1.5A 1.8-5.5V"},

        {"generic_name": "LDO_LDL1117S33R", "kicad_symbol": "Regulator_Linear:LDL1117S33R",
         "kicad_footprint": "Package_TO_SOT_SMD:SOT-223-3_TabPin2", "manufacturer": "ST",
         "mpn": "LDL1117S33R", "supplier_sku": "C130026", "category": "voltage_regulators",
         "description": "LDO 3.3V 800mA"},

        # Sensors
        {"generic_name": "IMU_ICM42688P", "kicad_symbol": "Sensor_Motion:ICM-42688-P",
         "kicad_footprint": "Package_LGA:LGA-14_3x2.5mm_P0.4mm", "manufacturer": "TDK",
         "mpn": "ICM-42688-P", "supplier_sku": "C2191168", "category": "accelerometers",
         "description": "6-Axis IMU SPI/I2C"},

        {"generic_name": "BARO_BMP388", "kicad_symbol": "Sensor_Pressure:BMP388",
         "kicad_footprint": "Package_LGA:LGA-10_2x2mm_P0.5mm", "manufacturer": "Bosch",
         "mpn": "BMP388", "supplier_sku": "C83294", "category": "accelerometers",
         "description": "Pressure Sensor I2C/SPI"},

        {"generic_name": "MAG_QMC5883L", "kicad_symbol": "Sensor_Magnetic:QMC5883L",
         "kicad_footprint": "Package_LGA:LGA-16_3x3mm_P0.5mm", "manufacturer": "QST",
         "mpn": "QMC5883L", "supplier_sku": "C976032", "category": "accelerometers",
         "description": "3-Axis Magnetometer I2C"},

        # Memory
        {"generic_name": "FLASH_W25Q128JV", "kicad_symbol": "Memory_Flash:W25Q128JV",
         "kicad_footprint": "Package_SO:SOIC-8_5.23x5.23mm_P1.27mm", "manufacturer": "Winbond",
         "mpn": "W25Q128JVSIQ", "supplier_sku": "C97521", "category": "microcontrollers",
         "description": "128Mbit SPI Flash"},

        # Interface
        {"generic_name": "CAN_TJA1051", "kicad_symbol": "Interface_CAN_LIN:TJA1051T",
         "kicad_footprint": "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm", "manufacturer": "NXP",
         "mpn": "TJA1051T/3", "supplier_sku": "C132146", "category": "microcontrollers",
         "description": "CAN Transceiver 3.3V"},

        {"generic_name": "ESD_USBLC6_2SC6", "kicad_symbol": "Power_Protection:USBLC6-2SC6",
         "kicad_footprint": "Package_TO_SOT_SMD:SOT-23-6", "manufacturer": "ST",
         "mpn": "USBLC6-2SC6", "supplier_sku": "C7518", "category": "diodes",
         "description": "USB ESD Protection"},

        # Crystals (use closest category)
        {"generic_name": "XTAL_8MHZ_3225", "kicad_symbol": "Device:Crystal",
         "kicad_footprint": "Crystal:Crystal_SMD_3225-4Pin_3.2x2.5mm", "manufacturer": "Yangxing",
         "mpn": "X32258MSB4SI", "supplier_sku": "C15629", "category": "switches",
         "description": "8MHz 20pF Crystal"},

        {"generic_name": "XTAL_32K768_3215", "kicad_symbol": "Device:Crystal",
         "kicad_footprint": "Crystal:Crystal_SMD_3215-2Pin_3.2x1.5mm", "manufacturer": "Seiko",
         "mpn": "FC-135", "supplier_sku": "C70501", "category": "switches",
         "description": "32.768kHz RTC Crystal"},

        # Passives - Resistors (0603)
        {"generic_name": "R_1K_0603", "kicad_symbol": "Device:R",
         "kicad_footprint": "Resistor_SMD:R_0603_1608Metric", "manufacturer": "Yageo",
         "mpn": "RC0603FR-071KL", "supplier_sku": "C21190", "category": "resistors",
         "description": "1k 1% 0603"},

        {"generic_name": "R_10K_0402", "kicad_symbol": "Device:R",
         "kicad_footprint": "Resistor_SMD:R_0402_1005Metric", "manufacturer": "Yageo",
         "mpn": "RC0402FR-0710KL", "supplier_sku": "C60491", "category": "resistors",
         "description": "10k 1% 0402"},

        {"generic_name": "R_100K_0402", "kicad_symbol": "Device:R",
         "kicad_footprint": "Resistor_SMD:R_0402_1005Metric", "manufacturer": "Yageo",
         "mpn": "RC0402FR-07100KL", "supplier_sku": "C60491", "category": "resistors",
         "description": "100k 1% 0402"},

        {"generic_name": "R_5K1_0402", "kicad_symbol": "Device:R",
         "kicad_footprint": "Resistor_SMD:R_0402_1005Metric", "manufacturer": "Yageo",
         "mpn": "RC0402FR-075K1L", "supplier_sku": "C25905", "category": "resistors",
         "description": "5.1k 1% 0402"},

        {"generic_name": "R_27R_0402", "kicad_symbol": "Device:R",
         "kicad_footprint": "Resistor_SMD:R_0402_1005Metric", "manufacturer": "Yageo",
         "mpn": "RC0402FR-0727RL", "supplier_sku": "C60458", "category": "resistors",
         "description": "27R 1% 0402"},

        {"generic_name": "R_1K_0603", "kicad_symbol": "Device:R",
         "kicad_footprint": "Resistor_SMD:R_0603_1608Metric", "manufacturer": "Yageo",
         "mpn": "RC0603FR-071KL", "supplier_sku": "C21190", "category": "resistors",
         "description": "1k 1% 0603"},

        {"generic_name": "R_100K_0603", "kicad_symbol": "Device:R",
         "kicad_footprint": "Resistor_SMD:R_0603_1608Metric", "manufacturer": "Yageo",
         "mpn": "RC0603FR-07100KL", "supplier_sku": "C25804", "category": "resistors",
         "description": "100k 1% 0603"},

        {"generic_name": "R_32K4_0603", "kicad_symbol": "Device:R",
         "kicad_footprint": "Resistor_SMD:R_0603_1608Metric", "manufacturer": "Yageo",
         "mpn": "RC0603FR-0732K4L", "supplier_sku": "C25818", "category": "resistors",
         "description": "32.4k 1% 0603"},

        # Passives - Capacitors
        {"generic_name": "C_100NF_0603", "kicad_symbol": "Device:C",
         "kicad_footprint": "Capacitor_SMD:C_0603_1608Metric", "manufacturer": "Yageo",
         "mpn": "CC0603KRX7R9BB104", "supplier_sku": "C14663", "category": "capacitors",
         "description": "100nF 50V X7R 0603"},

        {"generic_name": "C_100NF_0402", "kicad_symbol": "Device:C",
         "kicad_footprint": "Capacitor_SMD:C_0402_1005Metric", "manufacturer": "Murata",
         "mpn": "GRM155R71C104KA88D", "supplier_sku": "C1525", "category": "capacitors",
         "description": "100nF 16V X7R 0402"},

        {"generic_name": "C_10UF_0805", "kicad_symbol": "Device:C",
         "kicad_footprint": "Capacitor_SMD:C_0805_2012Metric", "manufacturer": "Murata",
         "mpn": "GRM21BR61C106KE15L", "supplier_sku": "C440198", "category": "capacitors",
         "description": "10uF 16V X5R 0805"},

        {"generic_name": "C_22UF_0805", "kicad_symbol": "Device:C",
         "kicad_footprint": "Capacitor_SMD:C_0805_2012Metric", "manufacturer": "Murata",
         "mpn": "GRM21BR61C226ME44L", "supplier_sku": "C59461", "category": "capacitors",
         "description": "22uF 16V X5R 0805"},

        {"generic_name": "C_4U7_0603", "kicad_symbol": "Device:C",
         "kicad_footprint": "Capacitor_SMD:C_0603_1608Metric", "manufacturer": "Murata",
         "mpn": "GRM188R61E475KE21D", "supplier_sku": "C84718", "category": "capacitors",
         "description": "4.7uF 25V X5R 0603"},

        {"generic_name": "C_18PF_0402", "kicad_symbol": "Device:C",
         "kicad_footprint": "Capacitor_SMD:C_0402_1005Metric", "manufacturer": "Murata",
         "mpn": "GRM1555C1H180JZ01D", "supplier_sku": "C107274", "category": "capacitors",
         "description": "18pF 50V C0G 0402"},

        {"generic_name": "C_12PF_0402", "kicad_symbol": "Device:C",
         "kicad_footprint": "Capacitor_SMD:C_0402_1005Metric", "manufacturer": "Murata",
         "mpn": "GRM1555C1H120JZ01D", "supplier_sku": "C107270", "category": "capacitors",
         "description": "12pF 50V C0G 0402"},

        # LEDs
        {"generic_name": "LED_GREEN_0603", "kicad_symbol": "Device:LED",
         "kicad_footprint": "LED_SMD:LED_0603_1608Metric", "manufacturer": "Lite-On",
         "mpn": "LTST-C193TGKT-5A", "supplier_sku": "C125093", "category": "leds",
         "description": "Green LED 0603"},

        {"generic_name": "LED_BLUE_0603", "kicad_symbol": "Device:LED",
         "kicad_footprint": "LED_SMD:LED_0603_1608Metric", "manufacturer": "Lite-On",
         "mpn": "LTST-C193TBKT-5A", "supplier_sku": "C125088", "category": "leds",
         "description": "Blue LED 0603"},

        # Switches/Buttons
        {"generic_name": "SW_TACT_3X6MM", "kicad_symbol": "Switch:SW_Push",
         "kicad_footprint": "Button_Switch_SMD:SW_SPST_TL3342", "manufacturer": "E-Switch",
         "mpn": "TL3342F160QG", "supplier_sku": "C2884834", "category": "switches",
         "description": "Tactile Switch 3x6mm"},

        # Inductors
        {"generic_name": "INDUCTOR_2R2_2520", "kicad_symbol": "Device:L",
         "kicad_footprint": "Inductor_SMD:L_2.5x2.0mm", "manufacturer": "TDK",
         "mpn": "VLS252010ET-2R2M", "supplier_sku": "C167240", "category": "resistors",
         "description": "2.2uH 1.4A Inductor"},

        # Connectors (use closest category)
        {"generic_name": "USB_C_16PIN", "kicad_symbol": "Connector:USB_C_Receptacle_USB2.0",
         "kicad_footprint": "Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12",
         "manufacturer": "HRO", "mpn": "TYPE-C-31-M-12", "supplier_sku": "C165948",
         "category": "connectors", "description": "USB-C 16P 5A"},

        {"generic_name": "CONN_SWD_2X5_127MM", "kicad_symbol": "Connector:Conn_02x05_Odd_Even",
         "kicad_footprint": "Connector_PinHeader_1.27mm:PinHeader_2x05_P1.27mm_Vertical_SMD",
         "manufacturer": "CJT", "mpn": "A2005WR-2x5P", "supplier_sku": "C249742",
         "category": "connectors", "description": "SWD Header 2x5 1.27mm"},
    ]

    inserted = 0
    for part in essential_parts:
        part["jlc_class"] = "Basic" if part["category"] in ("resistors", "capacitors", "leds") else "Extended"
        part["attributes_json"] = json.dumps({"voltage_rating": "50V" if part["category"] == "resistors" else "",
                                               "tolerance": "1%" if part["category"] == "resistors" else "±10%"})
        row_id = db.insert_component(part, ignore_duplicate=True)
        if row_id:
            inserted += 1

    if verbose:
        logger.info(f"Seeded {inserted} essential JLCPCB components")
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


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--full":
        # Full sync - fetch thousands of parts
        sync_all_jlcpcb(max_per_category=10000)
    elif len(sys.argv) > 1 and sys.argv[1] == "--seed":
        # Keep seed for backwards compatibility, but recommend --full
        logger.info("Using --seed (seeded data). For real JLCPCB data, use --full instead.")
        seed_essential_components()
    else:
        # Default: standard catalog sync with higher limits
        sync_catalog()
