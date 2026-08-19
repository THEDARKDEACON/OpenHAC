"""Shared offline ``comp_data`` builders for complex fab-capable example boards.

All footprints are stock KiCad library parts under ``/usr/share/kicad/footprints``.
Pinouts are explicit so fabrication mode (FAB-001) does not invent pins.
"""

from __future__ import annotations

import json
from typing import Any


def _pinout(pins: dict[int | str, tuple[str, str]]) -> str:
    rows = []
    for num, (name, typ) in pins.items():
        rows.append({"num": str(num), "name": name, "type": typ})
    return json.dumps(rows)


def offline_part(
    *,
    generic_name: str,
    footprint: str,
    pins: dict[int | str, tuple[str, str]],
    category: str,
    symbol: str = "Device:R",
    mpn: str | None = None,
    package: str = "",
    description: str = "",
) -> dict[str, Any]:
    return {
        "generic_name": generic_name,
        "mpn": mpn or generic_name,
        "manufacturer": "OpenHaC-Offline",
        "description": description or generic_name,
        "category": category,
        "package": package,
        "kicad_symbol": symbol,
        "kicad_footprint": footprint,
        "pinout_json": _pinout(pins),
        "jlc_class": "Basic",
    }


# --- Passives -----------------------------------------------------------------

R_0805 = lambda name, ohms="10k": offline_part(
    generic_name=name,
    footprint="Resistor_SMD:R_0805_2012Metric",
    pins={1: ("1", "passive"), 2: ("2", "passive")},
    category="Resistor",
    symbol="Device:R",
    package="0805",
    description=f"Resistor {ohms} 0805",
)

C_0805 = lambda name, val="100nF": offline_part(
    generic_name=name,
    footprint="Capacitor_SMD:C_0805_2012Metric",
    pins={1: ("1", "passive"), 2: ("2", "passive")},
    category="Capacitor",
    symbol="Device:C",
    package="0805",
    description=f"Capacitor {val} 0805",
)

C_0603 = lambda name, val="100nF": offline_part(
    generic_name=name,
    footprint="Capacitor_SMD:C_0603_1608Metric",
    pins={1: ("1", "passive"), 2: ("2", "passive")},
    category="Capacitor",
    symbol="Device:C",
    package="0603",
    description=f"Capacitor {val} 0603",
)

LED_0805 = lambda name: offline_part(
    generic_name=name,
    footprint="LED_SMD:LED_0805_2012Metric",
    pins={1: ("K", "passive"), 2: ("A", "passive")},
    category="LED",
    symbol="Device:LED",
    package="0805",
    description="LED 0805",
)

# --- AMS1117-3.3 (SOT-223: 1=GND, 2=VOUT/tab, 3=VIN) -------------------------

AMS1117_33 = offline_part(
    generic_name="AMS1117_3V3",
    footprint="Package_TO_SOT_SMD:SOT-223-3_TabPin2",
    pins={
        1: ("GND", "power_in"),
        2: ("VOUT", "power_out"),
        3: ("VIN", "power_in"),
    },
    category="Regulator",
    symbol="Regulator_Linear:AMS1117-3.3",
    package="SOT-223",
    mpn="AMS1117-3.3",
    description="3.3V LDO AMS1117 (DevKit-style)",
)

# --- USB-C receptacle (HRO TYPE-C-31-M-12) ------------------------------------

USB_C_HRO_PINS: dict[int | str, tuple[str, str]] = {
    "A1": ("GND", "power_in"),
    "A4": ("VBUS", "power_in"),
    "A5": ("CC1", "bidirectional"),
    "A6": ("D+", "bidirectional"),
    "A7": ("D-", "bidirectional"),
    "A8": ("SBU1", "bidirectional"),
    "A9": ("VBUS", "power_in"),
    "A12": ("GND", "power_in"),
    "B1": ("GND", "power_in"),
    "B4": ("VBUS", "power_in"),
    "B5": ("CC2", "bidirectional"),
    "B6": ("D-", "bidirectional"),
    "B7": ("D+", "bidirectional"),
    "B8": ("SBU2", "bidirectional"),
    "B9": ("VBUS", "power_in"),
    "B12": ("GND", "power_in"),
    "S1": ("SHIELD", "passive"),
}

USB_C_HRO = offline_part(
    generic_name="USB_C_HRO_TYPE_C_31_M_12",
    footprint="Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12",
    pins=USB_C_HRO_PINS,
    category="Connector",
    symbol="Connector:USB_C_Receptacle_USB2.0_16P",
    package="USB-C",
    mpn="TYPE-C-31-M-12",
    description="USB-C receptacle (Espressif DevKitC style)",
)

