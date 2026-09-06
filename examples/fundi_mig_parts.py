"""Offline pinouts for the Fundi MIG controller OpenHaC port.

Footprints are stock KiCad libraries (3D via ${KICAD9_3DMODEL_DIR}).
SPICE subckts are matched by MPN against examples/fundi_mig_spice/overlay.json.
"""

from __future__ import annotations

import json
from typing import Any


def _pinout(pins: dict[int | str, tuple[str, str]]) -> str:
    rows = [{"num": str(n), "name": name, "type": typ} for n, (name, typ) in pins.items()]
    return json.dumps(rows)


def part(
    *,
    generic_name: str,
    footprint: str,
    pins: dict[int | str, tuple[str, str]],
    category: str,
    symbol: str,
    mpn: str | None = None,
    package: str = "",
    description: str = "",
) -> dict[str, Any]:
    return {
        "generic_name": generic_name,
        "mpn": mpn or generic_name,
        "manufacturer": "OpenHaC-Fundi",
        "description": description or generic_name,
        "category": category,
        "package": package,
        "kicad_symbol": symbol,
        "kicad_footprint": footprint,
        "pinout_json": _pinout(pins),
        "jlc_class": "Basic",
    }


def mk(name: str, data: dict):
    from openhac.core.base import Component

    c = Component(name, comp_data=dict(data))
    part_obj = getattr(c, "part", None)
    if part_obj is not None:
        fields = getattr(part_obj, "fields", None)
        if isinstance(fields, dict):
            if data.get("kicad_footprint"):
                part_obj.footprint = data["kicad_footprint"]
                fields["Footprint"] = data["kicad_footprint"]
            if data.get("kicad_symbol"):
                fields["kicad_symbol"] = data["kicad_symbol"]
                fields["kiCad_symbol"] = data["kicad_symbol"]
            fields["Value"] = name
            if data.get("mpn"):
                fields["MPN"] = data["mpn"]
            if data.get("generic_name"):
                fields["generic_name"] = data["generic_name"]
            if data.get("category"):
                fields["category"] = data["category"]
                fields["Category"] = data["category"]
    return c


def R(name: str, ohms: str) -> dict:
    d = part(
        generic_name=name,
        footprint="Resistor_SMD:R_0805_2012Metric",
        pins={1: ("1", "passive"), 2: ("2", "passive")},
        category="Resistor",
        symbol="Device:R",
        package="0805",
        description=f"Resistor {ohms}",
    )
    return d


def C(name: str, val: str) -> dict:
    return part(
        generic_name=name,
        footprint="Capacitor_SMD:C_0805_2012Metric",
        pins={1: ("1", "passive"), 2: ("2", "passive")},
        category="Capacitor",
        symbol="Device:C",
        package="0805",
        description=f"Capacitor {val}",
    )


def Vsrc(name: str, volts: str) -> dict:
    return part(
        generic_name=name,
        footprint="Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical",
        pins={1: ("+", "passive"), 2: ("-", "passive")},
        category="Connector",
        symbol="Device:Battery_Cell",
        package="sim",
        description=f"DC source {volts} (spice rail / battery stand-in)",
    )


LED = part(
    generic_name="LED_3MM",
    footprint="LED_THT:LED_D3.0mm",
    pins={1: ("K", "passive"), 2: ("A", "passive")},
    category="LED",
    symbol="Device:LED",
    package="3mm",
    mpn="LED_RED",
    description="3 mm LED",
)

D_1N4007 = part(
    generic_name="D_1N4007",
    footprint="Diode_THT:D_DO-41_SOD81_P10.16mm_Horizontal",
    pins={1: ("K", "passive"), 2: ("A", "passive")},
    category="Diode",
    symbol="Device:D",
    package="DO-41",
    mpn="1N4007",
    description="1N4007 rectifier",
)

D_1N5819 = part(
    generic_name="D_1N5819",
    footprint="Diode_THT:D_DO-41_SOD81_P10.16mm_Horizontal",
    pins={1: ("K", "passive"), 2: ("A", "passive")},
    category="Diode",
    symbol="Device:D_Schottky",
    package="DO-41",
    mpn="1N5819",
    description="1N5819 Schottky",
)

