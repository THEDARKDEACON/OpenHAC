"""
LCSC/JLCPCB CSV Bulk Import

Downloads and imports the LCSC component database CSV (500k+ parts) into the local SQLite DB.
LCSC provides a full catalog export via their BOM tool that can be downloaded and parsed.

Usage:
    # Download CSV manually from LCSC BOM tool, then:
    python3 -m openhac.database.import_lcsc_csv /path/to/lcsc_components.csv

    # Or use the helper to download directly:
    python3 -m openhac.database.import_lcsc_csv --download

The CSV contains:
    - LCSC Part Number (Cxxxxx)
    - Manufacturer
    - MPN
    - Description
    - Category
    - Package/Footprint
    - Stock quantity
    - Price breaks
    - Datasheet URLs
"""

import csv
import json
import logging
import os
import sys
import urllib.request
from pathlib import Path
from typing import Optional

from .db_manager import DatabaseManager

logger = logging.getLogger("openhac.import_lcsc")

# LCSC BOM tool CSV export URL (this changes, may need manual download)
LCSC_CSV_URL = "https://lcsc.com/api/export/components.csv"

# Known LCSC category to KiCad symbol mappings
CATEGORY_TO_KICAD = {
    "Resistors": "Device:R",
    "Capacitors": "Device:C",
    "Inductors": "Device:L",
    "LEDs": "Device:LED",
    "Diodes": "Device:D",
    "Transistors": "Transistor_BJT:BC817",
    "MOSFETs": "Transistor_FET:BSS138",
    "Voltage Regulators": "Regulator_Linear:AMS1117-5.0",
    "Microcontrollers": "MCU_Module:Generic_MCU",
    "Memory": "Memory_Flash:W25Q128JV",
    "Connectors": "Connector_Generic:Conn_01x04",
    "Crystals": "Device:Crystal",
    "Switches": "Switch:SW_Push",
    "ICs": "Device:IC",
    "Sensors": "Sensor:Generic",
}


def _package_to_kicad_footprint(package: str) -> str:
    """Convert LCSC package name to KiCad footprint library reference."""
    if not package:
        return ""

    pkg = package.upper().replace(" ", "_")

    # SMD Resistors
    if pkg in ("0201", "0402", "0603", "0805", "1206", "1210", "1812", "2010", "2512"):
        return f"Resistor_SMD:R_{pkg}_Metric"

    # SMD Capacitors
    if pkg in ("0201", "0402", "0603", "0805", "1206", "1210", "1812"):
        return f"Capacitor_SMD:C_{pkg}_Metric"

    # SMD LEDs
    if pkg in ("0201", "0402", "0603", "0805", "1206"):
        return f"LED_SMD:LED_{pkg}_Metric"

    # Common IC packages
    if "SOT-23" in pkg:
        return f"Package_TO_SOT_SMD:SOT-23"
    if "SOT-89" in pkg:
        return f"Package_TO_SOT_SMD:SOT-89"
    if "SOT-223" in pkg:
        return f"Package_TO_SOT_SMD:SOT-223"
    if "SOP-8" in pkg or "SOIC-8" in pkg:
        return f"Package_SO:SOIC-8_3.9x4.9mm_P1.27mm"
    if "SOP-16" in pkg or "SOIC-16" in pkg:
        return f"Package_SO:SOIC-16_3.9x9.9mm_P1.27mm"
    if "TSSOP-14" in pkg:
        return f"Package_SO:TSSOP-14_4.4x5mm_P0.65mm"
    if "TSSOP-20" in pkg:
        return f"Package_SO:TSSOP-20_4.4x6.5mm_P0.65mm"
    if "LQFP-32" in pkg:
        return f"Package_QFP:LQFP-32_7x7mm_P0.8mm"
    if "LQFP-48" in pkg:
        return f"Package_QFP:LQFP-48_7x7mm_P0.5mm"
    if "LQFP-64" in pkg:
        return f"Package_QFP:LQFP-64_10x10mm_P0.5mm"
    if "LQFP-100" in pkg:
        return f"Package_QFP:LQFP-100_14x14mm_P0.5mm"
    if "QFN-32" in pkg:
        return f"Package_DFN_QFN:QFN-32-1EP_5x5mm_P0.5mm_EP3.3x3.3mm"
    if "QFN-48" in pkg:
        return f"Package_DFN_QFN:QFN-48-1EP_7x7mm_P0.5mm_EP5.15x5.15mm"

    # Connectors
    if "USB-C" in pkg or "TYPE-C" in pkg:
        return f"Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12"
    if "HEADER" in pkg or "PIN HEADER" in pkg.upper():
        return f"Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical"

    # Crystals
    if "3225" in pkg or "3.2X2.5" in pkg.upper():
        return f"Crystal:Crystal_SMD_3225-4Pin_3.2x2.5mm"
    if "3215" in pkg or "3.2X1.5" in pkg.upper():
        return f"Crystal:Crystal_SMD_3215-2Pin_3.2x1.5mm"

    return ""