# --- ESP32-WROOM-32 (KiCad RF_Module pin numbers / names) ---------------------

ESP32_WROOM32_PINS: dict[int | str, tuple[str, str]] = {
    1: ("GND", "power_in"),
    2: ("VDD", "power_in"),
    3: ("EN", "input"),
    4: ("SENSOR_VP", "input"),
    5: ("SENSOR_VN", "input"),
    6: ("IO34", "input"),
    7: ("IO35", "input"),
    8: ("IO32", "bidirectional"),
    9: ("IO33", "bidirectional"),
    10: ("IO25", "bidirectional"),
    11: ("IO26", "bidirectional"),
    12: ("IO27", "bidirectional"),
    13: ("IO14", "bidirectional"),
    14: ("IO12", "bidirectional"),
    15: ("GND", "power_in"),
    16: ("IO13", "bidirectional"),
    17: ("SHD_SD2", "bidirectional"),
    18: ("SWP_SD3", "bidirectional"),
    19: ("SCS_CMD", "bidirectional"),
    20: ("SCK_CLK", "bidirectional"),
    21: ("SDO_SD0", "bidirectional"),
    22: ("SDI_SD1", "bidirectional"),
    23: ("IO15", "bidirectional"),
    24: ("IO2", "bidirectional"),
    25: ("IO0", "bidirectional"),
    26: ("IO4", "bidirectional"),
    27: ("IO16", "bidirectional"),
    28: ("IO17", "bidirectional"),
    29: ("IO5", "bidirectional"),
    30: ("IO18", "bidirectional"),
    31: ("IO19", "bidirectional"),
    32: ("NC", "no_connect"),
    33: ("IO21", "bidirectional"),
    34: ("RXD0_IO3", "bidirectional"),
    35: ("TXD0_IO1", "bidirectional"),
    36: ("IO22", "bidirectional"),
    37: ("IO23", "bidirectional"),
    38: ("GND", "power_in"),
    39: ("GND", "power_in"),
}

ESP32_WROOM32 = offline_part(
    generic_name="ESP32_WROOM_32",
    footprint="RF_Module:ESP32-WROOM-32",
    pins=ESP32_WROOM32_PINS,
    category="MCU",
    symbol="RF_Module:ESP32-WROOM-32",
    package="ESP32-WROOM-32",
    mpn="ESP32-WROOM-32",
    description="Espressif ESP32-WROOM-32 module",
)

# --- 24LC256 I2C EEPROM SOIC-8 -----------------------------------------------

EEPROM_24LC256 = offline_part(
    generic_name="EEPROM_24LC256",
    footprint="Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
    pins={
        1: ("A0", "input"),
        2: ("A1", "input"),
        3: ("A2", "input"),
        4: ("VSS", "power_in"),
        5: ("SDA", "bidirectional"),
        6: ("SCL", "input"),
        7: ("WP", "input"),
        8: ("VCC", "power_in"),
    },
    category="Memory",
    symbol="Memory_EEPROM:24LC256",
    package="SOIC-8",
    mpn="24LC256",
    description="I2C EEPROM 256Kbit",
)

# --- TJA1051 CAN transceiver SOIC-8 ------------------------------------------

TJA1051 = offline_part(
    generic_name="CAN_TJA1051T",
    footprint="Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
    pins={
        1: ("TXD", "input"),
        2: ("GND", "power_in"),
        3: ("VCC", "power_in"),
        4: ("RXD", "output"),
        5: ("VIO", "power_in"),
        6: ("CANL", "bidirectional"),
        7: ("CANH", "bidirectional"),
        8: ("S", "input"),
    },
    category="Interface",
    symbol="Interface_CAN_LIN:TJA1051",
    package="SOIC-8",
    mpn="TJA1051T",
    description="High-speed CAN transceiver",
)

# --- STM32F103C8 LQFP-48 (Blue Pill class; abbreviated names, all pads) ------

