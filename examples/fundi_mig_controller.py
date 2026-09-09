#!/usr/bin/env python3
"""Fundi MIG controller — OpenHaC port from the JKUAT KiCad netlist.

Source: Fundi_Files/circuit (live sheets: root, VnI, R4).
Electrical SoT: this Board (nets + KiCad refs).

U7 is the ATmega2560 MCU (TQFP-100), not an Arduino Mega board module.
No module stand-ins. Parts without Fundi/KiCad mechanical identity
(MAX6675 modules, batteries, motors, VSIN/VDC) have empty
footprints and appear on the FAB-003 omit / enrichment list.
Verified packages live in examples/fundi_mig_overlays/.

See examples/fundi_mig_overlays/ENRICHMENT.md.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

_EX = Path(__file__).resolve().parent
_OVERLAYS = _EX / "fundi_mig_overlays"
_SPICE = _EX / "fundi_mig_spice"
os.environ.setdefault("OPENHAC_CATALOG_OVERLAY", str(_OVERLAYS))
os.environ.setdefault("OPENHAC_SPICE_MODEL_OVERLAY", str(_SPICE / "overlay.json"))
os.environ.setdefault("OPENHAC_SPICE_VENDOR_DIR", str(_SPICE))

from openhac.compiler.spice_models import reset_spice_model_registry_cache

reset_spice_model_registry_cache()

import openhac.core  # noqa: F401
from openhac.core import Board
from openhac.core.base import Component, Module
from openhac.core.net import Net


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


def mk(ref: str, data: dict, *, value: str | None = None):
    gn = str(data.get("generic_name") or ref)
    c = Component(gn, comp_data=dict(data), refdes=ref)
    part_obj = getattr(c, "part", None)
    if part_obj is not None:
        fields = getattr(part_obj, "fields", None)
        if isinstance(fields, dict):
            fp = data.get("kicad_footprint") or ""
            part_obj.footprint = fp
            fields["Footprint"] = fp
            if data.get("kicad_symbol"):
                fields["kicad_symbol"] = data["kicad_symbol"]
                fields["kiCad_symbol"] = data["kicad_symbol"]
            fields["Value"] = value if value is not None else data.get("description") or gn
            fields["OpenHaC_Source_Ref"] = ref
            if data.get("mpn"):
                fields["MPN"] = data["mpn"]
            if data.get("generic_name"):
                fields["generic_name"] = data["generic_name"]
            if data.get("category"):
                fields["category"] = data["category"]
                fields["Category"] = data["category"]
            fields["Reference"] = ref
            if not fp:
                fields["OpenHaC_Enrichment"] = "footprint_required"
        try:
            part_obj.refdes = ref
            part_obj.ref = ref
        except Exception:
            pass
    try:
        c.ref = ref
    except Exception:
        pass
    return c


def _connect(comp, pin, net):
    if net is None:
        return
    comp[pin] += net


# --- Part templates (footprint empty => no PCB stand-in) -------------------

A1101ELHL = part(
    generic_name='A1101ELHL',
    footprint='Package_TO_SOT_SMD:SOT-23W',
    pins={
        1: ('VCC', 'power_in'),
        2: ('VOUT', 'open_collector'),
        3: ('GND', 'power_in'),
    },
    category='Sensor',
    symbol='Sensor_Magnetic:A1101xLH',
    mpn='A1101ELHL',
    description='A1101ELHL',
)

AD620 = part(
    generic_name='AD620',
    footprint='Package_SO:SOIC-8_3.9x4.9mm_P1.27mm',
    pins={
        1: ('Rg', 'passive'),
        2: ('-', 'input'),
        3: ('+', 'input'),
        4: ('Vs-', 'power_in'),
        5: ('Ref', 'passive'),
        6: ('6', 'output'),
        7: ('Vs+', 'power_in'),
        8: ('Rg', 'passive'),
    },
    category='Amplifier',
    symbol='Amplifier_Instrumentation:AD620',
    mpn='AD620',
    description='AD620',
)

ADS1115 = part(
    generic_name='ads1115',
    footprint='Package_SO:VSSOP-10_3x3mm_P0.5mm',
    pins={
        1: ('Addr', 'input'),
        2: ('Alrt/Rdy', 'input'),
        3: ('GND', 'power_in'),
        4: ('A0', 'input'),
        5: ('A1', 'input'),
        6: ('A2', 'input'),
        7: ('A3', 'input'),
        8: ('SDA', 'bidirectional'),
        9: ('SCL', 'input'),
        10: ('VDD', 'power_in'),
    },
    category='ADC',
    symbol='Analog_ADC:ADS1115IDGS',
    mpn='ads1115',
    description='ads1115',
)

ATMEGA2560 = part(
    generic_name='ATMEGA2560',
    footprint='Package_QFP:TQFP-100_14x14mm_P0.5mm',
    pins={
        1: ('PG5', 'bidirectional'),
        2: ('PE0', 'bidirectional'),
        3: ('PE1', 'bidirectional'),
        4: ('PE2', 'bidirectional'),
        5: ('PE3', 'bidirectional'),
        6: ('PE4', 'bidirectional'),
        7: ('PE5', 'bidirectional'),
        8: ('PE6', 'bidirectional'),
        9: ('PE7', 'bidirectional'),
        10: ('VCC', 'power_in'),
        11: ('GND', 'power_in'),
        12: ('PH0', 'bidirectional'),
        13: ('PH1', 'bidirectional'),
        14: ('PH2', 'bidirectional'),
        15: ('PH3', 'bidirectional'),
        16: ('PH4', 'bidirectional'),
        17: ('PH5', 'bidirectional'),
        18: ('PH6', 'bidirectional'),
        19: ('PB0', 'bidirectional'),
        20: ('PB1', 'bidirectional'),
        21: ('PB2', 'bidirectional'),
        22: ('PB3', 'bidirectional'),
        23: ('PB4', 'bidirectional'),
        24: ('PB5', 'bidirectional'),
        25: ('PB6', 'bidirectional'),
        26: ('PB7', 'bidirectional'),
        27: ('PH7', 'bidirectional'),
        28: ('PG3', 'bidirectional'),
        29: ('PG4', 'bidirectional'),
        30: ('~{RESET}', 'input'),
        31: ('VCC', 'passive'),
        32: ('GND', 'passive'),
        33: ('XTAL2', 'output'),
        34: ('XTAL1', 'input'),
        35: ('PL0', 'bidirectional'),
        36: ('PL1', 'bidirectional'),
        37: ('PL2', 'bidirectional'),
        38: ('PL3', 'bidirectional'),
        39: ('PL4', 'bidirectional'),
        40: ('PL5', 'bidirectional'),
        41: ('PL6', 'bidirectional'),
        42: ('PL7', 'bidirectional'),
        43: ('PD0', 'bidirectional'),
        44: ('PD1', 'bidirectional'),
        45: ('PD2', 'bidirectional'),
        46: ('PD3', 'bidirectional'),
        47: ('PD4', 'bidirectional'),
        48: ('PD5', 'bidirectional'),
        49: ('PD6', 'bidirectional'),
        50: ('PD7', 'bidirectional'),
        51: ('PG0', 'bidirectional'),
        52: ('PG1', 'bidirectional'),
        53: ('PC0', 'bidirectional'),
        54: ('PC1', 'bidirectional'),
        55: ('PC2', 'bidirectional'),
        56: ('PC3', 'bidirectional'),
        57: ('PC4', 'bidirectional'),
        58: ('PC5', 'bidirectional'),
        59: ('PC6', 'bidirectional'),
        60: ('PC7', 'bidirectional'),
        61: ('VCC', 'passive'),
        62: ('GND', 'passive'),
        63: ('PJ0', 'bidirectional'),
        64: ('PJ1', 'bidirectional'),
        65: ('PJ2', 'bidirectional'),
        66: ('PJ3', 'bidirectional'),
        67: ('PJ4', 'bidirectional'),
        68: ('PJ5', 'bidirectional'),
        69: ('PJ6', 'bidirectional'),
        70: ('PG2', 'bidirectional'),
        71: ('PA7', 'bidirectional'),
        72: ('PA6', 'bidirectional'),
        73: ('PA5', 'bidirectional'),
        74: ('PA4', 'bidirectional'),
        75: ('PA3', 'bidirectional'),
        76: ('PA2', 'bidirectional'),
        77: ('PA1', 'bidirectional'),
        78: ('PA0', 'bidirectional'),
        79: ('PJ7', 'bidirectional'),
        80: ('VCC', 'passive'),
        81: ('GND', 'passive'),
        82: ('PK7', 'bidirectional'),
        83: ('PK6', 'bidirectional'),
        84: ('PK5', 'bidirectional'),
        85: ('PK4', 'bidirectional'),
        86: ('PK3', 'bidirectional'),
        87: ('PK2', 'bidirectional'),
        88: ('PK1', 'bidirectional'),
        89: ('PK0', 'bidirectional'),
        90: ('PF7', 'bidirectional'),
        91: ('PF6', 'bidirectional'),
        92: ('PF5', 'bidirectional'),
        93: ('PF4', 'bidirectional'),
        94: ('PF3', 'bidirectional'),
        95: ('PF2', 'bidirectional'),
        96: ('PF1', 'bidirectional'),
        97: ('PF0', 'bidirectional'),
        98: ('AREF', 'passive'),
        99: ('GND', 'passive'),
        100: ('AVCC', 'power_in'),
    },
    category='Microcontroller',
    symbol='MCU_Microchip_ATmega:ATmega2560-16A',
    mpn='ATmega2560-16AU',
    package='TQFP-100',
    description='Microchip ATmega2560 (Arduino Mega 2560 MCU)',
)

ARDUINO_NANO = part(
    generic_name='Arduino_Nano',
    footprint='Module:Arduino_Nano',
    pins={
        1: ('D1', 'bidirectional'),
        4: ('GND', 'power_in'),
        19: ('A0', 'bidirectional'),
        20: ('A1', 'bidirectional'),
        21: ('A2', 'bidirectional'),
        30: ('Vin', 'power_in'),
    },
    category='Microcontroller',
    symbol='MCU_Module:Arduino_Nano_v3.x',
    mpn='Arduino_Nano',
    description='Arduino_Nano',
)

ARDUINO_NANO_EVERY_SOCKET = part(
    generic_name='Arduino_Nano_Every_Socket',
    footprint='Module:Arduino_Nano',
    pins={
        1: ('D1/TX', 'bidirectional'),
        2: ('D0/RX', 'bidirectional'),
        3: ('RESET', 'open_collector'),
        4: ('GND', 'power_in'),
        5: ('D2', 'bidirectional'),
        6: ('D3', 'bidirectional'),
        7: ('D4', 'bidirectional'),
        8: ('D5', 'bidirectional'),
        9: ('D6', 'bidirectional'),
        10: ('D7', 'bidirectional'),
        11: ('D8', 'bidirectional'),
        12: ('D9', 'bidirectional'),
        13: ('D10', 'bidirectional'),
        14: ('D11_MOSI', 'bidirectional'),
        15: ('D12_MISO', 'bidirectional'),
        16: ('D13_SCK', 'bidirectional'),
        17: ('3.3V', 'power_out'),
        18: ('AREF', 'input'),
        19: ('A0', 'bidirectional'),
        20: ('A1', 'bidirectional'),
        21: ('A2', 'bidirectional'),
        22: ('A3', 'bidirectional'),
        23: ('A4/SDA', 'bidirectional'),
        24: ('A5/SCL', 'bidirectional'),
        25: ('A6', 'input'),
        26: ('A7', 'input'),
        27: ('5V', 'power_in'),
        28: ('RESET', 'open_collector'),
        29: ('GND', 'power_in'),
        30: ('VIN', 'power_in'),
    },
    category='Microcontroller',
    symbol='MCU_Module:Arduino_Nano_Every',
    mpn='Arduino_Nano_Every_Socket',
    description='Arduino_Nano_Every_Socket',
)

BATTERY_CELL = part(
    generic_name='Battery_Cell',
    footprint='',
    pins={
        1: ('+', 'passive'),
        2: ('-', 'passive'),
    },
    category='Power',
    symbol='Device:Battery_Cell',
    mpn='Battery_Cell',
    description='Battery_Cell',
)

BT136_800 = part(
    generic_name='BT136-800',
    footprint='Package_TO_SOT_THT:TO-220-3_Vertical',
    pins={
        1: ('A1', 'passive'),
        2: ('A2', 'passive'),
        3: ('G', 'input'),
    },
    category='Power',
    symbol='Triac_Thyristor:BT136-800',
    mpn='BT136-800',
    description='BT136-800',
)

C = part(
    generic_name='C',
    footprint='Capacitor_SMD:C_0805_2012Metric',
    pins={
        1: ('1', 'passive'),
        2: ('2', 'passive'),
    },
    category='Capacitor',
    symbol='Device:C',
    mpn='C',
    description='C',
)

C_SMALL = part(
    generic_name='C_Small',
    footprint='Capacitor_SMD:C_0805_2012Metric',
    pins={
        1: ('1', 'passive'),
        2: ('2', 'passive'),
    },
    category='Capacitor',
    symbol='Device:C',
    mpn='C_Small',
    description='C_Small',
)

D_SMALL = part(
    generic_name='D_Small',
    footprint='Diode_THT:D_DO-41_SOD81_P10.16mm_Horizontal',
    pins={
        1: ('K', 'passive'),
        2: ('A', 'passive'),
    },
    category='Diode',
    symbol='Device:D_Schottky',
    mpn='D_Small',
    description='D_Small',
)

LED = part(
    generic_name='LED',
    footprint='LED_THT:LED_D3.0mm',
    pins={
        1: ('K', 'passive'),
        2: ('A', 'passive'),
    },
    category='LED',
    symbol='Device:LED',
    mpn='LED',
    description='LED',
)

MAX1044 = part(
    generic_name='MAX1044',
    footprint='Package_DIP:DIP-8_W7.62mm',
    pins={
        1: ('NC', 'no_connect'),
        2: ('CAP+', 'passive'),
        3: ('GND', 'power_in'),
        4: ('CAP-', 'passive'),
        5: ('VOUT', 'power_out'),
        6: ('LV', 'input'),
        7: ('OSC', 'input'),
        8: ('V+', 'power_in'),
    },
    category='Regulator',
    symbol='Regulator_SwitchedCapacitor:MAX1044',
    mpn='MAX1044',
    description='MAX1044',
)

MAX485_1_1 = part(
    generic_name='max485_1_1',
    footprint='Package_SO:SOIC-8_3.9x4.9mm_P1.27mm',
    pins={
        1: ('RO', 'output'),
        2: ('~{RE}', 'no_connect'),
        3: ('DE', 'no_connect'),
        4: ('DI', 'input'),
        5: ('GND', 'power_in'),
        6: ('A', 'bidirectional'),
        7: ('B', 'bidirectional'),
        8: ('Vcc', 'power_in'),
    },
    category='Interface',
    symbol='Interface_UART:MAX485E',
    mpn='max485_1_1',
    description='max485_1_1',
)

MAX485_1_2 = part(
    generic_name='max485_1_2',
    footprint='Package_SO:SOIC-8_3.9x4.9mm_P1.27mm',
    pins={
        1: ('RO', 'output'),
        2: ('~{RE}', 'input'),
        3: ('DE', 'no_connect'),
        4: ('DI', 'input'),
        5: ('GND', 'no_connect'),
        6: ('A', 'bidirectional'),
        7: ('B', 'bidirectional'),
        8: ('Vcc', 'power_in'),
    },
    category='Interface',
    symbol='Interface_UART:MAX485E',
    mpn='max485_1_2',
    description='max485_1_2',
)

MAX485_1_3 = part(
    generic_name='max485_1_3',
    footprint='Package_SO:SOIC-8_3.9x4.9mm_P1.27mm',
    pins={
        1: ('RO', 'output'),
        2: ('~{RE}', 'input'),
        3: ('DE', 'no_connect'),
        4: ('DI', 'input'),
        5: ('GND', 'no_connect'),
        6: ('A', 'bidirectional'),
        7: ('B', 'bidirectional'),
        8: ('Vcc', 'power_in'),
    },
    category='Interface',
    symbol='Interface_UART:MAX485E',
    mpn='max485_1_3',
    description='max485_1_3',
)

MAX485_1_4 = part(
    generic_name='max485_1_4',
    footprint='Package_SO:SOIC-8_3.9x4.9mm_P1.27mm',
    pins={
        1: ('RO', 'output'),
        2: ('~{RE}', 'no_connect'),
        3: ('DE', 'no_connect'),
        4: ('DI', 'input'),
        5: ('GND', 'power_in'),
        6: ('A', 'bidirectional'),
        7: ('B', 'bidirectional'),
        8: ('Vcc', 'power_in'),
    },
    category='Interface',
    symbol='Interface_UART:MAX485E',
    mpn='max485_1_4',
    description='max485_1_4',
)

MAX6675_THERMOCOUPLE_MODULE = part(
    generic_name='max6675_thermocouple_module',
    footprint='',
    pins={
        'CS': ('CS', 'input'),
        'GND': ('GND', 'power_in'),
        'SCK': ('SCK', 'input'),
        'SO': ('SO', 'open_collector'),
        'Vcc': ('Vcc', 'power_in'),
    },
    category='Sensor',
    symbol='Device:R',
    mpn='max6675_thermocouple_module',
    description='max6675_thermocouple_module',
)

MAX6675_THERMOCOUPLE_MODULE_1 = part(
    generic_name='max6675_thermocouple_module_1',
    footprint='',
    pins={
        'CS': ('CS', 'input'),
        'GND': ('GND', 'power_in'),
        'SCK': ('SCK', 'input'),
        'SO': ('SO', 'open_collector'),
        'Vcc': ('Vcc', 'power_in'),
    },
    category='Sensor',
    symbol='Device:R',
    mpn='max6675_thermocouple_module_1',
    description='max6675_thermocouple_module_1',
)

MAX6675_THERMOCOUPLE_MODULE_2 = part(
    generic_name='max6675_thermocouple_module_2',
    footprint='',
    pins={
        'CS': ('CS', 'input'),
        'GND': ('GND', 'power_in'),
        'SCK': ('SCK', 'input'),
        'SO': ('SO', 'open_collector'),
        'Vcc': ('Vcc', 'power_in'),
    },
    category='Sensor',
    symbol='Device:R',
    mpn='max6675_thermocouple_module_2',
    description='max6675_thermocouple_module_2',
)

MAX6675_THERMOCOUPLE_MODULE_3 = part(
    generic_name='max6675_thermocouple_module_3',
    footprint='',
    pins={
        'CS': ('CS', 'input'),
        'GND': ('GND', 'power_in'),
        'SCK': ('SCK', 'input'),
        'SO': ('SO', 'open_collector'),
        'Vcc': ('Vcc', 'power_in'),
    },
    category='Sensor',
    symbol='Device:R',
    mpn='max6675_thermocouple_module_3',
    description='max6675_thermocouple_module_3',
)

MAX6675_THERMOCOUPLE_MODULE_4 = part(
    generic_name='max6675_thermocouple_module_4',
    footprint='',
    pins={
        'CS': ('CS', 'input'),
        'GND': ('GND', 'power_in'),
        'SCK': ('SCK', 'input'),
        'SO': ('SO', 'open_collector'),
        'Vcc': ('Vcc', 'power_in'),
    },
    category='Sensor',
    symbol='Device:R',
    mpn='max6675_thermocouple_module_4',
    description='max6675_thermocouple_module_4',
)

MOC3021M = part(
    generic_name='MOC3021M',
    footprint='Package_DIP:DIP-6_W7.62mm',
    pins={
        1: ('1', 'passive'),
        2: ('2', 'passive'),
        3: ('NC', 'no_connect'),
        4: ('4', 'passive'),
        5: ('NC', 'no_connect'),
        6: ('6', 'passive'),
    },
    category='Isolator',
    symbol='Relay_SolidState:MOC3021M',
    mpn='MOC3021M',
    description='MOC3021M',
)

MOTOR_AC = part(
    generic_name='Motor_AC',
    footprint='',
    pins={
        1: ('1', 'passive'),
        2: ('2', 'passive'),
    },
    category='Motor',
    symbol='Motor:Motor_AC',
    mpn='Motor_AC',
    description='Motor_AC',
)

MOTOR_SERVO = part(
    generic_name='Motor_Servo',
    footprint='',
    pins={
        1: ('PWM', 'passive'),
        2: ('+', 'passive'),
        3: ('-', 'passive'),
    },
    category='Motor',
    symbol='Motor:Motor_Servo',
    mpn='Motor_Servo',
    description='Motor_Servo',
)

PC817 = part(
    generic_name='PC817',
    footprint='Package_DIP:DIP-4_W7.62mm',
    pins={
        1: ('1', 'passive'),
        2: ('2', 'passive'),
        3: ('3', 'passive'),
        4: ('4', 'passive'),
    },
    category='Isolator',
    symbol='Isolator:PC817',
    mpn='PC817',
    description='PC817',
)

P_1N4007 = part(
    generic_name='1N4007',
    footprint='Diode_THT:D_DO-41_SOD81_P10.16mm_Horizontal',
    pins={
        1: ('K', 'passive'),
        2: ('A', 'passive'),
    },
    category='Diode',
    symbol='Device:D',
    mpn='1N4007',
    description='1N4007',
)

P_74HC14 = part(
    generic_name='74HC14',
    footprint='Package_DIP:DIP-14_W7.62mm',
    pins={
        1: ('1', 'input'),
        2: ('2', 'output'),
        7: ('GND', 'power_in'),
        12: ('12', 'output'),
        13: ('13', 'input'),
        14: ('VCC', 'power_in'),
    },
    category='Logic',
    symbol='74xx:74HC14',
    mpn='74HC14',
    description='74HC14',
)

R = part(
    generic_name='R',
    footprint='Resistor_SMD:R_0805_2012Metric',
    pins={
        1: ('1', 'passive'),
        2: ('2', 'passive'),
    },
    category='Resistor',
    symbol='Device:R',
    mpn='R',
    description='R',
)

R_POTENTIOMETER = part(
    generic_name='R_Potentiometer',
    footprint='Potentiometer_THT:Potentiometer_Bourns_3296W_Vertical',
    pins={
        1: ('1', 'passive'),
        2: ('2', 'passive'),
        3: ('3', 'passive'),
    },
    category='Potentiometer',
    symbol='Device:R_Potentiometer',
    mpn='R_Potentiometer',
    description='R_Potentiometer',
)

R_SMALL = part(
    generic_name='R_Small',
    footprint='Resistor_SMD:R_0805_2012Metric',
    pins={
        1: ('1', 'passive'),
        2: ('2', 'passive'),
    },
    category='Resistor',
    symbol='Device:R',
    mpn='R_Small',
    description='R_Small',
)

SCREW_TERMINAL_01X02 = part(
    generic_name='Screw_Terminal_01x02',
    footprint='TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-1,5-2_1x02_P5.00mm_Horizontal',
    pins={
        1: ('Pin_1', 'passive'),
        2: ('Pin_2', 'passive'),
    },
    category='Connector',
    symbol='Connector:Screw_Terminal_01x02',
    mpn='Screw_Terminal_01x02',
    description='Screw_Terminal_01x02',
)

SW_SPST = part(
    generic_name='SW_SPST',
    footprint='Button_Switch_THT:SW_PUSH_6mm',
    pins={
        1: ('A', 'passive'),
        2: ('B', 'passive'),
    },
    category='Switch',
    symbol='Switch:SW_SPST',
    mpn='SW_SPST',
    description='SW_SPST',
)

VDC = part(
    generic_name='VDC',
    footprint='',
    pins={
        1: ('1', 'passive'),
        2: ('2', 'passive'),
    },
    category='Power',
    symbol='Device:Battery_Cell',
    mpn='VDC',
    description='VDC',
)

VSIN = part(
    generic_name='VSIN',
    footprint='',
    pins={
        1: ('1', 'passive'),
        2: ('2', 'passive'),
    },
    category='Power',
    symbol='Device:Battery_Cell',
    mpn='VSIN',
    description='VSIN',
)

class Root(Module):
    """Root schematic — power, Mega, Nano R1, R2/R3, triac, WFS"""

    def __init__(self, N: dict[str, Net]) -> None:
        super().__init__('Root')
        self.BT1 = self.add(mk('BT1', BATTERY_CELL, value='9V cells'))
        self.BT2 = self.add(mk('BT2', BATTERY_CELL, value='Battery_Cell'))
        self.BT3 = self.add(mk('BT3', BATTERY_CELL, value='9V and 5V buck'))
        self.BT5 = self.add(mk('BT5', BATTERY_CELL, value='Li-ion'))
        self.C1 = self.add(mk('C1', C, value='0.1u'))
        self.C2 = self.add(mk('C2', C, value='0.1u'))
        self.C3 = self.add(mk('C3', C_SMALL, value='1u'))
        self.C4 = self.add(mk('C4', C_SMALL, value='100n'))
        self.C5 = self.add(mk('C5', C_SMALL, value='1u'))
        self.C6 = self.add(mk('C6', C_SMALL, value='100n'))
        self.C7 = self.add(mk('C7', C_SMALL, value='100n'))
        self.C8 = self.add(mk('C8', C_SMALL, value='100n'))
        self.D1 = self.add(mk('D1', P_1N4007, value='1N4007'))
        self.D10 = self.add(mk('D10', D_SMALL, value='1n5819'))
        self.D2 = self.add(mk('D2', P_1N4007, value='1N4007'))
        self.D3 = self.add(mk('D3', P_1N4007, value='1N4007'))
        self.D4 = self.add(mk('D4', P_1N4007, value='1N4007'))
        self.D5 = self.add(mk('D5', D_SMALL, value='1n5819'))
        self.D6 = self.add(mk('D6', D_SMALL, value='1n5819'))
        self.D7 = self.add(mk('D7', LED, value='LED'))
        self.D8 = self.add(mk('D8', LED, value='LED'))
        self.D9 = self.add(mk('D9', D_SMALL, value='1n5819'))
        self.J1 = self.add(mk('J1', SCREW_TERMINAL_01X02, value='MIG-Torch'))
        self.J2 = self.add(mk('J2', SCREW_TERMINAL_01X02, value='MIG-Shunt'))
        self.M2 = self.add(mk('M2', MOTOR_SERVO, value='Motor_Servo'))
        self.M4 = self.add(mk('M4', MOTOR_AC, value='Motor_AC'))
        self.Q1 = self.add(mk('Q1', BT136_800, value='BT137'))
        self.R1 = self.add(mk('R1', R, value='50k'))
        self.R10 = self.add(mk('R10', R, value='1M'))
        self.R11 = self.add(mk('R11', R, value='1M'))
        self.R12 = self.add(mk('R12', R, value='1M'))
        self.R13 = self.add(mk('R13', R, value='1M'))
        self.R14 = self.add(mk('R14', R, value='440R'))
        self.R15 = self.add(mk('R15', R, value='440R'))
        self.R16 = self.add(mk('R16', R, value='2k2'))
        self.R17 = self.add(mk('R17', R, value='2k2'))
        self.R18 = self.add(mk('R18', R, value='135R'))
        self.R19 = self.add(mk('R19', R, value='135R'))
        self.R2 = self.add(mk('R2', R, value='100k'))
        self.R20 = self.add(mk('R20', R, value='135R'))
        self.R21 = self.add(mk('R21', R, value='135R'))
        self.R22 = self.add(mk('R22', R, value='330R'))
        self.R23 = self.add(mk('R23', R, value='330R'))
        self.R24 = self.add(mk('R24', R, value='10k'))
        self.R25 = self.add(mk('R25', R, value='2k2'))
        self.R26 = self.add(mk('R26', R, value='3k'))
        self.R27 = self.add(mk('R27', R, value='3k'))
        self.R28 = self.add(mk('R28', R, value='2k2'))
        self.R29 = self.add(mk('R29', R, value='3k'))
        self.R3 = self.add(mk('R3', R, value='50k'))
        self.R30 = self.add(mk('R30', R, value='82k'))
        self.R31 = self.add(mk('R31', R, value='5k'))
        self.R32 = self.add(mk('R32', R, value='5k'))
        self.R33 = self.add(mk('R33', R, value='330R'))
        self.R34 = self.add(mk('R34', R, value='330R'))
        self.R35 = self.add(mk('R35', R, value='330R'))
        self.R36 = self.add(mk('R36', R, value='220R'))
        self.R37 = self.add(mk('R37', R, value='3k'))
        self.R38 = self.add(mk('R38', R_SMALL, value='5k'))
        self.R39 = self.add(mk('R39', R_SMALL, value='5k'))
        self.R4 = self.add(mk('R4', R, value='100k'))
        self.R5 = self.add(mk('R5', R, value='1M'))
        self.R6 = self.add(mk('R6', R, value='1k'))
        self.R7 = self.add(mk('R7', R, value='1k'))
        self.R8 = self.add(mk('R8', R, value='330'))
        self.R9 = self.add(mk('R9', R, value='330'))
        self.RV1 = self.add(mk('RV1', R_POTENTIOMETER, value='Pot'))
        self.SW1 = self.add(mk('SW1', SW_SPST, value='SW_SPST'))
        self.U1 = self.add(mk('U1', AD620, value='AD620'))
        self.U10 = self.add(mk('U10', PC817, value='PC817'))
        self.U11 = self.add(mk('U11', PC817, value='PC817'))
        self.U12 = self.add(mk('U12', PC817, value='PC817'))
        self.U13 = self.add(mk('U13', PC817, value='PC817'))
        self.U14 = self.add(mk('U14', PC817, value='PC817'))
        self.U15 = self.add(mk('U15', MAX485_1_1, value='max485_1_1'))
        self.U16 = self.add(mk('U16', P_74HC14, value='74HC14_data'))
        self.U17 = self.add(mk('U17', ADS1115, value='ads1115'))
        self.U18 = self.add(mk('U18', P_74HC14, value='74HC14_power'))
        self.U19 = self.add(mk('U19', ARDUINO_NANO, value='Arduino_Nano'))
        self.U2 = self.add(mk('U2', AD620, value='AD620'))
        self.U20 = self.add(mk('U20', PC817, value='PC817'))
        self.U21 = self.add(mk('U21', MAX6675_THERMOCOUPLE_MODULE_2, value='max6675_thermocouple_module_2'))
        self.U22 = self.add(mk('U22', MAX485_1_2, value='max485_1_2'))
        self.U24 = self.add(mk('U24', P_74HC14, value='74HC14_power'))
        self.U25 = self.add(mk('U25', MAX6675_THERMOCOUPLE_MODULE_1, value='max6675_thermocouple_module_1'))
        self.U3 = self.add(mk('U3', PC817, value='PC817'))
        self.U4 = self.add(mk('U4', MAX6675_THERMOCOUPLE_MODULE, value='max6675_thermocouple_module'))
        self.U5 = self.add(mk('U5', PC817, value='PC817'))
        self.U6 = self.add(mk('U6', A1101ELHL, value='A3144'))
        self.U7 = self.add(mk('U7', ATMEGA2560, value='ATmega2560-16AU'))
        self.U8 = self.add(mk('U8', MOC3021M, value='MOC3021M'))
        self.U9 = self.add(mk('U9', PC817, value='PC817'))
        self.V1 = self.add(mk('V1', VDC, value='5V'))
        self.V2 = self.add(mk('V2', VSIN, value='240Vrms'))
        self.V3 = self.add(mk('V3', VDC, value='5V'))

        # Netlist wiring
        _connect(self.BT1, 1, N['P9V'])
        _connect(self.BT1, 2, N['GND3'])
        _connect(self.BT2, 1, N['GND3'])
        _connect(self.BT2, 2, N['N9V'])
        _connect(self.BT3, 1, N['P5V_VnI'])
        _connect(self.BT3, 2, N['GND3'])
        _connect(self.BT5, 1, N['P5V_Li_ion'])
        _connect(self.BT5, 2, N['GND2'])
        _connect(self.C1, 1, N['P5V_sens'])
        _connect(self.C1, 2, N['GND'])
        _connect(self.C2, 1, N['P5V_servo'])
        _connect(self.C2, 2, N['GND'])
        _connect(self.C3, 1, N['Net_U2'])
        _connect(self.C3, 2, N['Net_U2_P'])
        _connect(self.C4, 1, N['GND3'])
        _connect(self.C4, 2, N['Net_U1'])
        _connect(self.C5, 1, N['Net_U1'])
        _connect(self.C5, 2, N['Net_U1_P'])
        _connect(self.C6, 1, N['Net_U1_P'])
        _connect(self.C6, 2, N['GND3'])
        _connect(self.C7, 1, N['Net_U2_P'])
        _connect(self.C7, 2, N['GND3'])
        _connect(self.C8, 1, N['GND3'])
        _connect(self.C8, 2, N['Net_U2'])
        _connect(self.D1, 1, N['Net_D1_K'])
        _connect(self.D1, 2, N['Net_D1_A'])
        _connect(self.D10, 1, N['Net_D10_K'])
        _connect(self.D10, 2, N['SDA'])
        _connect(self.D2, 1, N['Net_D2_K'])
        _connect(self.D2, 2, N['Net_D1_A'])
        _connect(self.D3, 1, N['Net_D3_K'])
        _connect(self.D3, 2, N['Net_D1_K'])
        _connect(self.D4, 1, N['Net_D3_K'])
        _connect(self.D4, 2, N['Net_D2_K'])
        _connect(self.D5, 1, N['Net_D5_K'])
        _connect(self.D5, 2, N['SCL_isolated'])
        _connect(self.D6, 1, N['Net_D6_K'])
        _connect(self.D6, 2, N['SDA_isolated'])
        _connect(self.D7, 1, N['GND3'])
        _connect(self.D7, 2, N['Net_D7_A'])
        _connect(self.D8, 1, N['GND3'])
        _connect(self.D8, 2, N['Net_D8_A'])
        _connect(self.D9, 1, N['Net_D9_K'])
        _connect(self.D9, 2, N['SCL'])
        _connect(self.J1, 1, N['Net_J1_Pin_1'])
        _connect(self.J1, 2, N['Net_J1_Pin_2'])
        _connect(self.J2, 1, N['Net_J2_Pin_1'])
        _connect(self.J2, 2, N['Net_J2_Pin_2'])
        _connect(self.M2, 1, N['SERVO2'])
        _connect(self.M2, 2, N['P5V_servo'])
        _connect(self.M2, 3, N['GND'])
        _connect(self.M4, 1, N['Net_Q1_A1'])
        _connect(self.M4, 2, N['AC'])
        _connect(self.Q1, 1, N['Net_Q1_A1'])
        _connect(self.Q1, 2, N['ACP'])
        _connect(self.Q1, 3, N['Net_Q1_G'])
        _connect(self.R1, 1, N['AC'])
        _connect(self.R1, 2, N['Net_D2_K'])
        _connect(self.R10, 1, N['GND3'])
        _connect(self.R10, 2, N['Net_U1'])
        _connect(self.R11, 1, N['GND3'])
        _connect(self.R11, 2, N['Net_U2'])
        _connect(self.R12, 1, N['GND3'])
        _connect(self.R12, 2, N['Net_U1_P'])
        _connect(self.R13, 1, N['GND3'])
        _connect(self.R13, 2, N['Net_U2_P'])
        _connect(self.R14, 1, N['Net_R14_Pad1'])
        _connect(self.R14, 2, N['Net_U17_A2'])
        _connect(self.R15, 1, N['Net_U17_A0'])
        _connect(self.R15, 2, N['Net_R15_Pad2'])
        _connect(self.R16, 1, N['P5V_VnI'])
        _connect(self.R16, 2, N['SCL_isolated'])
        _connect(self.R17, 1, N['P5V_VnI'])
        _connect(self.R17, 2, N['SDA_isolated'])
        _connect(self.R18, 1, N['P5V_VnI'])
        _connect(self.R18, 2, N['Net_D6_K'])
        _connect(self.R19, 1, N['P5V_VnI'])
        _connect(self.R19, 2, N['Net_D5_K'])
        _connect(self.R2, 1, N['Net_R2_Pad1'])
        _connect(self.R2, 2, N['Net_J1_Pin_2'])
        _connect(self.R20, 1, N['P5V_sens'])
        _connect(self.R20, 2, N['Net_D9_K'])
        _connect(self.R21, 1, N['P5V_sens'])
        _connect(self.R21, 2, N['Net_D10_K'])
        _connect(self.R22, 1, N['P5V_sens'])
        _connect(self.R22, 2, N['Net_R22_Pad2'])
        _connect(self.R23, 1, N['P5V_sens'])
        _connect(self.R23, 2, N['Net_R23_Pad2'])
        _connect(self.R24, 1, N['P5V_sens'])
        _connect(self.R24, 2, N['T1SO'])
        _connect(self.R25, 1, N['P5V_sens'])
        _connect(self.R25, 2, N['SCL'])
        _connect(self.R26, 1, N['Net_R26_Pad1'])
        _connect(self.R26, 2, N['P5V_Li_ion'])
        _connect(self.R27, 1, N['Net_U4_CS'])
        _connect(self.R27, 2, N['P5V_Li_ion'])
        _connect(self.R28, 1, N['P5V_sens'])
        _connect(self.R28, 2, N['SDA'])
        _connect(self.R29, 1, N['P5V_Li_ion'])
        _connect(self.R29, 2, N['Net_R29_Pad2'])
        _connect(self.R3, 1, N['ACP'])
        _connect(self.R3, 2, N['Net_D1_K'])
        _connect(self.R30, 1, N['Net_R30_Pad1'])
        _connect(self.R30, 2, N['Net_J1_Pin_2'])
        _connect(self.R31, 1, N['Net_U1'])
        _connect(self.R31, 2, N['Net_R30_Pad1'])
        _connect(self.R32, 1, N['Net_U1_P'])
        _connect(self.R32, 2, N['Net_R2_Pad1'])
        _connect(self.R33, 1, N['Net_U19_D1'])
        _connect(self.R33, 2, N['Net_R33_Pad2'])
        _connect(self.R34, 1, N['Net_R34_Pad1'])
        _connect(self.R34, 2, N['P9V'])
        _connect(self.R35, 1, N['Net_D7_A'])
        _connect(self.R35, 2, N['Net_R34_Pad1'])
        _connect(self.R36, 1, N['Net_D8_A'])
        _connect(self.R36, 2, N['P5V_VnI'])
        _connect(self.R37, 1, N['Net_R37_Pad1'])
        _connect(self.R37, 2, N['P5V_sens'])
        _connect(self.R38, 1, N['Net_J2_Pin_2'])
        _connect(self.R38, 2, N['Net_U2'])
        _connect(self.R39, 1, N['Net_J2_Pin_1'])
        _connect(self.R39, 2, N['Net_U2_P'])
        _connect(self.R4, 1, N['Net_R4_Pad1'])
        _connect(self.R4, 2, N['Net_R2_Pad1'])
        _connect(self.R5, 1, N['Net_J1_Pin_1'])
        _connect(self.R5, 2, N['Net_R4_Pad1'])
        _connect(self.R6, 2, N['ZERO'])
        _connect(self.R7, 1, N['P5V_sens'])
        _connect(self.R7, 2, N['HALL'])
        _connect(self.R8, 1, N['TRIAC'])
        _connect(self.R8, 2, N['Net_R8_Pad2'])
        _connect(self.R9, 1, N['Net_R9_Pad1'])
        _connect(self.R9, 2, N['ACP'])
        _connect(self.RV1, 2, N['Net_RV1_Pad2'])
        _connect(self.RV1, 3, N['Net_RV1_Pad3'])
        _connect(self.SW1, 1, N['Net_SW1_A'])
        _connect(self.SW1, 2, N['ACP'])
        _connect(self.U1, 2, N['Net_U1'])
        _connect(self.U1, 3, N['Net_U1_P'])
        _connect(self.U1, 4, N['N9V'])
        _connect(self.U1, 5, N['GND3'])
        _connect(self.U1, 6, N['Net_R15_Pad2'])
        _connect(self.U1, 7, N['P9V'])
        _connect(self.U10, 1, N['Net_D10_K'])
        _connect(self.U10, 2, N['SDA'])
        _connect(self.U10, 3, N['GND3'])
        _connect(self.U10, 4, N['Net_D6_K'])
        _connect(self.U11, 1, N['Net_D6_K'])
        _connect(self.U11, 2, N['SDA_isolated'])
        _connect(self.U11, 3, N['GND'])
        _connect(self.U11, 4, N['Net_D10_K'])
        _connect(self.U12, 1, N['Net_R22_Pad2'])
        _connect(self.U12, 2, N['T1SCK'])
        _connect(self.U12, 3, N['GND2'])
        _connect(self.U12, 4, N['Net_R26_Pad1'])
        _connect(self.U13, 1, N['Net_R23_Pad2'])
        _connect(self.U13, 2, N['T1CS'])
        _connect(self.U13, 3, N['GND2'])
        _connect(self.U13, 4, N['Net_U4_CS'])
        _connect(self.U14, 1, N['Net_R29_Pad2'])
        _connect(self.U14, 2, N['Net_U4_SO'])
        _connect(self.U14, 3, N['GND'])
        _connect(self.U14, 4, N['T1SO'])
        _connect(self.U15, 4, N['Net_U15_DI'])
        _connect(self.U15, 5, N['GND'])
        _connect(self.U15, 6, N['DP'])
        _connect(self.U15, 7, N['D'])
        _connect(self.U15, 8, N['P5V_sens'])
        _connect(self.U16, 1, N['Net_R26_Pad1'])
        _connect(self.U16, 2, N['Net_U4_SCK'])
        _connect(self.U16, 12, N['Net_U15_DI'])
        _connect(self.U16, 13, N['Net_R37_Pad1'])
        _connect(self.U17, 3, N['GND3'])
        _connect(self.U17, 4, N['Net_U17_A0'])
        _connect(self.U17, 6, N['Net_U17_A2'])
        _connect(self.U17, 8, N['SDA_isolated'])
        _connect(self.U17, 9, N['SCL_isolated'])
        _connect(self.U17, 10, N['P5V_VnI'])
        _connect(self.U18, 7, N['GND2'])
        _connect(self.U18, 14, N['P5V_Li_ion'])
        _connect(self.U19, 1, N['Net_U19_D1'])
        _connect(self.U19, 4, N['GND2'])
        _connect(self.U19, 19, N['Net_U19_A0'])
        _connect(self.U19, 20, N['Net_U19_A1'])
        _connect(self.U19, 21, N['Net_U19_A2'])
        _connect(self.U19, 30, N['P5V_Li_ion'])
        _connect(self.U2, 1, N['Net_RV1_Pad2'])
        _connect(self.U2, 2, N['Net_U2'])
        _connect(self.U2, 3, N['Net_U2_P'])
        _connect(self.U2, 4, N['N9V'])
        _connect(self.U2, 5, N['GND3'])
        _connect(self.U2, 6, N['Net_R14_Pad1'])
        _connect(self.U2, 7, N['P9V'])
        _connect(self.U2, 8, N['Net_RV1_Pad3'])
        _connect(self.U20, 1, N['Net_R33_Pad2'])
        _connect(self.U20, 2, N['GND2'])
        _connect(self.U20, 3, N['GND'])
        _connect(self.U20, 4, N['Net_R37_Pad1'])
        _connect(self.U21, 'CS', N['T1CS'])
        _connect(self.U21, 'GND', N['GND'])
        _connect(self.U21, 'SCK', N['T1SCK'])
        _connect(self.U21, 'SO', N['T1SO'])
        _connect(self.U21, 'Vcc', N['P5V_sens'])
        _connect(self.U22, 1, N['DAT'])
        _connect(self.U22, 2, N['GND'])
        _connect(self.U22, 6, N['DP'])
        _connect(self.U22, 7, N['D'])
        _connect(self.U22, 8, N['P5V_sens'])
        _connect(self.U24, 7, N['GND'])
        _connect(self.U24, 14, N['P5V_sens'])
        _connect(self.U25, 'CS', N['Net_U19_A2'])
        _connect(self.U25, 'GND', N['GND2'])
        _connect(self.U25, 'SCK', N['Net_U19_A1'])
        _connect(self.U25, 'SO', N['Net_U19_A0'])
        _connect(self.U25, 'Vcc', N['P5V_Li_ion'])
        _connect(self.U3, 1, N['Net_D3_K'])
        _connect(self.U3, 2, N['Net_D1_A'])
        _connect(self.U3, 3, N['GND'])
        _connect(self.U3, 4, N['ZERO'])
        _connect(self.U4, 'CS', N['Net_U4_CS'])
        _connect(self.U4, 'GND', N['GND2'])
        _connect(self.U4, 'SCK', N['Net_U4_SCK'])
        _connect(self.U4, 'SO', N['Net_U4_SO'])
        _connect(self.U4, 'Vcc', N['P5V_Li_ion'])
        _connect(self.U5, 1, N['Net_D9_K'])
        _connect(self.U5, 2, N['SCL'])
        _connect(self.U5, 3, N['GND3'])
        _connect(self.U5, 4, N['Net_D5_K'])
        _connect(self.U6, 1, N['P5V_sens'])
        _connect(self.U6, 2, N['HALL'])
        _connect(self.U6, 3, N['GND'])
        # U7 ATmega2560: Arduino Mega pin names mapped to TQFP pads
        _connect(self.U7, 7, N['HALL'])
        _connect(self.U7, 16, N['SERVO2'])
        _connect(self.U7, 43, N['SCL'])
        _connect(self.U7, 44, N['SDA'])
        _connect(self.U7, 45, N['DAT'])
        _connect(self.U7, 82, N['ZERO'])
        _connect(self.U7, 83, N['TRIAC'])
        _connect(self.U7, 86, N['T1SCK'])
        _connect(self.U7, 87, N['T1CS'])
        _connect(self.U7, 88, N['T2SCK'])
        _connect(self.U7, 89, N['T2CS'])
        _connect(self.U7, 90, N['T1SO'])
        _connect(self.U7, 91, N['T2SO'])
        _connect(self.U7, 92, N['T3SO'])
        _connect(self.U7, 93, N['T4SO'])
        _connect(self.U7, 94, N['T3SCK'])
        _connect(self.U7, 95, N['T3CS'])
        _connect(self.U7, 96, N['T4SCK'])
        _connect(self.U7, 97, N['T4CS'])
        _connect(self.U7, 11, N['GND'])
        _connect(self.U7, 32, N['GND'])
        _connect(self.U7, 62, N['GND'])
        _connect(self.U7, 81, N['GND'])
        _connect(self.U7, 99, N['GND'])
        _connect(self.U8, 1, N['Net_R8_Pad2'])
        _connect(self.U8, 2, N['GND'])
        _connect(self.U8, 4, N['Net_Q1_G'])
        _connect(self.U8, 6, N['Net_R9_Pad1'])
        _connect(self.U9, 1, N['Net_D5_K'])
        _connect(self.U9, 2, N['SCL_isolated'])
        _connect(self.U9, 3, N['GND'])
        _connect(self.U9, 4, N['Net_D9_K'])
        _connect(self.V1, 1, N['P5V_sens'])
        _connect(self.V1, 2, N['GND'])
        _connect(self.V2, 1, N['Net_SW1_A'])
        _connect(self.V2, 2, N['AC'])
        _connect(self.V3, 1, N['P5V_servo'])
        _connect(self.V3, 2, N['GND'])
        for _c in self.components:
            try:
                _c.nc_unused_pins()
            except Exception:
                pass


class VnI(Module):
    """Hierarchical VnI sheet"""

    def __init__(self, N: dict[str, Net]) -> None:
        super().__init__('VnI')
        self.BT4 = self.add(mk('BT4', BATTERY_CELL, value='9V cells'))
        self.BT6 = self.add(mk('BT6', BATTERY_CELL, value='Battery_Cell'))
        self.BT7 = self.add(mk('BT7', BATTERY_CELL, value='9V and 5V buck'))
        self.C10 = self.add(mk('C10', C_SMALL, value='1u'))
        self.C11 = self.add(mk('C11', C_SMALL, value='100n'))
        self.C12 = self.add(mk('C12', C_SMALL, value='100n'))
        self.C13 = self.add(mk('C13', C_SMALL, value='1u'))
        self.C14 = self.add(mk('C14', C_SMALL, value='100n'))
        self.C9 = self.add(mk('C9', C_SMALL, value='100n'))
        self.D11 = self.add(mk('D11', LED, value='LED'))
        self.D12 = self.add(mk('D12', LED, value='LED'))
        self.D13 = self.add(mk('D13', D_SMALL, value='1n5819'))
        self.D14 = self.add(mk('D14', D_SMALL, value='1n5819'))
        self.D15 = self.add(mk('D15', D_SMALL, value='1n5819'))
        self.D16 = self.add(mk('D16', D_SMALL, value='1n5819'))
        self.J3 = self.add(mk('J3', SCREW_TERMINAL_01X02, value='MIG-Torch'))
        self.J4 = self.add(mk('J4', SCREW_TERMINAL_01X02, value='MIG-Shunt'))
        self.R42 = self.add(mk('R42', R, value='330R'))
        self.R43 = self.add(mk('R43', R, value='330R'))
        self.R44 = self.add(mk('R44', R, value='220R'))
        self.R45 = self.add(mk('R45', R, value='100k'))
        self.R46 = self.add(mk('R46', R, value='100k'))
        self.R47 = self.add(mk('R47', R, value='1M'))
        self.R48 = self.add(mk('R48', R, value='82k'))
        self.R49 = self.add(mk('R49', R, value='5k'))
        self.R50 = self.add(mk('R50', R_SMALL, value='5k'))
        self.R51 = self.add(mk('R51', R_SMALL, value='5k'))
        self.R52 = self.add(mk('R52', R, value='5k'))
        self.R53 = self.add(mk('R53', R, value='1M'))
        self.R54 = self.add(mk('R54', R, value='1M'))
        self.R55 = self.add(mk('R55', R, value='1M'))
        self.R56 = self.add(mk('R56', R, value='1M'))
        self.R57 = self.add(mk('R57', R, value='440R'))
        self.R58 = self.add(mk('R58', R, value='440R'))
        self.R59 = self.add(mk('R59', R, value='2k2'))
        self.R60 = self.add(mk('R60', R, value='2k2'))
        self.R61 = self.add(mk('R61', R, value='135R'))
        self.R62 = self.add(mk('R62', R, value='135R'))
        self.R63 = self.add(mk('R63', R, value='135R'))
        self.R64 = self.add(mk('R64', R, value='135R'))
        self.R65 = self.add(mk('R65', R, value='2k2'))
        self.R66 = self.add(mk('R66', R, value='2k2'))
        self.RV2 = self.add(mk('RV2', R_POTENTIOMETER, value='Pot'))
        self.U23 = self.add(mk('U23', MAX1044, value='MAX1044'))
        self.U32 = self.add(mk('U32', AD620, value='AD620'))
        self.U33 = self.add(mk('U33', AD620, value='AD620'))
        self.U34 = self.add(mk('U34', ADS1115, value='ads1115'))
        self.U35 = self.add(mk('U35', PC817, value='PC817'))
        self.U36 = self.add(mk('U36', PC817, value='PC817'))
        self.U37 = self.add(mk('U37', PC817, value='PC817'))
        self.U38 = self.add(mk('U38', PC817, value='PC817'))

        # Netlist wiring
        _connect(self.BT4, 1, N['P9V'])
        _connect(self.BT4, 2, N['GND3'])
        _connect(self.BT6, 1, N['GND3'])
        _connect(self.BT6, 2, N['N9V'])
        _connect(self.BT7, 1, N['P5V_VnI'])
        _connect(self.BT7, 2, N['GND3'])
        _connect(self.C10, 1, N['Net_U33'])
        _connect(self.C10, 2, N['Net_U33_P'])
        _connect(self.C11, 1, N['Net_U33_P'])
        _connect(self.C11, 2, N['GND3'])
        _connect(self.C12, 1, N['GND3'])
        _connect(self.C12, 2, N['Net_U32'])
        _connect(self.C13, 1, N['Net_U32'])
        _connect(self.C13, 2, N['Net_U32_P'])
        _connect(self.C14, 1, N['Net_U32_P'])
        _connect(self.C14, 2, N['GND3'])
        _connect(self.C9, 1, N['GND3'])
        _connect(self.C9, 2, N['Net_U33'])
        _connect(self.D11, 1, N['GND3'])
        _connect(self.D11, 2, N['Net_D11_A'])
        _connect(self.D12, 1, N['GND3'])
        _connect(self.D12, 2, N['Net_D12_A'])
        _connect(self.D13, 1, N['Net_D13_K'])
        _connect(self.D13, 2, N['VnI_SCL_isolated'])
        _connect(self.D14, 1, N['Net_D14_K'])
        _connect(self.D14, 2, N['VnI_SDA_isolated'])
        _connect(self.D15, 1, N['Net_D15_K'])
        _connect(self.D15, 2, N['SCL'])
        _connect(self.D16, 1, N['Net_D16_K'])
        _connect(self.D16, 2, N['SDA'])
        _connect(self.J3, 1, N['Net_J3_Pin_1'])
        _connect(self.J3, 2, N['Net_J3_Pin_2'])
        _connect(self.J4, 1, N['Net_J4_Pin_1'])
        _connect(self.J4, 2, N['Net_J4_Pin_2'])
        _connect(self.R42, 1, N['Net_R42_Pad1'])
        _connect(self.R42, 2, N['P9V'])
        _connect(self.R43, 1, N['Net_D11_A'])
        _connect(self.R43, 2, N['Net_R42_Pad1'])
        _connect(self.R44, 1, N['Net_D12_A'])
        _connect(self.R44, 2, N['P5V_VnI'])
        _connect(self.R45, 1, N['Net_R45_Pad1'])
        _connect(self.R45, 2, N['Net_J3_Pin_2'])
        _connect(self.R46, 1, N['Net_R46_Pad1'])
        _connect(self.R46, 2, N['Net_R45_Pad1'])
        _connect(self.R47, 1, N['Net_J3_Pin_1'])
        _connect(self.R47, 2, N['Net_R46_Pad1'])
        _connect(self.R48, 1, N['Net_R48_Pad1'])
        _connect(self.R48, 2, N['Net_J3_Pin_2'])
        _connect(self.R49, 1, N['Net_U32_P'])
        _connect(self.R49, 2, N['Net_R45_Pad1'])
        _connect(self.R50, 1, N['Net_J4_Pin_2'])
        _connect(self.R50, 2, N['Net_U33'])
        _connect(self.R51, 1, N['Net_J4_Pin_1'])
        _connect(self.R51, 2, N['Net_U33_P'])
        _connect(self.R52, 1, N['Net_U32'])
        _connect(self.R52, 2, N['Net_R48_Pad1'])
        _connect(self.R53, 1, N['GND3'])
        _connect(self.R53, 2, N['Net_U33'])
        _connect(self.R54, 1, N['GND3'])
        _connect(self.R54, 2, N['Net_U32'])
        _connect(self.R55, 1, N['GND3'])
        _connect(self.R55, 2, N['Net_U32_P'])
        _connect(self.R56, 1, N['GND3'])
        _connect(self.R56, 2, N['Net_U33_P'])
        _connect(self.R57, 1, N['Net_U34_A0'])
        _connect(self.R57, 2, N['Net_R57_Pad2'])
        _connect(self.R58, 1, N['Net_R58_Pad1'])
        _connect(self.R58, 2, N['Net_U34_A2'])
        _connect(self.R59, 1, N['P5V_VnI'])
        _connect(self.R59, 2, N['VnI_SCL_isolated'])
        _connect(self.R60, 1, N['P5V_VnI'])
        _connect(self.R60, 2, N['VnI_SDA_isolated'])
        _connect(self.R61, 1, N['P5V_VnI'])
        _connect(self.R61, 2, N['Net_D14_K'])
        _connect(self.R62, 1, N['P5V_VnI'])
        _connect(self.R62, 2, N['Net_D13_K'])
        _connect(self.R63, 1, N['P5V_sens'])
        _connect(self.R63, 2, N['Net_D15_K'])
        _connect(self.R64, 1, N['P5V_sens'])
        _connect(self.R64, 2, N['Net_D16_K'])
        _connect(self.R65, 1, N['P5V_sens'])
        _connect(self.R65, 2, N['SCL'])
        _connect(self.R66, 1, N['P5V_sens'])
        _connect(self.R66, 2, N['SDA'])
        _connect(self.RV2, 2, N['Net_RV2_Pad2'])
        _connect(self.RV2, 3, N['Net_RV2_Pad3'])
        _connect(self.U32, 2, N['Net_U32'])
        _connect(self.U32, 3, N['Net_U32_P'])
        _connect(self.U32, 4, N['N9V'])
        _connect(self.U32, 5, N['GND3'])
        _connect(self.U32, 6, N['Net_R57_Pad2'])
        _connect(self.U32, 7, N['P9V'])
        _connect(self.U33, 1, N['Net_RV2_Pad2'])
        _connect(self.U33, 2, N['Net_U33'])
        _connect(self.U33, 3, N['Net_U33_P'])
        _connect(self.U33, 4, N['N9V'])
        _connect(self.U33, 5, N['GND3'])
        _connect(self.U33, 6, N['Net_R58_Pad1'])
        _connect(self.U33, 7, N['P9V'])
        _connect(self.U33, 8, N['Net_RV2_Pad3'])
        _connect(self.U34, 3, N['GND3'])
        _connect(self.U34, 4, N['Net_U34_A0'])
        _connect(self.U34, 6, N['Net_U34_A2'])
        _connect(self.U34, 8, N['VnI_SDA_isolated'])
        _connect(self.U34, 9, N['VnI_SCL_isolated'])
        _connect(self.U34, 10, N['P5V_VnI'])
        _connect(self.U35, 1, N['Net_D15_K'])
        _connect(self.U35, 2, N['SCL'])
        _connect(self.U35, 3, N['GND3'])
        _connect(self.U35, 4, N['Net_D13_K'])
        _connect(self.U36, 1, N['Net_D13_K'])
        _connect(self.U36, 2, N['VnI_SCL_isolated'])
        _connect(self.U36, 3, N['GND'])
        _connect(self.U36, 4, N['Net_D15_K'])
        _connect(self.U37, 1, N['Net_D16_K'])
        _connect(self.U37, 2, N['SDA'])
        _connect(self.U37, 3, N['GND3'])
        _connect(self.U37, 4, N['Net_D14_K'])
        _connect(self.U38, 1, N['Net_D14_K'])
        _connect(self.U38, 2, N['VnI_SDA_isolated'])
        _connect(self.U38, 3, N['GND'])
        _connect(self.U38, 4, N['Net_D16_K'])
        for _c in self.components:
            try:
                _c.nc_unused_pins()
            except Exception:
                pass


class R4(Module):
    """R4 Nano Every + MAX6675 + RS-485"""

    def __init__(self, N: dict[str, Net]) -> None:
        super().__init__('R4')
        self.A1 = self.add(mk('A1', ARDUINO_NANO_EVERY_SOCKET, value='Arduino_Nano_Every_Socket'))
        self.R73 = self.add(mk('R73', R, value='330R'))
        self.R74 = self.add(mk('R74', R, value='3k'))
        self.U44 = self.add(mk('U44', MAX6675_THERMOCOUPLE_MODULE_1, value='I'))
        self.U45 = self.add(mk('U45', MAX6675_THERMOCOUPLE_MODULE_2, value='J'))
        self.U46 = self.add(mk('U46', MAX6675_THERMOCOUPLE_MODULE_3, value='K'))
        self.U47 = self.add(mk('U47', MAX6675_THERMOCOUPLE_MODULE_4, value='L'))
        self.U48 = self.add(mk('U48', PC817, value='PC817'))
        self.U49 = self.add(mk('U49', P_74HC14, value='74HC14_data'))
        self.U50 = self.add(mk('U50', MAX485_1_4, value='max485_1_4'))
        self.U51 = self.add(mk('U51', MAX485_1_3, value='max485_1_3'))

        # Netlist wiring
        _connect(self.A1, 1, N['T_Substrate'])
        _connect(self.A1, 5, N['T3SCK'])
        _connect(self.A1, 6, N['T3CS'])
        _connect(self.A1, 7, N['T3SO'])
        _connect(self.A1, 8, N['T4SCK'])
        _connect(self.A1, 9, N['T4CS'])
        _connect(self.A1, 10, N['T4SO'])
        _connect(self.A1, 19, N['T1SO'])
        _connect(self.A1, 20, N['T1CS'])
        _connect(self.A1, 21, N['T1SCK'])
        _connect(self.A1, 22, N['T2SCK'])
        _connect(self.A1, 23, N['T2CS'])
        _connect(self.A1, 24, N['T2SO'])
        _connect(self.A1, 29, N['GND2'])
        _connect(self.A1, 30, N['P5V_Boosted'])
        _connect(self.R73, 1, N['T_Substrate'])
        _connect(self.R73, 2, N['Net_R73_Pad2'])
        _connect(self.R74, 1, N['Net_R74_Pad1'])
        _connect(self.R74, 2, N['P5V_sens'])
        _connect(self.U44, 'CS', N['T1CS'])
        _connect(self.U44, 'GND', N['GND2'])
        _connect(self.U44, 'SCK', N['T1SCK'])
        _connect(self.U44, 'SO', N['T1SO'])
        _connect(self.U44, 'Vcc', N['P5V_Boosted'])
        _connect(self.U45, 'CS', N['T2CS'])
        _connect(self.U45, 'GND', N['GND2'])
        _connect(self.U45, 'SCK', N['T2SCK'])
        _connect(self.U45, 'SO', N['T2SO'])
        _connect(self.U45, 'Vcc', N['P5V_Boosted'])
        _connect(self.U46, 'CS', N['T3CS'])
        _connect(self.U46, 'GND', N['GND2'])
        _connect(self.U46, 'SCK', N['T3SCK'])
        _connect(self.U46, 'SO', N['T3SO'])
        _connect(self.U46, 'Vcc', N['P5V_Boosted'])
        _connect(self.U47, 'CS', N['T4CS'])
        _connect(self.U47, 'GND', N['GND2'])
        _connect(self.U47, 'SCK', N['T4SCK'])
        _connect(self.U47, 'SO', N['T4SO'])
        _connect(self.U47, 'Vcc', N['P5V_Boosted'])
        _connect(self.U48, 1, N['Net_R73_Pad2'])
        _connect(self.U48, 2, N['GND2'])
        _connect(self.U48, 3, N['GND'])
        _connect(self.U48, 4, N['Net_R74_Pad1'])
        _connect(self.U49, 12, N['Net_U50_DI'])
        _connect(self.U49, 13, N['Net_R74_Pad1'])
        _connect(self.U50, 4, N['Net_U50_DI'])
        _connect(self.U50, 5, N['GND'])
        _connect(self.U50, 6, N['R4_DP'])
        _connect(self.U50, 7, N['R4_D'])
        _connect(self.U50, 8, N['P5V_sens'])
        _connect(self.U51, 1, N['T_Substrate'])
        _connect(self.U51, 2, N['GND'])
        _connect(self.U51, 6, N['R4_DP'])
        _connect(self.U51, 7, N['R4_D'])
        _connect(self.U51, 8, N['P5V_sens'])
        for _c in self.components:
            try:
                _c.nc_unused_pins()
            except Exception:
                pass


def build_board() -> Board:
    board = Board(size_mm=None, layers=2, compile_goal="handoff", strict=False)
    net_names = [
        'AC',
        'ACP',
        'D',
        'DAT',
        'DP',
        'GND',
        'GND2',
        'GND3',
        'HALL',
        'N9V',
        'Net_D10_K',
        'Net_D11_A',
        'Net_D12_A',
        'Net_D13_K',
        'Net_D14_K',
        'Net_D15_K',
        'Net_D16_K',
        'Net_D1_A',
        'Net_D1_K',
        'Net_D2_K',
        'Net_D3_K',
        'Net_D5_K',
        'Net_D6_K',
        'Net_D7_A',
        'Net_D8_A',
        'Net_D9_K',
        'Net_J1_Pin_1',
        'Net_J1_Pin_2',
        'Net_J2_Pin_1',
        'Net_J2_Pin_2',
        'Net_J3_Pin_1',
        'Net_J3_Pin_2',
        'Net_J4_Pin_1',
        'Net_J4_Pin_2',
        'Net_Q1_A1',
        'Net_Q1_G',
        'Net_R14_Pad1',
        'Net_R15_Pad2',
        'Net_R22_Pad2',
        'Net_R23_Pad2',
        'Net_R26_Pad1',
        'Net_R29_Pad2',
        'Net_R2_Pad1',
        'Net_R30_Pad1',
        'Net_R33_Pad2',
        'Net_R34_Pad1',
        'Net_R37_Pad1',
        'Net_R42_Pad1',
        'Net_R45_Pad1',
        'Net_R46_Pad1',
        'Net_R48_Pad1',
        'Net_R4_Pad1',
        'Net_R57_Pad2',
        'Net_R58_Pad1',
        'Net_R73_Pad2',
        'Net_R74_Pad1',
        'Net_R8_Pad2',
        'Net_R9_Pad1',
        'Net_RV1_Pad2',
        'Net_RV1_Pad3',
        'Net_RV2_Pad2',
        'Net_RV2_Pad3',
        'Net_SW1_A',
        'Net_U1',
        'Net_U15_DI',
        'Net_U17_A0',
        'Net_U17_A2',
        'Net_U19_A0',
        'Net_U19_A1',
        'Net_U19_A2',
        'Net_U19_D1',
        'Net_U1_P',
        'Net_U2',
        'Net_U2_P',
        'Net_U32',
        'Net_U32_P',
        'Net_U33',
        'Net_U33_P',
        'Net_U34_A0',
        'Net_U34_A2',
        'Net_U4_CS',
        'Net_U4_SCK',
        'Net_U4_SO',
        'Net_U50_DI',
        'P5V_Boosted',
        'P5V_Li_ion',
        'P5V_VnI',
        'P5V_sens',
        'P5V_servo',
        'P9V',
        'R4_D',
        'R4_DP',
        'SCL',
        'SCL_isolated',
        'SDA',
        'SDA_isolated',
        'SERVO2',
        'T1CS',
        'T1SCK',
        'T1SO',
        'T2CS',
        'T2SCK',
        'T2SO',
        'T3CS',
        'T3SCK',
        'T3SO',
        'T4CS',
        'T4SCK',
        'T4SO',
        'TRIAC',
        'T_Substrate',
        'VnI_SCL_isolated',
        'VnI_SDA_isolated',
        'ZERO',
    ]
    N = {n: Net(n) for n in net_names}
    root = Root(N)
    vni = VnI(N)
    r4 = R4(N)
    for m in (root, vni, r4):
        board.add_module(m)
    board.set_schematic_sheet("ROOT", root)
    board.set_schematic_sheet("VnI", vni)
    board.set_schematic_sheet("R4", r4)
    for name in [
        'GND',
        'GND2',
        'GND3',
        'N9V',
        'P5V_Boosted',
        'P5V_Li_ion',
        'P5V_VnI',
        'P5V_sens',
        'P5V_servo',
        'P9V',
        'VnI_SCL_isolated',
        'VnI_SDA_isolated',
    ]:
        if name in N:
            try:
                board.declare_power_rail(name, N[name])
            except Exception:
                pass
    board.declare_spice_island(vni)
    if "GND3" in N:
        board.declare_spice_ground("GND3")
    for name, volts in (
        ("P9V", 9.0),
        ("N9V", -9.0),
        ("P5V_VnI", 5.0),
        ("P5V_sens", 5.0),
    ):
        if name in N:
            try:
                board.declare_spice_rail(name, volts)
            except Exception:
                pass
    return board


board = build_board()

if __name__ == "__main__":
    mods = board._get_all_modules()
    n = sum(len(m.components) for m in mods)
    refs = sorted(
        {
            str(getattr(c, "ref", None) or getattr(c, "name", "?"))
            for m in mods
            for c in m.components
        }
    )
    empty_fp = []
    for m in mods:
        for c in m.components:
            p = getattr(c, 'part', None)
            fp = getattr(p, 'footprint', None) or ''
            if not str(fp).strip():
                empty_fp.append(str(getattr(c, "ref", "?")))
    print(f"Fundi MIG: {n} components, {len(refs)} refs")
    print(f"empty footprints (enrichment required): {len(empty_fp)} -> {", ".join(sorted(empty_fp))}")