AD620 = part(
    generic_name="AD620",
    footprint="Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
    pins={
        1: ("Rg", "passive"),
        2: ("-", "input"),
        3: ("+", "input"),
        4: ("Vs-", "power_in"),
        5: ("Ref", "passive"),
        6: ("OUT", "output"),
        7: ("Vs+", "power_in"),
        8: ("Rg2", "passive"),
    },
    category="Amplifier",
    symbol="Amplifier_Instrumentation:AD620",
    package="SOIC-8",
    mpn="AD620ANZ",
    description="AD620 instrumentation amplifier",
)

PC817 = part(
    generic_name="OPTO_PC817",
    footprint="Package_DIP:DIP-4_W7.62mm",
    pins={
        1: ("A", "passive"),
        2: ("K", "passive"),
        3: ("E", "passive"),
        4: ("C", "passive"),
    },
    category="Isolator",
    symbol="Isolator:PC817",
    package="DIP-4",
    mpn="PC817",
    description="PC817 phototransistor optocoupler",
)

HC14 = part(
    generic_name="74HC14",
    footprint="Package_DIP:DIP-14_W7.62mm",
    pins={
        1: ("1A", "input"),
        2: ("1Y", "output"),
        3: ("2A", "input"),
        4: ("2Y", "output"),
        5: ("3A", "input"),
        6: ("3Y", "output"),
        7: ("GND", "power_in"),
        8: ("4Y", "output"),
        9: ("4A", "input"),
        10: ("5Y", "output"),
        11: ("5A", "input"),
        12: ("6Y", "output"),
        13: ("6A", "input"),
        14: ("VCC", "power_in"),
    },
    category="Logic",
    symbol="74xx:74HC14",
    package="DIP-14",
    mpn="SN74HC14N",
    description="Hex Schmitt-trigger inverter",
)

ADS1115 = part(
    generic_name="ADS1115",
    footprint="Package_SO:VSSOP-10_3x3mm_P0.5mm",
    pins={
        1: ("ADDR", "input"),
        2: ("ALERT", "no_connect"),
        3: ("GND", "power_in"),
        4: ("AIN0", "input"),
        5: ("AIN1", "input"),
        6: ("AIN2", "input"),
        7: ("AIN3", "input"),
        8: ("SDA", "bidirectional"),
        9: ("SCL", "input"),
        10: ("VDD", "power_in"),
    },
    category="ADC",
    symbol="Analog_ADC:ADS1115IDGS",
    package="VSSOP-10",
    mpn="ADS1115IDGSR",
    description="TI ADS1115 16-bit I2C ADC",
)

MAX6675 = part(
    generic_name="MAX6675_MOD",
    footprint="Connector_PinHeader_2.54mm:PinHeader_1x05_P2.54mm_Vertical",
    pins={
        1: ("VCC", "power_in"),
        2: ("GND", "power_in"),
        3: ("SO", "output"),
        4: ("SCK", "input"),
        5: ("CS", "input"),
    },
    category="Sensor",
    symbol="Connector:Conn_01x05_Pin",
    package="module",
    mpn="MAX6675",
    description="MAX6675 K-type thermocouple module (header stand-in)",
)

MAX485 = part(
    generic_name="MAX485",
    footprint="Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
    pins={
        1: ("RO", "output"),
        2: ("RE", "input"),
        3: ("DE", "input"),
        4: ("DI", "input"),
        5: ("GND", "power_in"),
        6: ("A", "bidirectional"),
        7: ("B", "bidirectional"),
        8: ("VCC", "power_in"),
    },
    category="Interface",
    symbol="Interface_UART:MAX485E",
    package="SOIC-8",
    mpn="MAX485ESA+",
    description="5 V RS-485 transceiver",
)

