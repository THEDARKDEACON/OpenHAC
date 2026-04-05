"""Bootstrap the local SQLite catalog with example rows (offline dev / demos).

Why lists of components live here
--------------------------------
OpenHaC's **runtime source of truth** for part data is the **SQLite database**
(``openhac.db`` or ``OPENHAC_DB_PATH``). That file is not shipped full of every
JLC part: it is filled by **you** via:

- **This module** — ``openhac seed`` / ``seed_database()`` INSERTs a curated set
  so tutorials (e.g. flight controller) and tests work **without** network.
- **``openhac sync``** — pulls many parts from the JLC-oriented catalog into the DB.
- **JIT paths** — ``Component`` / ``parametric_search`` can call the live API
  (see ``api_fallback`` / ``db_manager`` Phase 4) and **cache** rows into the same DB.

So ``seed_data.py`` is not "instead of" the database; it **writes into** the
database the first time (or adds idempotent rows like ``part_offers``) when you
want a reproducible starter dataset.
"""

import json
import logging
import os
from .db_manager import DatabaseManager

logger = logging.getLogger("openhac.seed")


def _seed_idempotent_part_offers(db: DatabaseManager) -> None:
    """LIB-001 sample rows (safe to call on every seed; INSERT OR IGNORE)."""
    for offer in (
        {
            "generic_name": "R_10k_0805",
            "rank": 1,
            "supplier": "Mouser",
            "supplier_sku": "603-RC0805FR-0710KL",
            "mpn": "RC0805FR-0710KL",
            "note": "LIB-001 example",
        },
        {
            "generic_name": "R_10k_0805",
            "rank": 2,
            "supplier": "DigiKey",
            "supplier_sku": "311-10.0KCRCT-ND",
            "mpn": "",
            "note": "",
        },
    ):
        db.insert_part_offer(offer, ignore_duplicate=True)