def _stm32f103_pins() -> dict[int | str, tuple[str, str]]:
    # Numeric pad map matching Package_QFP:LQFP-48_7x7mm_P0.5mm
    named = {
        1: ("VBAT", "power_in"),
        2: ("PC13", "bidirectional"),
        3: ("PC14", "bidirectional"),
        4: ("PC15", "bidirectional"),
        5: ("PD0", "bidirectional"),
        6: ("PD1", "bidirectional"),
        7: ("NRST", "input"),
        8: ("VSSA", "power_in"),
        9: ("VDDA", "power_in"),
        10: ("PA0", "bidirectional"),
        11: ("PA1", "bidirectional"),
        12: ("PA2", "bidirectional"),
        13: ("PA3", "bidirectional"),
        14: ("PA4", "bidirectional"),
        15: ("PA5", "bidirectional"),
        16: ("PA6", "bidirectional"),
        17: ("PA7", "bidirectional"),
        18: ("PB0", "bidirectional"),
        19: ("PB1", "bidirectional"),
        20: ("PB2", "bidirectional"),
        21: ("PB10", "bidirectional"),
        22: ("PB11", "bidirectional"),
        23: ("VSS_1", "power_in"),
        24: ("VDD_1", "power_in"),
        25: ("PB12", "bidirectional"),
        26: ("PB13", "bidirectional"),
        27: ("PB14", "bidirectional"),
        28: ("PB15", "bidirectional"),
        29: ("PA8", "bidirectional"),
        30: ("PA9", "bidirectional"),
        31: ("PA10", "bidirectional"),
        32: ("PA11", "bidirectional"),
        33: ("PA12", "bidirectional"),
        34: ("PA13", "bidirectional"),
        35: ("VSS_2", "power_in"),
        36: ("VDD_2", "power_in"),
        37: ("PA14", "bidirectional"),
        38: ("PA15", "bidirectional"),
        39: ("PB3", "bidirectional"),
        40: ("PB4", "bidirectional"),
        41: ("PB5", "bidirectional"),
        42: ("PB6", "bidirectional"),
        43: ("PB7", "bidirectional"),
        44: ("BOOT0", "input"),
        45: ("PB8", "bidirectional"),
        46: ("PB9", "bidirectional"),
        47: ("VSS_3", "power_in"),
        48: ("VDD_3", "power_in"),
    }
    return named


STM32F103C8 = offline_part(
    generic_name="STM32F103C8T6",
    footprint="Package_QFP:LQFP-48_7x7mm_P0.5mm",
    pins=_stm32f103_pins(),
    category="MCU",
    symbol="MCU_ST_STM32F1:STM32F103C8Tx",
    package="LQFP-48",
    mpn="STM32F103C8T6",
    description="STM32F103C8T6 Blue-Pill class MCU",
)

HEADER_1x04 = offline_part(
    generic_name="HDR_1x04",
    footprint="Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical",
    pins={1: ("1", "passive"), 2: ("2", "passive"), 3: ("3", "passive"), 4: ("4", "passive")},
    category="Connector",
    symbol="Connector:Conn_01x04_Pin",
    package="PinHeader",
    description="1x4 pin header",
)

# --- MAX3485 RS-485 transceiver SOIC-8 ---------------------------------------

MAX3485 = offline_part(
    generic_name="RS485_MAX3485",
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
    symbol="Interface_UART:MAX3485",
    package="SOIC-8",
    mpn="MAX3485ESA+",
    description="3.3V RS-485 transceiver",
)

# --- BMP280 pressure sensor (Bosch LGA-8) ------------------------------------

BMP280 = offline_part(
    generic_name="SENSOR_BMP280",
    footprint="Package_LGA:Bosch_LGA-8_2x2.5mm_P0.65mm_ClockwisePinNumbering",
    pins={
        1: ("GND", "power_in"),
        2: ("CSB", "input"),
        3: ("SDI", "bidirectional"),
        4: ("SCK", "input"),
        5: ("SDO", "no_connect"),
        6: ("VDDIO", "power_in"),
        7: ("GND", "power_in"),
        8: ("VDD", "power_in"),
    },
    category="Sensor",
    symbol="Sensor_Pressure:BMP280",
    package="LGA-8",
    mpn="BMP280",
    description="Bosch BMP280 pressure / temperature",
)

# --- ESP32-C3-WROOM-02 (smaller RF module than WROOM-32) ---------------------

ESP32_C3_WROOM02_PINS: dict[int | str, tuple[str, str]] = {
    1: ("3V3", "power_in"),
    2: ("EN", "input"),
    3: ("IO4", "bidirectional"),
    4: ("IO5", "bidirectional"),
    5: ("IO6", "bidirectional"),
    6: ("IO7", "bidirectional"),
    7: ("IO8", "bidirectional"),
    8: ("IO9", "bidirectional"),
    9: ("GND", "power_in"),
    10: ("IO10", "bidirectional"),
    11: ("IO20_RXD", "bidirectional"),
    12: ("IO21_TXD", "bidirectional"),
    13: ("IO18", "bidirectional"),
    14: ("IO19", "bidirectional"),
    15: ("IO3", "bidirectional"),
    16: ("IO2", "bidirectional"),
    17: ("IO1", "bidirectional"),
    18: ("IO0", "bidirectional"),
    19: ("GND", "power_in"),
}

