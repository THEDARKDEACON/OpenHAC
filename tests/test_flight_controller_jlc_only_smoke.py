from __future__ import annotations

import json


def test_fc_jlc_only_constructs_power_module_without_pin_keyerror(tmp_path):
    from openhac.database.db_manager import DatabaseManager
    from openhac.core.base import Component

    # Isolated DB for this test.
    dm = DatabaseManager(db_path=str(tmp_path / "t.db"))
    Component.db = dm

    # Insert minimal rows required by PowerModule init.
    dm.insert_component(
        {
            "generic_name": "BUCK_TPS63001DRCR",
            "kicad_symbol": "Device:Q",
            "kicad_footprint": "Package_TO_SOT_SMD:SOT-23",
            "manufacturer": "X",
            "mpn": "BUCK_TPS63001DRCR",
            "supplier_sku": "C1",
            "description": "",
            "category": "ic",
            "attributes_json": "{}",
            "pinout_json": json.dumps(
                [{"num": "1", "name": "VIN"}, {"num": "2", "name": "GND"}, {"num": "3", "name": "SW"}, {"num": "4", "name": "FB"}]
            ),
        },
        ignore_duplicate=True,
    )
    dm.insert_component(
        {
            "generic_name": "LDO_LDL1117S33R",
            "kicad_symbol": "Device:Q",
            "kicad_footprint": "Package_TO_SOT_SMD:SOT-23",
            "manufacturer": "X",
            "mpn": "LDO_LDL1117S33R",
            "supplier_sku": "C1",
            "description": "",
            "category": "ic",
            "attributes_json": "{}",
            "pinout_json": json.dumps([{"num": "1", "name": "IN"}, {"num": "2", "name": "OUT"}, {"num": "3", "name": "GND"}]),
        },
        ignore_duplicate=True,
    )
    # Passives used by PowerModule.
    for g in [
        "INDUCTOR_2R2_2520",
        "C_10UF_0805",
        "C_100NF_0603",
        "C_22UF_0805",
        "R_100K_0603",
        "R_32K4_0603",
        "R_1K_0603",
    ]:
        dm.insert_component(
            {
                "generic_name": g,
                "kicad_symbol": "Device:R",
                "kicad_footprint": "Resistor_SMD:R_0603_1608Metric",
                "manufacturer": "X",
                "mpn": g,
                "supplier_sku": "C2",
                "description": "",
                "category": "resistors",
                "attributes_json": "{}",
            },
            ignore_duplicate=True,
        )

    dm.insert_component(
        {
            "generic_name": "LED_GREEN_0603",
            "kicad_symbol": "Device:LED",
            "kicad_footprint": "LED_SMD:LED_0603_1608Metric",
            "manufacturer": "X",
            "mpn": "LED_GREEN_0603",
            "supplier_sku": "C2",
            "description": "",
            "category": "leds",
            "attributes_json": "{}",
            "pinout_json": json.dumps([{"num": "1", "name": "A"}, {"num": "2", "name": "K"}]),
        },
        ignore_duplicate=True,
    )

    import flight_controller_jlc_only as fc

    # Should not raise KeyError for named pins.
    fc.PowerModule()

