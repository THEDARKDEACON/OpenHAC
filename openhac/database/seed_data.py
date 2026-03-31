import os
from .db_manager import DatabaseManager

def seed_database():
    db = DatabaseManager()
    
    # Check if already seeded
    if db.get_component("R_10k_0805"):
        print("Database already seeded.")
        return

    components = [
        {
            "generic_name": "R_10k_0805",
            "kicad_symbol": "Device:R",
            "kicad_footprint": "Resistor_SMD:R_0805_2012Metric",
            "manufacturer": "Yageo",
            "mpn": "RC0805FR-0710KL",
            "supplier_sku": "C17513",
            "description": "10k 1% 0805 Resistor"
        },
        {
            "generic_name": "C_100nF_0603",
            "kicad_symbol": "Device:C",
            "kicad_footprint": "Capacitor_SMD:C_0603_1608Metric",
            "manufacturer": "Samsung Electro-Mechanics",
            "mpn": "CL10B104KB8NNNC",
            "supplier_sku": "C14663",
            "description": "100nF 50V 0603 Capacitor"
        },
        {
            "generic_name": "XT60_Vertical",
            "kicad_symbol": "Connector_Generic:Conn_01x02",
            "kicad_footprint": "Connector_AMASS:AMASS_XT60-M_1x02_P7.20mm_Vertical",
            "manufacturer": "AMASS",
            "mpn": "XT60-M",
            "supplier_sku": "C123456",
            "description": "XT60 Male Vertical Connector"
        },
        {
            "generic_name": "LDO_5V",
            "kicad_symbol": "Regulator_Linear:AMS1117-5.0",
            "kicad_footprint": "Package_TO_SOT_SMD:SOT-223-3_TabPin2",
            "manufacturer": "Advanced Monolithic Systems",
            "mpn": "AMS1117-5.0",
            "supplier_sku": "C347222",
            "description": "5V 1A LDO Voltage Regulator"
        },
        {
            "generic_name": "ESP32_WROOM",
            "kicad_symbol": "MCU_Module:ESP32-WROOM-32E",
            "kicad_footprint": "RF_Module:ESP32-WROOM-32",
            "manufacturer": "Espressif Systems",
            "mpn": "ESP32-WROOM-32E (8MB)",
            "supplier_sku": "C529596",
            "description": "ESP32-WROOM-32E WiFi/BT Module"
        }
    ]

    for comp in components:
        db.insert_component(comp)
        print(f"Inserted {comp['generic_name']}")

    print("Database seeding completed.")

if __name__ == "__main__":
    seed_database()