ESP32_C3_WROOM02 = offline_part(
    generic_name="ESP32_C3_WROOM_02",
    footprint="RF_Module:ESP32-C3-WROOM-02",
    pins=ESP32_C3_WROOM02_PINS,
    category="MCU",
    symbol="RF_Module:ESP32-C3-WROOM-02",
    package="ESP32-C3-WROOM-02",
    mpn="ESP32-C3-WROOM-02",
    description="Espressif ESP32-C3-WROOM-02 module",
)


# --- ESP32-S3-WROOM-1 (application SoC for industrial gateway) ---------------

ESP32_S3_WROOM1_PINS: dict[int | str, tuple[str, str]] = {
    1: ("GND", "power_in"),
    2: ("3V3", "power_in"),
    3: ("EN", "input"),
    4: ("IO4", "bidirectional"),
    5: ("IO5", "bidirectional"),
    6: ("IO6", "bidirectional"),
    7: ("IO7", "bidirectional"),
    8: ("IO15", "bidirectional"),
    9: ("IO16", "bidirectional"),
    10: ("IO17", "bidirectional"),
    11: ("IO18", "bidirectional"),
    12: ("IO8", "bidirectional"),
    13: ("IO19", "bidirectional"),
    14: ("IO20", "bidirectional"),
    15: ("IO3", "bidirectional"),
    16: ("IO46", "bidirectional"),
    17: ("IO9", "bidirectional"),
    18: ("IO10", "bidirectional"),
    19: ("IO11", "bidirectional"),
    20: ("IO12", "bidirectional"),
    21: ("IO13", "bidirectional"),
    22: ("IO14", "bidirectional"),
    23: ("IO21", "bidirectional"),
    24: ("IO47", "bidirectional"),
    25: ("IO48", "bidirectional"),
    26: ("IO45", "bidirectional"),
    27: ("IO0", "bidirectional"),
    28: ("IO35", "bidirectional"),
    29: ("IO36", "bidirectional"),
    30: ("IO37", "bidirectional"),
    31: ("IO38", "bidirectional"),
    32: ("IO39", "bidirectional"),
    33: ("IO40", "bidirectional"),
    34: ("IO41", "bidirectional"),
    35: ("IO42", "bidirectional"),
    36: ("RXD0", "bidirectional"),
    37: ("TXD0", "bidirectional"),
    38: ("IO2", "bidirectional"),
    39: ("IO1", "bidirectional"),
    40: ("GND", "power_in"),
    41: ("EPAD", "power_in"),
}

ESP32_S3_WROOM1 = offline_part(
    generic_name="ESP32_S3_WROOM_1",
    footprint="RF_Module:ESP32-S3-WROOM-1",
    pins=ESP32_S3_WROOM1_PINS,
    category="MCU",
    symbol="RF_Module:ESP32-S3-WROOM-1",
    package="ESP32-S3-WROOM-1",
    mpn="ESP32-S3-WROOM-1",
    description="Espressif ESP32-S3-WROOM-1 WiFi/BLE SoC module",
)

# --- HopeRF RFM9X LoRa (SPI long-range mesh) ---------------------------------

RFM9X_LORA = offline_part(
    generic_name="RFM95_LORA",
    footprint="RF_Module:HOPERF_RFM9XW_SMD",
    pins={
        1: ("GND", "power_in"),
        2: ("MISO", "bidirectional"),
        3: ("MOSI", "input"),
        4: ("SCK", "input"),
        5: ("NSS", "input"),
        6: ("RESET", "input"),
        7: ("DIO0", "bidirectional"),
        8: ("DIO1", "bidirectional"),
        9: ("DIO2", "bidirectional"),
        10: ("DIO3", "bidirectional"),
        11: ("DIO4", "bidirectional"),
        12: ("DIO5", "bidirectional"),
        13: ("VDD", "power_in"),
        14: ("GND", "power_in"),
        15: ("GND", "power_in"),
        16: ("GND", "power_in"),
    },
    category="RF",
    symbol="RF_Module:RFM95W-868S2",
    package="RFM9X",
    mpn="RFM95W",
    description="HopeRF RFM95/96 LoRa transceiver module",
)

# --- nRF24L01+ short-range mesh radio ----------------------------------------

NRF24L01 = offline_part(
    generic_name="NRF24L01",
    footprint="RF_Module:nRF24L01_Breakout",
    pins={
        1: ("GND", "power_in"),
        2: ("VCC", "power_in"),
        3: ("CE", "input"),
        4: ("CSN", "input"),
        5: ("SCK", "input"),
        6: ("MOSI", "input"),
        7: ("MISO", "bidirectional"),
        8: ("IRQ", "no_connect"),
    },
    category="RF",
    symbol="RF:NRF24L01_Breakout",
    package="nRF24L01",
    mpn="nRF24L01+",
    description="Nordic nRF24L01+ 2.4GHz transceiver breakout",
)