MAX1044 = part(
    generic_name="MAX1044",
    footprint="Package_DIP:DIP-8_W7.62mm",
    pins={
        1: ("NC", "no_connect"),
        2: ("CAP+", "passive"),
        3: ("GND", "power_in"),
        4: ("CAP-", "passive"),
        5: ("VOUT", "power_out"),
        6: ("LV", "input"),
        7: ("OSC", "input"),
        8: ("V+", "power_in"),
    },
    category="Regulator",
    symbol="Regulator_SwitchedCapacitor:MAX1044",
    package="DIP-8",
    mpn="MAX1044CPA+",
    description="MAX1044 switched-capacitor inverter",
)

MOC3021 = part(
    generic_name="MOC3021M",
    footprint="Package_DIP:DIP-6_W7.62mm",
    pins={
        1: ("A", "passive"),
        2: ("K", "passive"),
        3: ("NC3", "no_connect"),
        4: ("MT1", "passive"),
        5: ("NC5", "no_connect"),
        6: ("MT2", "passive"),
    },
    category="Isolator",
    symbol="Relay_SolidState:MOC3021M",
    package="DIP-6",
    mpn="MOC3021M",
    description="MOC3021M random-phase opto-triac",
)

BT137 = part(
    generic_name="BT137",
    footprint="Package_TO_SOT_THT:TO-220-3_Vertical",
    pins={
        1: ("A1", "passive"),
        2: ("A2", "passive"),
        3: ("G", "passive"),
    },
    category="Power",
    symbol="Triac_Thyristor:BT136-800",
    package="TO-220",
    mpn="BT137-800",
    description="BT137-800 TRIAC (BT136-800 symbol)",
)

HALL = part(
    generic_name="A3144",
    footprint="Package_TO_SOT_SMD:SOT-23W",
    pins={
        1: ("VCC", "power_in"),
        2: ("VOUT", "open_collector"),
        3: ("GND", "power_in"),
    },
    category="Sensor",
    symbol="Sensor_Magnetic:A1101xLH",
    package="SOT-23W",
    mpn="A3144",
    description="Unipolar Hall switch (A3144 / A1101)",
)

TERM2 = part(
    generic_name="TERM_2",
    footprint="TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-1,5-2_1x02_P5.00mm_Horizontal",
    pins={1: ("1", "passive"), 2: ("2", "passive")},
    category="Connector",
    symbol="Connector:Screw_Terminal_01x02",
    package="TB",
    description="2-way screw terminal",
)

SW_SPST = part(
    generic_name="SW_SPST",
    footprint="Button_Switch_THT:SW_PUSH_6mm",
    pins={1: ("A", "passive"), 2: ("B", "passive")},
    category="Switch",
    symbol="Switch:SW_SPST",
    package="6mm",
    description="SPST switch",
)

SERVO = part(
    generic_name="SERVO_3P",
    footprint="Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical",
    pins={1: ("PWM", "input"), 2: ("V+", "power_in"), 3: ("GND", "power_in")},
    category="Connector",
    symbol="Connector:Conn_01x03_Pin",
    package="servo",
    description="Hobby servo header",
)

AC_LOAD = part(
    generic_name="AC_MOTOR",
    footprint="TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-1,5-2_1x02_P5.00mm_Horizontal",
    pins={1: ("1", "passive"), 2: ("2", "passive")},
    category="Connector",
    symbol="Connector:Screw_Terminal_01x02",
    package="TB",
    description="AC motor / heater terminals",
)

