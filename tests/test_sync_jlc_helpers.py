from __future__ import annotations

from openhac.database.sync_jlc import _derive_generic_name, _package_to_footprint


def test_derive_generic_name_resistor():
    item = {"resistance": 10_000, "package": "0805"}
    assert _derive_generic_name("resistors", item) == "R_10k_0805"


def test_derive_generic_name_capacitor():
    item = {"capacitance": 1e-6, "package": "0603"}
    assert _derive_generic_name("capacitors", item) == "C_1uF_0603"


def test_derive_generic_name_led():
    item = {"color": "red", "package": "0603"}
    assert _derive_generic_name("leds", item) == "LED_RED_0603"


def test_package_to_footprint_basic_mappings():
    assert _package_to_footprint("resistors", "0603") == "Resistor_SMD:R_0603_1608Metric"
    assert _package_to_footprint("capacitors", "0402") == "Capacitor_SMD:C_0402_1005Metric"
    assert _package_to_footprint("leds", "0805") == "LED_SMD:LED_0805_2012Metric"