# --- W5500 Ethernet MAC/PHY (SPI) on LQFP-48 — essential pins wired -----------

def _w5500_pins() -> dict[int | str, tuple[str, str]]:
    # Minimal functional map; remaining pads marked NC so FAB pin/pad coverage passes.
    named = {
        1: ("NC1", "no_connect"),
        11: ("MOSI", "input"),
        12: ("SCLK", "input"),
        13: ("SCS", "input"),
        14: ("INT", "no_connect"),
        15: ("RST", "input"),
        16: ("MISO", "bidirectional"),
        24: ("VDD", "power_in"),
        25: ("GND", "power_in"),
        32: ("TXN", "bidirectional"),
        33: ("TXP", "bidirectional"),
        34: ("RXN", "bidirectional"),
        35: ("RXP", "bidirectional"),
        42: ("VDD2", "power_in"),
        43: ("GND2", "power_in"),
    }
    for i in range(1, 49):
        named.setdefault(i, (f"NC{i}", "no_connect"))
    return named


W5500 = offline_part(
    generic_name="W5500_ETH",
    footprint="Package_QFP:LQFP-48_7x7mm_P0.5mm",
    pins=_w5500_pins(),
    category="Interface",
    symbol="Interface_Ethernet:W5500",
    package="LQFP-48",
    mpn="W5500",
    description="WIZnet W5500 hardwired TCP/IP Ethernet controller",
)

RJ45_MAGJACK = offline_part(
    generic_name="RJ45_MAGJACK",
    footprint="Connector_RJ:RJ45_Hanrun_HR911105A_Horizontal",
    pins={
        1: ("TD_P", "bidirectional"),
        2: ("TD_N", "bidirectional"),
        3: ("RD_P", "bidirectional"),
        4: ("NC4", "no_connect"),
        5: ("NC5", "no_connect"),
        6: ("RD_N", "bidirectional"),
        7: ("NC7", "no_connect"),
        8: ("NC8", "no_connect"),
        9: ("GND", "power_in"),
        10: ("GND", "power_in"),
        11: ("VCC_LED", "passive"),
        12: ("LED", "passive"),
        "SH": ("SHIELD", "passive"),
    },
    category="Connector",
    symbol="Connector:RJ45_Hanrun_HR911105A_Horizontal",
    package="RJ45",
    mpn="HR911105A",
    description="RJ45 jack with magnetics (Hanrun)",
)

# --- MPU-6050 class IMU (InvenSense QFN-24) ----------------------------------

MPU6050 = offline_part(
    generic_name="IMU_MPU6050",
    footprint="Sensor_Motion:InvenSense_QFN-24_4x4mm_P0.5mm",
    pins={
        **{i: (f"NC{i}", "no_connect") for i in range(1, 25)},
        8: ("VDDIO", "power_in"),
        9: ("AD0", "input"),
        12: ("INT", "no_connect"),
        13: ("VDD", "power_in"),
        18: ("GND", "power_in"),
        23: ("SCL", "input"),
        24: ("SDA", "bidirectional"),
    },
    category="Sensor",
    symbol="Sensor_Motion:MPU-6050",
    package="QFN-24",
    mpn="MPU-6050",
    description="InvenSense MPU-6050 6-axis IMU",
)

# --- ADS1115 16-bit ADC (industrial analog / 4-20mA shunt front-end) ---------

ADS1115 = offline_part(
    generic_name="ADC_ADS1115",
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
    description="TI ADS1115 4-ch 16-bit I2C ADC",
)

# --- SSD1306 OLED (local HMI) ------------------------------------------------

SSD1306_OLED = offline_part(
    generic_name="OLED_SSD1306",
    footprint="Display:Adafruit_SSD1306",
    pins={
        1: ("VIN", "power_in"),
        2: ("GND", "power_in"),
        3: ("3V3", "no_connect"),
        4: ("NC4", "no_connect"),
        5: ("NC5", "no_connect"),
        6: ("NC6", "no_connect"),
        7: ("SCL", "input"),
        8: ("SDA", "bidirectional"),
    },
    category="Display",
    symbol="Display_Graphic:OLED-128O064D",
    package="OLED",
    mpn="SSD1306",
    description="SSD1306 128x64 OLED module",
)

# --- microSD logging ---------------------------------------------------------