NANO = part(
    generic_name="Arduino_Nano",
    footprint="Module:Arduino_Nano",
    pins={
        1: ("D1_TX", "bidirectional"),
        2: ("D0_RX", "bidirectional"),
        3: ("RST2", "input"),
        4: ("GND1", "power_in"),
        5: ("D2", "bidirectional"),
        6: ("D3", "bidirectional"),
        7: ("D4", "bidirectional"),
        8: ("D5", "bidirectional"),
        9: ("D6", "bidirectional"),
        10: ("D7", "bidirectional"),
        11: ("D8", "bidirectional"),
        12: ("D9", "bidirectional"),
        13: ("D10", "bidirectional"),
        14: ("D11", "bidirectional"),
        15: ("D12", "bidirectional"),
        16: ("D13", "bidirectional"),
        17: ("3V3", "power_out"),
        18: ("AREF", "passive"),
        19: ("A0", "bidirectional"),
        20: ("A1", "bidirectional"),
        21: ("A2", "bidirectional"),
        22: ("A3", "bidirectional"),
        23: ("A4", "bidirectional"),
        24: ("A5", "bidirectional"),
        25: ("A6", "bidirectional"),
        26: ("A7", "bidirectional"),
        27: ("P5V", "power_out"),
        28: ("RST1", "input"),
        29: ("GND2", "power_in"),
        30: ("VIN", "power_in"),
    },
    category="Microcontroller",
    symbol="MCU_Module:Arduino_Nano_v3.x",
    package="Nano",
    mpn="Arduino_Nano_v3",
    description="Arduino Nano v3",
)

NANO_EVERY = part(
    generic_name="Arduino_Nano_Every",
    footprint="Module:Arduino_Nano",
    pins={
        1: ("D1_TX", "bidirectional"),
        2: ("D0_RX", "bidirectional"),
        3: ("RST2", "input"),
        4: ("GND1", "power_in"),
        5: ("D2", "bidirectional"),
        6: ("D3", "bidirectional"),
        7: ("D4", "bidirectional"),
        8: ("D5", "bidirectional"),
        9: ("D6", "bidirectional"),
        10: ("D7", "bidirectional"),
        11: ("D8", "bidirectional"),
        12: ("D9", "bidirectional"),
        13: ("D10", "bidirectional"),
        14: ("MOSI", "bidirectional"),
        15: ("MISO", "bidirectional"),
        16: ("SCK", "bidirectional"),
        17: ("3V3", "power_out"),
        18: ("AREF", "passive"),
        19: ("A0", "bidirectional"),
        20: ("A1", "bidirectional"),
        21: ("A2", "bidirectional"),
        22: ("A3", "bidirectional"),
        23: ("A4_SDA", "bidirectional"),
        24: ("A5_SCL", "bidirectional"),
        25: ("A6", "bidirectional"),
        26: ("A7", "bidirectional"),
        27: ("P5V", "power_out"),
        28: ("RST1", "input"),
        29: ("GND2", "power_in"),
        30: ("VIN", "power_in"),
    },
    category="Microcontroller",
    symbol="MCU_Module:Arduino_Nano_Every",
    package="Nano",
    mpn="Arduino_Nano_Every",
    description="Arduino Nano Every",
)

# Minimal Mega 2560: used pins from the Fundi schematic, 2.54 mm header (KiCad 3D).
MEGA = part(
    generic_name="Arduino_Mega2560",
    footprint="Connector_PinHeader_2.54mm:PinHeader_1x23_P2.54mm_Vertical",
    pins={
        1: ("P5V", "power_out"),
        2: ("D3", "bidirectional"),
        3: ("D6", "bidirectional"),
        4: ("D7", "bidirectional"),
        5: ("D8", "bidirectional"),
        6: ("D19", "bidirectional"),
        7: ("D20", "bidirectional"),
        8: ("D21", "bidirectional"),
        9: ("A0", "bidirectional"),
        10: ("A1", "bidirectional"),
        11: ("A2", "bidirectional"),
        12: ("A3", "bidirectional"),
        13: ("A4", "bidirectional"),
        14: ("A5", "bidirectional"),
        15: ("A6", "bidirectional"),
        16: ("A7", "bidirectional"),
        17: ("A8", "bidirectional"),
        18: ("A9", "bidirectional"),
        19: ("A10", "bidirectional"),
        20: ("A11", "bidirectional"),
        21: ("A14", "bidirectional"),
        22: ("A15", "bidirectional"),
        23: ("GND", "power_in"),
    },
    category="Microcontroller",
    symbol="Connector:Conn_01x22_Pin",
    package="Mega-minimal",
    mpn="Arduino_Mega_2560",
    description="Arduino Mega 2560 (pins used by Fundi schematic)",
)