def _derive_generic_name(row: dict) -> str:
    """Create a searchable generic name from LCSC CSV row data."""
    category = row.get("First Category", "")
    mpn = row.get("Manufacturer Part Number", "")
    desc = row.get("Description", "")
    pkg = row.get("Package", "")

    # Resistors: R_VALUE_PACKAGE
    if "Resistor" in category:
        # Try to extract value from MPN or description
        import re
        # Look for patterns like 10K, 1K, 100R, 4.7K, etc.
        match = re.search(r'(\d+\.?\d*)([KMkmRr])', mpn + " " + desc)
        if match:
            val = match.group(1)
            unit = match.group(2).upper()
            if unit == 'K':
                val_str = f"{val}K"
            elif unit == 'M':
                val_str = f"{val}M"
            else:
                val_str = f"{val}R"
            pkg_clean = pkg.replace(" ", "_")
            return f"R_{val_str}_{pkg_clean}"
        return f"R_{mpn}_{pkg}"

    # Capacitors: C_VALUE_PACKAGE
    if "Capacitor" in category:
        import re
        # Look for patterns like 100nF, 10uF, 4.7uF, 100pF, etc.
        match = re.search(r'(\d+\.?\d*)([pnuµm])F', mpn + " " + desc)
        if match:
            val = match.group(1)
            unit = match.group(2).lower()
            unit_map = {'p': 'PF', 'n': 'NF', 'u': 'UF', 'µ': 'UF', 'm': 'MF'}
            val_str = f"{val}{unit_map.get(unit, unit.upper())}"
            pkg_clean = pkg.replace(" ", "_")
            return f"C_{val_str}_{pkg_clean}"
        return f"C_{mpn}_{pkg}"

    # Inductors: L_VALUE_PACKAGE
    if "Inductor" in category:
        import re
        match = re.search(r'(\d+\.?\d*)([unmµ])H', mpn + " " + desc)
        if match:
            val = match.group(1)
            unit = match.group(2).lower()
            unit_map = {'p': 'PH', 'n': 'NH', 'u': 'UH', 'µ': 'UH', 'm': 'MH'}
            val_str = f"{val}{unit_map.get(unit, unit.upper())}"
            pkg_clean = pkg.replace(" ", "_")
            return f"L_{val_str}_{pkg_clean}"
        return f"L_{mpn}_{pkg}"

    # LEDs: LED_COLOR_PACKAGE
    if "LED" in category:
        import re
        colors = re.findall(r'(Red|Green|Blue|Yellow|White|RGB|Warm White)', desc, re.I)
        color = colors[0].upper().replace(" ", "_") if colors else ""
        pkg_clean = pkg.replace(" ", "_")
        if color:
            return f"LED_{color}_{pkg_clean}"
        return f"LED_{mpn}_{pkg_clean}"

    # MCUs: MCU_MPN_PACKAGE
    if "MCU" in category or "Microcontroller" in desc:
        return f"MCU_{mpn}_{pkg}"

    # Default: CATEGORY_MPN_PACKAGE
    cat_clean = category.replace(" ", "_").upper()
    return f"{cat_clean}_{mpn}_{pkg}"