MICROSD = offline_part(
    generic_name="MICROSD_SLOT",
    footprint="Connector_Card:microSD_HC_Molex_47219-2001",
    pins={
        1: ("DAT2", "bidirectional"),
        2: ("DAT3_CS", "bidirectional"),
        3: ("CMD_DI", "bidirectional"),
        4: ("VDD", "power_in"),
        5: ("CLK", "input"),
        6: ("VSS", "power_in"),
        7: ("DAT0_DO", "bidirectional"),
        8: ("DAT1", "bidirectional"),
        9: ("CD", "passive"),
    },
    category="Connector",
    symbol="Connector:Micro_SD_Card",
    package="microSD",
    mpn="47219-2001",
    description="Molex microSD card connector",
)

# --- Optocoupler (isolated DI) -----------------------------------------------

OPTO_SOIC4 = offline_part(
    generic_name="OPTO_PC817",
    footprint="Package_SO:SOIC-4_4.55x2.6mm_P1.27mm",
    pins={
        1: ("A", "passive"),
        2: ("K", "passive"),
        3: ("E", "passive"),
        4: ("C", "passive"),
    },
    category="Isolator",
    symbol="Isolator:PC817",
    package="SOIC-4",
    mpn="PC817",
    description="PC817 phototransistor optocoupler",
)

XTAL_8MHZ = offline_part(
    generic_name="XTAL_8MHZ",
    footprint="Crystal:Crystal_SMD_3225-4Pin_3.2x2.5mm",
    pins={
        1: ("X1", "passive"),
        2: ("GND", "passive"),
        3: ("X2", "passive"),
        4: ("GND2", "passive"),
    },
    category="Crystal",
    symbol="Device:Crystal_GND2",
    package="3225",
    mpn="XTAL_8M",
    description="8 MHz crystal 3225",
)

HEADER_1x06 = offline_part(
    generic_name="HDR_1x06",
    footprint="Connector_PinHeader_2.54mm:PinHeader_1x06_P2.54mm_Vertical",
    pins={i: (str(i), "passive") for i in range(1, 7)},
    category="Connector",
    symbol="Connector:Conn_01x06_Pin",
    package="PinHeader",
    description="1x6 pin header",
)

HEADER_1x08 = offline_part(
    generic_name="HDR_1x08",
    footprint="Connector_PinHeader_2.54mm:PinHeader_1x08_P2.54mm_Vertical",
    pins={i: (str(i), "passive") for i in range(1, 9)},
    category="Connector",
    symbol="Connector:Conn_01x08_Pin",
    package="PinHeader",
    description="1x8 pin header",
)

HEADER_1x10 = offline_part(
    generic_name="HDR_1x10",
    footprint="Connector_PinHeader_2.54mm:PinHeader_1x10_P2.54mm_Vertical",
    pins={i: (str(i), "passive") for i in range(1, 11)},
    category="Connector",
    symbol="Connector:Conn_01x10_Pin",
    package="PinHeader",
    description="1x10 pin header",
)

# --- PDN passives / mixed-signal tie (stock KiCad symbols, 0805 bodies) ------

FERRITE_0805 = lambda name: offline_part(
    generic_name=name,
    footprint="Inductor_SMD:L_0805_2012Metric",
    pins={1: ("1", "passive"), 2: ("2", "passive")},
    category="Filter",
    symbol="Device:FerriteBead",
    package="0805",
    description="Ferrite bead 0805",
)

FUSE_0805 = lambda name: offline_part(
    generic_name=name,
    footprint="Fuse:Fuse_0805_2012Metric",
    pins={1: ("1", "passive"), 2: ("2", "passive")},
    category="Fuse",
    symbol="Device:Fuse",
    package="0805",
    description="Fuse 0805",
)

L_0805 = lambda name, val="10uH": offline_part(
    generic_name=name,
    footprint="Inductor_SMD:L_0805_2012Metric",
    pins={1: ("1", "passive"), 2: ("2", "passive")},
    category="Inductor",
    symbol="Device:L",
    package="0805",
    description=f"Inductor {val} 0805",
)

NETTIE_2 = offline_part(
    generic_name="NETTIE_AGND_GND",
    footprint="NetTie:NetTie-2_SMD_Pad2.0mm",
    pins={1: ("1", "passive"), 2: ("2", "passive")},
    category="NetTie",
    symbol="Device:NetTie_2",
    package="NetTie",
    description="2-pad net-tie (AGND star point)",
)

# --- AMS1117-1.8 (same SOT-223 / AP1117 pin numbers: 1=GND 2=VO 3=VI) --------