def seed_database():
    db = DatabaseManager()
    _seed_idempotent_part_offers(db)

    # Check if a critical new part is missing
    if db.get_component("MCU_STM32F407VET6"):
        logger.info("Database already seeded with production flight-controller parts.")
        return

    components = [
        # --- Resistors ---
        {
            "generic_name": "R_10k_0805",
            "kicad_symbol": "Device:R",
            "kicad_footprint": "Resistor_SMD:R_0805_2012Metric",
            "manufacturer": "Yageo",
            "mpn": "RC0805FR-0710KL",
            "supplier_sku": "C17513",
            "description": "10k 1% 0805 Resistor",
            "category": "resistors",
            "tolerance": "1%",
            "power_watts": 0.125,
            "jlc_class": "Basic",
        },
        {
            "generic_name": "R_1k_0603",
            "kicad_symbol": "Device:R",
            "kicad_footprint": "Resistor_SMD:R_0603_1608Metric",
            "manufacturer": "Yageo",
            "mpn": "RC0603FR-071KL",
            "supplier_sku": "C21190",
            "description": "1k 1% 0603 Resistor",
            "category": "resistors",
            "tolerance": "1%",
            "power_watts": 0.1,
            "jlc_class": "Basic",
        },

        # --- Capacitors ---
        {
            "generic_name": "C_100nF_0603",
            "kicad_symbol": "Device:C",
            "kicad_footprint": "Capacitor_SMD:C_0603_1608Metric",
            "manufacturer": "Samsung Electro-Mechanics",
            "mpn": "CL10B104KB8NNNC",
            "supplier_sku": "C14663",
            "description": "100nF 50V 0603 Capacitor",
            "category": "capacitors",
            "voltage_rating": 50.0,
            "jlc_class": "Basic",
        },
        {
            "generic_name": "C_10uF_0805",
            "kicad_symbol": "Device:C",
            "kicad_footprint": "Capacitor_SMD:C_0805_2012Metric",
            "manufacturer": "Samsung Electro-Mechanics",
            "mpn": "CL21A106KAYNNNE",
            "supplier_sku": "C15850",
            "description": "10uF 25V 0805 Capacitor",
            "category": "capacitors",
            "voltage_rating": 25.0,
            "jlc_class": "Basic",
        },
        {
            "generic_name": "C_470uF_1210",
            "kicad_symbol": "Device:C",
            "kicad_footprint": "Capacitor_SMD:C_1210_3225Metric",
            "manufacturer": "Murata",
            "mpn": "GRM32ER61E476ME15L",
            "supplier_sku": "C96123",
            "description": "470uF 25V 1210 Capacitor",
            "category": "capacitors",
            "voltage_rating": 25.0,
            "jlc_class": "Extended",
        },

        # --- Connectors ---
        {
            "generic_name": "XT60_Vertical",
            "kicad_symbol": "Connector_Generic:Conn_01x02",
            "kicad_footprint": "Connector_AMASS:AMASS_XT60-M_1x02_P7.20mm_Vertical",
            "manufacturer": "AMASS",
            "mpn": "XT60-M",
            "supplier_sku": "C123456",
            "description": "XT60 Male Vertical Connector",
            "category": "connectors",
            "jlc_class": "Extended",
        },
        {
            "generic_name": "Conn_USB_C_Receptacle",
            "kicad_symbol": "Connector:USB_C_Receptacle_USB2.0",
            "kicad_footprint": "Connector_USB:USB_C_Receptacle",
            "manufacturer": "Korean Hroparts",
            "mpn": "TYPE-C-31-M-12",
            "supplier_sku": "C165948",
            "description": "USB Type-C Receptacle",
            "category": "connectors",
            "jlc_class": "Basic",
        },

        # --- Voltage Regulators ---
        {
            "generic_name": "LDO_5V",
            "kicad_symbol": "Regulator_Linear:AMS1117-5.0",
            "kicad_footprint": "Package_TO_SOT_SMD:SOT-223-3_TabPin2",
            "manufacturer": "Advanced Monolithic Systems",
            "mpn": "AMS1117-5.0",
            "supplier_sku": "C347222",
            "description": "5V 1A LDO Voltage Regulator",
            "category": "voltage_regulators",
            "jlc_class": "Basic",
        },
        {
            "generic_name": "LDO_5V_TO-252",
            "kicad_symbol": "Regulator_Linear:AMS1117-5.0",
            "kicad_footprint": "Package_TO_SOT_SMD:TO-252-2",
            "manufacturer": "Texas Instruments",
            "mpn": "LM1117IMP-5.0",
            "supplier_sku": "C26093",
            "description": "5V 3A Buck Regulator TO-252",
            "category": "voltage_regulators",
            "jlc_class": "Extended",
        },
        {
            "generic_name": "LDO_3.3V_SOT-223",
            "kicad_symbol": "Regulator_Linear:AMS1117-3.3",
            "kicad_footprint": "Package_TO_SOT_SMD:SOT-223-3_TabPin2",
            "manufacturer": "Advanced Monolithic Systems",
            "mpn": "AMS1117-3.3",
            "supplier_sku": "C6186",
            "description": "3.3V 1A LDO Regulator SOT-223",
            "category": "voltage_regulators",
            "jlc_class": "Basic",
        },

        # --- MCUs ---
        {
            "generic_name": "ESP32_WROOM",
            "kicad_symbol": "MCU_Module:ESP32-WROOM-32E",
            "kicad_footprint": "RF_Module:ESP32-WROOM-32",
            "manufacturer": "Espressif Systems",
            "mpn": "ESP32-WROOM-32E (8MB)",
            "supplier_sku": "C529596",
            "description": "ESP32-WROOM-32E WiFi/BT Module",
            "category": "microcontrollers",
            "jlc_class": "Extended",
        },
        {
            "generic_name": "MCU_STM32F407VET6_C28730",
            "kicad_symbol": "MCU_ST_STM32:STM32F407VETx",
            "kicad_footprint": "Package_QFP:LQFP-100_14x14mm_P0.5mm",
            "manufacturer": "STMicroelectronics",
            "mpn": "STM32F407VET6",
            "supplier_sku": "C28730",
            "description": "ARM Cortex-M4 168MHz 512KB Flash MCU",
            "category": "microcontrollers",
            "jlc_class": "Extended",
        },
        {
            "generic_name": "MCU_STM32F407VET6",
            "kicad_symbol": "MCU_ST_STM32F4:STM32F407VET6",
            "kicad_footprint": "Package_QFP:LQFP-100_14x14mm_P0.5mm",
            "manufacturer": "STMicroelectronics",
            "mpn": "STM32F407VET6",
            "supplier_sku": "C28730",
            "category": "microcontrollers",
            "description": "ARM Cortex-M4 MCU, 1MB Flash, 192KB RAM",
            "attributes_json": json.dumps({"family": "STM32F4", "speed_mhz": 168})
        },
        {
            "generic_name": "USB-C",
            "kicad_symbol": "Connector:USB_C_Receptacle_USB2.0",
            "kicad_footprint": "Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12",
            "manufacturer": "HRO",
            "mpn": "TYPE-C-31-M-12",
            "supplier_sku": "C165948",
            "category": "connectors",
            "description": "USB-C Receptacle 16-pin",
            "attributes_json": json.dumps({"connector_type": "USB-C", "pin_count": 16})
        },
        # --- Testability (REL-003) ---
        {
            "generic_name": "TP_Mech_1mm",
            "kicad_symbol": "Device:TestPoint",
            "kicad_footprint": "TestPoint:TestPoint_Pad_D1.0mm",
            "manufacturer": "",
            "mpn": "TP-1mm",
            "supplier_sku": "",
            "description": "1 mm mechanical test pad (KiCad stock lib)",
            "category": "testability",
            "jlc_class": "Extended",
        },
    ]

    for comp in components:
        db.insert_component(comp)
        logger.debug(f"Inserted {comp['generic_name']}")

    if not db.get_component("TP_Mech_1mm"):
        db.insert_component(
            {
                "generic_name": "TP_Mech_1mm",
                "kicad_symbol": "Device:TestPoint",
                "kicad_footprint": "TestPoint:TestPoint_Pad_D1.0mm",
                "manufacturer": "",
                "mpn": "TP-1mm",
                "supplier_sku": "",
                "description": "1 mm mechanical test pad (KiCad stock lib)",
                "category": "testability",
                "jlc_class": "Extended",
            }
        )
        logger.debug("Inserted TP_Mech_1mm (idempotent seed)")

    logger.info("Database seeding completed.")


if __name__ == "__main__":
    seed_database()