def import_lcsc_csv(csv_path: str, verbose: bool = True) -> int:
    """Import LCSC components CSV into the database.

    Args:
        csv_path: Path to the LCSC CSV file
        verbose: Print progress

    Returns:
        Number of components inserted
    """
    db = DatabaseManager()
    csv_file = Path(csv_path)

    if not csv_file.exists():
        logger.error(f"CSV file not found: {csv_path}")
        return 0

    inserted = 0
    skipped = 0

    with open(csv_file, 'r', encoding='utf-8', errors='ignore') as f:
        reader = csv.DictReader(f)

        for row in reader:
            lcsc = row.get("LCSC Part Number", "").strip()
            if not lcsc:
                skipped += 1
                continue

            mpn = row.get("Manufacturer Part Number", "").strip()
            mfr = row.get("Manufacturer", "").strip()
            desc = row.get("Description", "").strip()
            category = row.get("First Category", "").strip()
            pkg = row.get("Package", "").strip()
            stock = row.get("Stock", "0").strip()

            # Skip if already exists
            if db.get_component(lcsc):
                skipped += 1
                continue

            generic_name = _derive_generic_name(row)
            if not generic_name:
                generic_name = lcsc

            kicad_symbol = CATEGORY_TO_KICAD.get(category, "Device:IC")
            kicad_footprint = _package_to_kicad_footprint(pkg)

            component = {
                "generic_name": generic_name,
                "kicad_symbol": kicad_symbol,
                "kicad_footprint": kicad_footprint,
                "manufacturer": mfr,
                "mpn": mpn,
                "supplier_sku": lcsc,
                "description": desc,
                "category": category.lower().replace(" ", "_"),
                "package": pkg,
                "stock": int(stock) if stock.isdigit() else 0,
                "jlc_class": "Basic" if category in ("Resistors", "Capacitors", "LEDs") else "Extended",
                "attributes_json": json.dumps({
                    "lcsc_category": category,
                    "lcsc_package": pkg,
                }),
            }

            row_id = db.insert_component(component, ignore_duplicate=True)
            if row_id:
                inserted += 1
                if verbose and inserted % 1000 == 0:
                    logger.info(f"Imported {inserted} components...")

    if verbose:
        logger.info(f"Import complete: {inserted} inserted, {skipped} skipped")

    return inserted


def download_lcsc_csv(output_path: Optional[str] = None) -> str:
    """Attempt to download the LCSC components CSV.

    Note: LCSC doesn't have a direct CSV download API. The user typically needs to:
    1. Log into LCSC.com
    2. Go to BOM tool
    3. Export the full component database

    This function provides instructions and attempts common URLs.
    """
    output = Path(output_path or "lcsc_components.csv")

    logger.info("Attempting to download LCSC catalog...")
    logger.info("Note: LCSC requires authentication for bulk downloads.")

    # Try the common export URLs
    urls_to_try = [
        "https://lcsc.com/api/export/components.csv",
        "https://jlcpcb.com/api/export/components.csv",
    ]

    for url in urls_to_try:
        try:
            logger.info(f"Trying: {url}")
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.0"
            })
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = resp.read()
                output.write_bytes(data)
                logger.info(f"Downloaded to: {output}")
                return str(output)
        except Exception as e:
            logger.warning(f"Failed: {e}")

    logger.error("""
Could not auto-download LCSC catalog.

Manual download instructions:
1. Visit https://lcsc.com
2. Log in to your account
3. Go to 'BOM Tool' or 'Component Search'
4. Look for 'Export' or 'Download' option
5. Download the full components CSV
6. Run: python3 -m openhac.database.import_lcsc_csv /path/to/downloaded.csv
""")
    return ""


def main():
    if len(sys.argv) < 2:
        print("""
LCSC CSV Import Tool

Usage:
    python3 -m openhac.database.import_lcsc_csv <path/to/lcsc.csv>
    python3 -m openhac.database.import_lcsc_csv --download

The CSV should contain columns like:
    - LCSC Part Number
    - Manufacturer
    - Manufacturer Part Number
    - Description
    - Package
    - Stock
    - Category

Download from: https://lcsc.com (BOM Tool > Export)
""")
        sys.exit(1)

    if sys.argv[1] == "--download":
        csv_path = download_lcsc_csv()
        if csv_path:
            import_lcsc_csv(csv_path)
    else:
        import_lcsc_csv(sys.argv[1])


if __name__ == "__main__":
    main()