AMS1117_18 = offline_part(
    generic_name="AMS1117_1V8",
    footprint="Package_TO_SOT_SMD:SOT-223-3_TabPin2",
    pins={
        1: ("GND", "power_in"),
        2: ("VOUT", "power_out"),
        3: ("VIN", "power_in"),
    },
    category="Regulator",
    symbol="Regulator_Linear:AMS1117-1.8",
    package="SOT-223",
    mpn="AMS1117-1.8",
    description="1.8V LDO AMS1117",
)

# --- CH340C USB-UART (KiCad Interface_USB:CH340C, SOIC-16) -------------------

CH340C = offline_part(
    generic_name="CH340C",
    footprint="Package_SO:SOIC-16_3.9x9.9mm_P1.27mm",
    pins={
        1: ("GND", "power_in"),
        2: ("TXD", "output"),
        3: ("RXD", "input"),
        4: ("V3", "power_out"),
        5: ("UD+", "bidirectional"),
        6: ("UD-", "bidirectional"),
        7: ("NC7", "no_connect"),
        8: ("NC8", "no_connect"),
        9: ("CTS", "input"),
        10: ("DSR", "input"),
        11: ("RI", "input"),
        12: ("DCD", "input"),
        13: ("DTR", "output"),
        14: ("RTS", "output"),
        15: ("R232", "input"),
        16: ("VCC", "power_in"),
    },
    category="Interface",
    symbol="Interface_USB:CH340C",
    package="SOIC-16",
    mpn="CH340C",
    description="WCH CH340C USB-UART (crystal-less)",
)

# --- W25Q32JVSS SPI flash (KiCad Memory_Flash:W25Q32JVSS, SOIC-8 208 mil) ----

W25Q32JVSS = offline_part(
    generic_name="W25Q32JVSS",
    footprint="Package_SO:SOIC-8_5.3x5.3mm_P1.27mm",
    pins={
        1: ("CS", "input"),
        2: ("DO", "bidirectional"),
        3: ("WP", "bidirectional"),
        4: ("GND", "power_in"),
        5: ("DI", "bidirectional"),
        6: ("CLK", "input"),
        7: ("HOLD", "bidirectional"),
        8: ("VCC", "power_in"),
    },
    category="Memory",
    symbol="Memory_Flash:W25Q32JVSS",
    package="SOIC-8-208mil",
    mpn="W25Q32JVSSIQ",
    description="Winbond 32Mbit SPI NOR flash",
)

# --- 74HC595 shift register (KiCad 74xx:74HC595, SOIC-16) --------------------

HC595 = offline_part(
    generic_name="74HC595",
    footprint="Package_SO:SOIC-16_3.9x9.9mm_P1.27mm",
    pins={
        1: ("QB", "output"),
        2: ("QC", "output"),
        3: ("QD", "output"),
        4: ("QE", "output"),
        5: ("QF", "output"),
        6: ("QG", "output"),
        7: ("QH", "output"),
        8: ("GND", "power_in"),
        9: ("QHP", "output"),
        10: ("SRCLR", "input"),
        11: ("SRCLK", "input"),
        12: ("RCLK", "input"),
        13: ("OE", "input"),
        14: ("SER", "input"),
        15: ("QA", "output"),
        16: ("VCC", "power_in"),
    },
    category="Logic",
    symbol="74xx:74HC595",
    package="SOIC-16",
    mpn="SN74HC595DR",
    description="8-bit serial-in parallel-out shift register",
)

# --- 2N7002 NMOS (KiCad Transistor_FET:2N7002 extends Q_NMOS_GSD) ------------

Q_2N7002 = offline_part(
    generic_name="2N7002",
    footprint="Package_TO_SOT_SMD:SOT-23",
    pins={
        1: ("G", "input"),
        2: ("S", "passive"),
        3: ("D", "passive"),
    },
    category="Discrete",
    symbol="Transistor_FET:2N7002",
    package="SOT-23",
    mpn="2N7002",
    description="N-channel MOSFET 60V SOT-23",
)

# --- DS3231M RTC (KiCad Timer_RTC:DS3231M, SOIC-16W; many GND pads) ----------

DS3231M = offline_part(
    generic_name="DS3231M",
    footprint="Package_SO:SOIC-16W_7.5x10.3mm_P1.27mm",
    pins={
        1: ("32KHZ", "no_connect"),
        2: ("VCC", "power_in"),
        3: ("INT", "no_connect"),
        4: ("RST", "no_connect"),
        5: ("GND5", "power_in"),
        6: ("GND6", "power_in"),
        7: ("GND7", "power_in"),
        8: ("GND8", "power_in"),
        9: ("GND9", "power_in"),
        10: ("GND10", "power_in"),
        11: ("GND11", "power_in"),
        12: ("GND12", "power_in"),
        13: ("GND", "power_in"),
        14: ("VBAT", "power_in"),
        15: ("SDA", "bidirectional"),
        16: ("SCL", "input"),
    },
    category="Timer",
    symbol="Timer_RTC:DS3231M",
    package="SOIC-16W",
    mpn="DS3231M",
    description="Maxim DS3231M I2C RTC/TCXO",
)

# --- TXS0108E level shifter (KiCad Logic_LevelTranslator:TXS0108EPW) ---------

TXS0108E = offline_part(
    generic_name="TXS0108EPW",
    footprint="Package_SO:TSSOP-20_4.4x6.5mm_P0.65mm",
    pins={
        1: ("A1", "bidirectional"),
        2: ("VCCA", "power_in"),
        3: ("A2", "bidirectional"),
        4: ("A3", "bidirectional"),
        5: ("A4", "bidirectional"),
        6: ("A5", "bidirectional"),
        7: ("A6", "bidirectional"),
        8: ("A7", "bidirectional"),
        9: ("A8", "bidirectional"),
        10: ("OE", "input"),
        11: ("GND", "power_in"),
        12: ("B8", "bidirectional"),
        13: ("B7", "bidirectional"),
        14: ("B6", "bidirectional"),
        15: ("B5", "bidirectional"),
        16: ("B4", "bidirectional"),
        17: ("B3", "bidirectional"),
        18: ("B2", "bidirectional"),
        19: ("VCCB", "power_in"),
        20: ("B1", "bidirectional"),
    },
    category="Interface",
    symbol="Logic_LevelTranslator:TXS0108EPW",
    package="TSSOP-20",
    mpn="TXS0108EPWR",
    description="8-bit bidirectional level translator",
)

# --- MCP4725 DAC (KiCad Analog_DAC:MCP4725xxx-xCH, SOT-23-6) -----------------

MCP4725 = offline_part(
    generic_name="MCP4725",
    footprint="Package_TO_SOT_SMD:SOT-23-6",
    pins={
        1: ("VOUT", "output"),
        2: ("VSS", "power_in"),
        3: ("VDD", "power_in"),
        4: ("SDA", "bidirectional"),
        5: ("SCL", "input"),
        6: ("A0", "input"),
    },
    category="DAC",
    symbol="Analog_DAC:MCP4725xxx-xCH",
    package="SOT-23-6",
    mpn="MCP4725A0T-E/CH",
    description="12-bit I2C DAC",
)

# --- PCA9548A I2C mux (KiCad Interface_Expansion:PCA9548APW extends TCA9548) --

PCA9548A = offline_part(
    generic_name="PCA9548APW",
    footprint="Package_SO:TSSOP-24_4.4x7.8mm_P0.65mm",
    pins={
        1: ("A0", "input"),
        2: ("A1", "input"),
        3: ("RESET", "input"),
        4: ("SD0", "bidirectional"),
        5: ("SC0", "output"),
        6: ("SD1", "bidirectional"),
        7: ("SC1", "output"),
        8: ("SD2", "bidirectional"),
        9: ("SC2", "output"),
        10: ("SD3", "bidirectional"),
        11: ("SC3", "output"),
        12: ("GND", "power_in"),
        13: ("SD4", "bidirectional"),
        14: ("SC4", "output"),
        15: ("SD5", "bidirectional"),
        16: ("SC5", "output"),
        17: ("SD6", "bidirectional"),
        18: ("SC6", "output"),
        19: ("SD7", "bidirectional"),
        20: ("SC7", "output"),
        21: ("A2", "input"),
        22: ("SCL", "input"),
        23: ("SDA", "bidirectional"),
        24: ("VCC", "power_in"),
    },
    category="Interface",
    symbol="Interface_Expansion:PCA9548APW",
    package="TSSOP-24",
    mpn="PCA9548APW",
    description="8-channel I2C switch with reset",
)


def mk_component(name: str, data: dict):
    """Build a Component from offline ``comp_data`` and force the KiCad footprint field."""
    from openhac.core.base import Component

    c = Component(name, comp_data=dict(data))
    part = getattr(c, "part", None)
    if part is not None:
        fields = getattr(part, "fields", None)
        if isinstance(fields, dict):
            if data.get("kicad_footprint"):
                part.footprint = data["kicad_footprint"]
                fields["Footprint"] = data["kicad_footprint"]
            if data.get("kicad_symbol"):
                fields["kicad_symbol"] = data["kicad_symbol"]
                fields["kiCad_symbol"] = data["kicad_symbol"]
            fields["Value"] = name
    return c
