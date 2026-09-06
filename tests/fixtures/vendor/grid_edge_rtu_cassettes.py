"""Recorded vendor-shaped payloads for the grid-edge RTU full-suite test.

Default pytest never HTTP-fetches. Digi-Key product blobs go through
``DigiKeyAPI._parse_product`` (named pinout). jlcsearch rows go through
``JLCPCBAPI._parse_jlcsearch_item`` then ``_component_row_from_jlc_item``
(CAT-004 two-terminal policy + package→footprint map).

Pin tables are Digi-Key ``pin_number`` / ``signal_name`` / ``pin_type`` fields,
not OpenHaC ``_offline_parts`` dicts.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_CASSETTE_DIR = Path(__file__).resolve().parent


def _pin(num: str | int, name: str, typ: str = "bidirectional") -> dict[str, str]:
    return {"pin_number": str(num), "signal_name": name, "pin_type": typ}


def _digikey_product(
    *,
    mpn: str,
    manufacturer: str,
    dk_sku: str,
    description: str,
    category: str,
    package: str,
    pinout: list[dict[str, str]],
    datasheet: str = "https://example.invalid/ds.pdf",
) -> dict[str, Any]:
    return {
        "manufacturer_part_number": mpn,
        "manufacturer": {"name": manufacturer},
        "digi_key_part_number": dk_sku,
        "product_description": description,
        "quantity_available": 1000,
        "product_url": f"https://www.digikey.com/en/products/detail/{dk_sku}",
        "primary_datasheet_url": datasheet,
        "rohs_status": "RoHS Compliant",
        "lead_free": True,
        "category": {"name": category},
        "package_type": {"name": package},
        "lifecycle_status": "Active",
        "pinout": pinout,
    }


def _stm32f103_pins() -> list[dict[str, str]]:
    named = [
        ("1", "VBAT", "power_in"),
        ("2", "PC13", "bidirectional"),
        ("3", "PC14", "bidirectional"),
        ("4", "PC15", "bidirectional"),
        ("5", "PD0", "bidirectional"),
        ("6", "PD1", "bidirectional"),
        ("7", "NRST", "input"),
        ("8", "VSSA", "power_in"),
        ("9", "VDDA", "power_in"),
        ("10", "PA0", "bidirectional"),
        ("11", "PA1", "bidirectional"),
        ("12", "PA2", "bidirectional"),
        ("13", "PA3", "bidirectional"),
        ("14", "PA4", "bidirectional"),
        ("15", "PA5", "bidirectional"),
        ("16", "PA6", "bidirectional"),
        ("17", "PA7", "bidirectional"),
        ("18", "PB0", "bidirectional"),
        ("19", "PB1", "bidirectional"),
        ("20", "PB2", "bidirectional"),
        ("21", "PB10", "bidirectional"),
        ("22", "PB11", "bidirectional"),
        ("23", "VSS_1", "power_in"),
        ("24", "VDD_1", "power_in"),
        ("25", "PB12", "bidirectional"),
        ("26", "PB13", "bidirectional"),
        ("27", "PB14", "bidirectional"),
        ("28", "PB15", "bidirectional"),
        ("29", "PA8", "bidirectional"),
        ("30", "PA9", "bidirectional"),
        ("31", "PA10", "bidirectional"),
        ("32", "PA11", "bidirectional"),
        ("33", "PA12", "bidirectional"),
        ("34", "PA13", "bidirectional"),
        ("35", "VSS_2", "power_in"),
        ("36", "VDD_2", "power_in"),
        ("37", "PA14", "bidirectional"),
        ("38", "PA15", "bidirectional"),
        ("39", "PB3", "bidirectional"),
        ("40", "PB4", "bidirectional"),
        ("41", "PB5", "bidirectional"),
        ("42", "PB6", "bidirectional"),
        ("43", "PB7", "bidirectional"),
        ("44", "BOOT0", "input"),
        ("45", "PB8", "bidirectional"),
        ("46", "PB9", "bidirectional"),
        ("47", "VSS_3", "power_in"),
        ("48", "VDD_3", "power_in"),
    ]
    return [_pin(*r) for r in named]


def _esp32s3_pins() -> list[dict[str, str]]:
    named = [
        ("1", "GND", "power_in"),
        ("2", "3V3", "power_in"),
        ("3", "EN", "input"),
        ("4", "IO4", "bidirectional"),
        ("5", "IO5", "bidirectional"),
        ("6", "IO6", "bidirectional"),
        ("7", "IO7", "bidirectional"),
        ("8", "IO15", "bidirectional"),
        ("9", "IO16", "bidirectional"),
        ("10", "IO17", "bidirectional"),
        ("11", "IO18", "bidirectional"),
        ("12", "IO8", "bidirectional"),
        ("13", "IO19", "bidirectional"),
        ("14", "IO20", "bidirectional"),
        ("15", "IO3", "bidirectional"),
        ("16", "IO46", "bidirectional"),
        ("17", "IO9", "bidirectional"),
        ("18", "IO10", "bidirectional"),
        ("19", "IO11", "bidirectional"),
        ("20", "IO12", "bidirectional"),
        ("21", "IO13", "bidirectional"),
        ("22", "IO14", "bidirectional"),
        ("23", "IO21", "bidirectional"),
        ("24", "IO47", "bidirectional"),
        ("25", "IO48", "bidirectional"),
        ("26", "IO45", "bidirectional"),
        ("27", "IO0", "bidirectional"),
        ("28", "IO35", "bidirectional"),
        ("29", "IO36", "bidirectional"),
        ("30", "IO37", "bidirectional"),
        ("31", "IO38", "bidirectional"),
        ("32", "IO39", "bidirectional"),
        ("33", "IO40", "bidirectional"),
        ("34", "IO41", "bidirectional"),
        ("35", "IO42", "bidirectional"),
        ("36", "RXD0", "bidirectional"),
        ("37", "TXD0", "bidirectional"),
        ("38", "IO2", "bidirectional"),
        ("39", "IO1", "bidirectional"),
        ("40", "GND_P40", "power_in"),
        ("41", "EPAD", "power_in"),
    ]
    return [_pin(*r) for r in named]


def _usb_c_pins() -> list[dict[str, str]]:
    return [
        _pin("A1", "GND", "power_in"),
        _pin("A4", "VBUS", "power_in"),
        _pin("A5", "CC1", "bidirectional"),
        _pin("A6", "DP", "bidirectional"),
        _pin("A7", "DN", "bidirectional"),
        _pin("A8", "SBU1", "bidirectional"),
        _pin("A9", "VBUS_A9", "power_in"),
        _pin("A12", "GND_A12", "power_in"),
        _pin("B1", "GND_B1", "power_in"),
        _pin("B4", "VBUS_B4", "power_in"),
        _pin("B5", "CC2", "bidirectional"),
        _pin("B6", "DN_B", "bidirectional"),
        _pin("B7", "DP_B", "bidirectional"),
        _pin("B8", "SBU2", "bidirectional"),
        _pin("B9", "VBUS_B9", "power_in"),
        _pin("B12", "GND_B12", "power_in"),
        _pin("S1", "SHIELD", "passive"),
    ]


def _header_pins(n: int) -> list[dict[str, str]]:
    return [_pin(i, f"P{i}", "passive") for i in range(1, n + 1)]


def _mpu6050_pins() -> list[dict[str, str]]:
    pins = {i: _pin(i, f"NC{i}", "no_connect") for i in range(1, 25)}
    pins[8] = _pin(8, "VDDIO", "power_in")
    pins[9] = _pin(9, "AD0", "input")
    pins[12] = _pin(12, "INT", "no_connect")
    pins[13] = _pin(13, "VDD", "power_in")
    pins[18] = _pin(18, "GND", "power_in")
    pins[23] = _pin(23, "SCL", "input")
    pins[24] = _pin(24, "SDA", "bidirectional")
    return [pins[i] for i in range(1, 25)]


def _pca9548_pins() -> list[dict[str, str]]:
    named = [
        ("1", "A0", "input"),
        ("2", "A1", "input"),
        ("3", "RESET", "input"),
        ("4", "SD0", "bidirectional"),
        ("5", "SC0", "output"),
        ("6", "SD1", "bidirectional"),
        ("7", "SC1", "output"),
        ("8", "SD2", "bidirectional"),
        ("9", "SC2", "output"),
        ("10", "SD3", "bidirectional"),
        ("11", "SC3", "output"),
        ("12", "GND", "power_in"),
        ("13", "SD4", "bidirectional"),
        ("14", "SC4", "output"),
        ("15", "SD5", "bidirectional"),
        ("16", "SC5", "output"),
        ("17", "SD6", "bidirectional"),
        ("18", "SC6", "output"),
        ("19", "SD7", "bidirectional"),
        ("20", "SC7", "output"),
        ("21", "A2", "input"),
        ("22", "SCL", "input"),
        ("23", "SDA", "bidirectional"),
        ("24", "VCC", "power_in"),
    ]
    return [_pin(*r) for r in named]


def _hc595_pins() -> list[dict[str, str]]:
    named = [
        ("1", "QB", "output"),
        ("2", "QC", "output"),
        ("3", "QD", "output"),
        ("4", "QE", "output"),
        ("5", "QF", "output"),
        ("6", "QG", "output"),
        ("7", "QH", "output"),
        ("8", "GND", "power_in"),
        ("9", "QHP", "output"),
        ("10", "SRCLR", "input"),
        ("11", "SRCLK", "input"),
        ("12", "RCLK", "input"),
        ("13", "OE", "input"),
        ("14", "SER", "input"),
        ("15", "QA", "output"),
        ("16", "VCC", "power_in"),
    ]
    return [_pin(*r) for r in named]


def _ch340c_pins() -> list[dict[str, str]]:
    named = [
        ("1", "GND", "power_in"),
        ("2", "TXD", "output"),
        ("3", "RXD", "input"),
        ("4", "V3", "power_out"),
        ("5", "UDP", "bidirectional"),
        ("6", "UDM", "bidirectional"),
        ("7", "NC7", "no_connect"),
        ("8", "NC8", "no_connect"),
        ("9", "CTS", "input"),
        ("10", "DSR", "input"),
        ("11", "RI", "input"),
        ("12", "DCD", "input"),
        ("13", "DTR", "output"),
        ("14", "RTS", "output"),
        ("15", "R232", "input"),
        ("16", "VCC", "power_in"),
    ]
    return [_pin(*r) for r in named]


def _ds3231_pins() -> list[dict[str, str]]:
    named = [
        ("1", "KHZ32", "no_connect"),
        ("2", "VCC", "power_in"),
        ("3", "INT", "no_connect"),
        ("4", "RST", "no_connect"),
        ("5", "GND5", "power_in"),
        ("6", "GND6", "power_in"),
        ("7", "GND7", "power_in"),
        ("8", "GND8", "power_in"),
        ("9", "GND9", "power_in"),
        ("10", "GND10", "power_in"),
        ("11", "GND11", "power_in"),
        ("12", "GND12", "power_in"),
        ("13", "GND", "power_in"),
        ("14", "VBAT", "power_in"),
        ("15", "SDA", "bidirectional"),
        ("16", "SCL", "input"),
    ]
    return [_pin(*r) for r in named]


def _txs0108_pins() -> list[dict[str, str]]:
    named = [
        ("1", "A1", "bidirectional"),
        ("2", "VCCA", "power_in"),
        ("3", "A2", "bidirectional"),
        ("4", "A3", "bidirectional"),
        ("5", "A4", "bidirectional"),
        ("6", "A5", "bidirectional"),
        ("7", "A6", "bidirectional"),
        ("8", "A7", "bidirectional"),
        ("9", "A8", "bidirectional"),
        ("10", "OE", "input"),
        ("11", "GND", "power_in"),
        ("12", "B8", "bidirectional"),
        ("13", "B7", "bidirectional"),
        ("14", "B6", "bidirectional"),
        ("15", "B5", "bidirectional"),
        ("16", "B4", "bidirectional"),
        ("17", "B3", "bidirectional"),
        ("18", "B2", "bidirectional"),
        ("19", "VCCB", "power_in"),
        ("20", "B1", "bidirectional"),
    ]
    return [_pin(*r) for r in named]


def _rfm95_pins() -> list[dict[str, str]]:
    named = [
        ("1", "GND", "power_in"),
        ("2", "MISO", "bidirectional"),
        ("3", "MOSI", "input"),
        ("4", "SCK", "input"),
        ("5", "NSS", "input"),
        ("6", "RESET", "input"),
        ("7", "DIO0", "bidirectional"),
        ("8", "DIO1", "bidirectional"),
        ("9", "DIO2", "bidirectional"),
        ("10", "DIO3", "bidirectional"),
        ("11", "DIO4", "bidirectional"),
        ("12", "DIO5", "bidirectional"),
        ("13", "VDD", "power_in"),
        ("14", "GND14", "power_in"),
        ("15", "GND15", "power_in"),
        ("16", "GND16", "power_in"),
    ]
    return [_pin(*r) for r in named]


# Post-parse catalog packing (package → stock KiCad id). Not a pin encyclopedia.
_PACKING: dict[str, tuple[str, str]] = {
    "AMS1117_3V3": ("Regulator_Linear:AMS1117-3.3", "Package_TO_SOT_SMD:SOT-223-3_TabPin2"),
    "USB_C_HRO_TYPE_C_31_M_12": (
        "Connector:USB_C_Receptacle_USB2.0_16P",
        "Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12",
    ),
    "ESP32_S3_WROOM_1": ("RF_Module:ESP32-S3-WROOM-1", "RF_Module:ESP32-S3-WROOM-1"),
    "STM32F103C8T6": ("MCU_ST_STM32F1:STM32F103C8Tx", "Package_QFP:LQFP-48_7x7mm_P0.5mm"),
    "CH340C": ("Interface_USB:CH340C", "Package_SO:SOIC-16_3.9x9.9mm_P1.27mm"),
    "AD620": ("Amplifier_Instrumentation:AD620", "Package_DIP:DIP-8_W7.62mm"),
    "D_1N4007": ("Device:D", "Diode_SMD:D_SOD-123"),
    "OPTO_PC817": ("Isolator:PC817", "Package_SO:SOIC-4_4.55x2.6mm_P1.27mm"),
    "CAN_TJA1051T": ("Interface_CAN_LIN:TJA1051", "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm"),
    "RS485_MAX3485": ("Interface_UART:MAX3485", "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm"),
    "74HC595": ("74xx:74HC595", "Package_SO:SOIC-16_3.9x9.9mm_P1.27mm"),
    "2N7002": ("Transistor_FET:2N7002", "Package_TO_SOT_SMD:SOT-23"),
    "PCA9548APW": ("Interface_Expansion:PCA9548APW", "Package_SO:TSSOP-24_4.4x7.8mm_P0.65mm"),
    "ADC_ADS1115": ("Analog_ADC:ADS1115IDGS", "Package_SO:VSSOP-10_3x3mm_P0.5mm"),
    "MCP4725": ("Analog_DAC:MCP4725xxx-xCH", "Package_TO_SOT_SMD:SOT-23-6"),
    "TXS0108EPW": ("Logic_LevelTranslator:TXS0108EPW", "Package_SO:TSSOP-20_4.4x6.5mm_P0.65mm"),
    "DS3231M": ("Timer_RTC:DS3231M", "Package_SO:SOIC-16W_7.5x10.3mm_P1.27mm"),
    "EEPROM_24LC256": ("Memory_EEPROM:24LC256", "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm"),
    "W25Q32JVSS": ("Memory_Flash:W25Q32JVSS", "Package_SO:SOIC-8_5.3x5.3mm_P1.27mm"),
    "IMU_MPU6050": ("Sensor_Motion:MPU-6050", "Sensor_Motion:InvenSense_QFN-24_4x4mm_P0.5mm"),
    "SENSOR_BMP280": (
        "Sensor_Pressure:BMP280",
        "Package_LGA:Bosch_LGA-8_2x2.5mm_P0.65mm_ClockwisePinNumbering",
    ),
    "OLED_SSD1306": ("Display_Graphic:OLED-128O064D", "Display:Adafruit_SSD1306"),
    "RFM95_LORA": ("RF_Module:RFM95W-868S2", "RF_Module:HOPERF_RFM9XW_SMD"),
    "NRF24L01": ("RF:NRF24L01_Breakout", "RF_Module:nRF24L01_Breakout"),
    "MICROSD_SLOT": ("Connector:Micro_SD_Card", "Connector_Card:microSD_HC_Molex_47219-2001"),
    "HDR_1x04": (
        "Connector:Conn_01x04_Pin",
        "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical",
    ),
    "HDR_1x06": (
        "Connector:Conn_01x06_Pin",
        "Connector_PinHeader_2.54mm:PinHeader_1x06_P2.54mm_Vertical",
    ),
    "XTAL_8MHZ": ("Device:Crystal_GND2", "Crystal:Crystal_SMD_3225-4Pin_3.2x2.5mm"),
}


def digikey_records() -> list[dict[str, Any]]:
    """One cassette row per IC / connector / crystal. ``product`` is Digi-Key shaped."""
    specs: list[tuple[str, str, str, str, str, str, str, list[dict[str, str]]]] = [
        ("AMS1117_3V3", "AMS1117-3.3", "AMS", "296-AMS1117", "3.3V LDO", "PMIC - Voltage Regulators", "SOT-223",
         [_pin(1, "GND", "power_in"), _pin(2, "VOUT", "power_out"), _pin(3, "VIN", "power_in")]),
        ("USB_C_HRO_TYPE_C_31_M_12", "TYPE-C-31-M-12", "HRO", "HRO-USBC", "USB-C receptacle", "Connectors", "USB-C",
         _usb_c_pins()),
        ("ESP32_S3_WROOM_1", "ESP32-S3-WROOM-1", "Espressif", "ESP-S3-WROOM", "ESP32-S3 module", "RF Modules",
         "ESP32-S3-WROOM-1", _esp32s3_pins()),
        ("STM32F103C8T6", "STM32F103C8T6", "STMicroelectronics", "497-STM32F103", "MCU LQFP-48", "Microcontrollers",
         "LQFP-48", _stm32f103_pins()),
        ("CH340C", "CH340C", "WCH", "CH340C-ND", "USB UART", "Interface", "SOIC-16", _ch340c_pins()),
        ("AD620", "AD620ANZ", "Analog Devices", "AD620ANZ-ND", "Instrumentation amp", "Amplifiers", "DIP-8",
         [_pin(1, "RG1", "passive"), _pin(2, "INN", "input"), _pin(3, "INP", "input"),
          _pin(4, "VSM", "power_in"), _pin(5, "REF", "passive"), _pin(6, "OUT", "output"),
          _pin(7, "VSP", "power_in"), _pin(8, "RG2", "passive")]),
        ("D_1N4007", "1N4007", "Vishay", "1N4007CT-ND", "1A rectifier", "Diodes", "SOD-123",
         [_pin(1, "K", "passive"), _pin(2, "A", "passive")]),
        ("OPTO_PC817", "PC817", "Sharp", "PC817-ND", "Phototransistor opto", "Isolators", "SOIC-4",
         [_pin(1, "A", "passive"), _pin(2, "K", "passive"), _pin(3, "E", "passive"), _pin(4, "C", "passive")]),
        ("CAN_TJA1051T", "TJA1051T", "NXP", "TJA1051T-ND", "CAN transceiver", "Interface", "SOIC-8",
         [_pin(1, "TXD", "input"), _pin(2, "GND", "power_in"), _pin(3, "VCC", "power_in"),
          _pin(4, "RXD", "output"), _pin(5, "VIO", "power_in"), _pin(6, "CANL", "bidirectional"),
          _pin(7, "CANH", "bidirectional"), _pin(8, "S", "input")]),
        ("RS485_MAX3485", "MAX3485ESA+", "Analog Devices", "MAX3485-ND", "RS-485 transceiver", "Interface", "SOIC-8",
         [_pin(1, "RO", "output"), _pin(2, "RE", "input"), _pin(3, "DE", "input"), _pin(4, "DI", "input"),
          _pin(5, "GND", "power_in"), _pin(6, "A", "bidirectional"), _pin(7, "B", "bidirectional"),
          _pin(8, "VCC", "power_in")]),
        ("74HC595", "SN74HC595DR", "Texas Instruments", "296-74HC595", "Shift register", "Logic", "SOIC-16",
         _hc595_pins()),
        ("2N7002", "2N7002", "Onsemi", "2N7002-ND", "N-MOSFET", "Discrete MOSFET", "SOT-23",
         [_pin(1, "G", "input"), _pin(2, "S", "passive"), _pin(3, "D", "passive")]),
        ("PCA9548APW", "PCA9548APW", "NXP", "PCA9548A-ND", "I2C mux", "Interface", "TSSOP-24", _pca9548_pins()),
        ("ADC_ADS1115", "ADS1115IDGSR", "Texas Instruments", "296-ADS1115", "16-bit ADC", "Data Conversion", "VSSOP-10",
         [_pin(1, "ADDR", "input"), _pin(2, "ALERT", "no_connect"), _pin(3, "GND", "power_in"),
          _pin(4, "AIN0", "input"), _pin(5, "AIN1", "input"), _pin(6, "AIN2", "input"),
          _pin(7, "AIN3", "input"), _pin(8, "SDA", "bidirectional"), _pin(9, "SCL", "input"),
          _pin(10, "VDD", "power_in")]),
        ("MCP4725", "MCP4725A0T-E/CH", "Microchip", "MCP4725-ND", "12-bit DAC", "Data Conversion", "SOT-23-6",
         [_pin(1, "VOUT", "output"), _pin(2, "VSS", "power_in"), _pin(3, "VDD", "power_in"),
          _pin(4, "SDA", "bidirectional"), _pin(5, "SCL", "input"), _pin(6, "A0", "input")]),
        ("TXS0108EPW", "TXS0108EPWR", "Texas Instruments", "296-TXS0108", "Level translator", "Logic", "TSSOP-20",
         _txs0108_pins()),
        ("DS3231M", "DS3231M", "Maxim", "DS3231M-ND", "I2C RTC", "Clock/Timing", "SOIC-16W", _ds3231_pins()),
        ("EEPROM_24LC256", "24LC256", "Microchip", "24LC256-ND", "I2C EEPROM", "Memory", "SOIC-8",
         [_pin(1, "A0", "input"), _pin(2, "A1", "input"), _pin(3, "A2", "input"), _pin(4, "VSS", "power_in"),
          _pin(5, "SDA", "bidirectional"), _pin(6, "SCL", "input"), _pin(7, "WP", "input"),
          _pin(8, "VCC", "power_in")]),
        ("W25Q32JVSS", "W25Q32JVSSIQ", "Winbond", "W25Q32-ND", "SPI NOR flash", "Memory", "SOIC-8-208mil",
         [_pin(1, "CS", "input"), _pin(2, "DO", "bidirectional"), _pin(3, "WP", "bidirectional"),
          _pin(4, "GND", "power_in"), _pin(5, "DI", "bidirectional"), _pin(6, "CLK", "input"),
          _pin(7, "HOLD", "bidirectional"), _pin(8, "VCC", "power_in")]),
        ("IMU_MPU6050", "MPU-6050", "TDK InvenSense", "MPU6050-ND", "6-axis IMU", "Sensors", "QFN-24",
         _mpu6050_pins()),
        ("SENSOR_BMP280", "BMP280", "Bosch", "BMP280-ND", "Pressure sensor", "Sensors", "LGA-8",
         [_pin(1, "GND", "power_in"), _pin(2, "CSB", "input"), _pin(3, "SDI", "bidirectional"),
          _pin(4, "SCK", "input"), _pin(5, "SDO", "no_connect"), _pin(6, "VDDIO", "power_in"),
          _pin(7, "GND7", "power_in"), _pin(8, "VDD", "power_in")]),
        ("OLED_SSD1306", "SSD1306", "Solomon", "SSD1306-ND", "OLED module", "Optoelectronics", "OLED",
         [_pin(1, "VIN", "power_in"), _pin(2, "GND", "power_in"), _pin(3, "P3V3", "no_connect"),
          _pin(4, "NC4", "no_connect"), _pin(5, "NC5", "no_connect"), _pin(6, "NC6", "no_connect"),
          _pin(7, "SCL", "input"), _pin(8, "SDA", "bidirectional")]),
        ("RFM95_LORA", "RFM95W", "HopeRF", "RFM95-ND", "LoRa module", "RF Modules", "RFM9X", _rfm95_pins()),
        ("NRF24L01", "nRF24L01+", "Nordic", "NRF24-ND", "2.4GHz transceiver", "RF Modules", "nRF24L01",
         [_pin(1, "GND", "power_in"), _pin(2, "VCC", "power_in"), _pin(3, "CE", "input"),
          _pin(4, "CSN", "input"), _pin(5, "SCK", "input"), _pin(6, "MOSI", "input"),
          _pin(7, "MISO", "bidirectional"), _pin(8, "IRQ", "no_connect")]),
        ("MICROSD_SLOT", "47219-2001", "Molex", "WM47219-ND", "microSD connector", "Connectors", "microSD",
         [_pin(1, "DAT2", "bidirectional"), _pin(2, "DAT3_CS", "bidirectional"),
          _pin(3, "CMD_DI", "bidirectional"), _pin(4, "VDD", "power_in"), _pin(5, "CLK", "input"),
          _pin(6, "VSS", "power_in"), _pin(7, "DAT0_DO", "bidirectional"), _pin(8, "DAT1", "bidirectional"),
          _pin(9, "CD", "passive")]),
        ("HDR_1x04", "HDR-1x04", "Generic", "HDR4-ND", "1x4 pin header", "Connectors", "PinHeader 2.54mm",
         _header_pins(4)),
        ("HDR_1x06", "HDR-1x06", "Generic", "HDR6-ND", "1x6 pin header", "Connectors", "PinHeader 2.54mm",
         _header_pins(6)),
        ("XTAL_8MHZ", "X32258M", "ECS", "X3225-8M-ND", "8 MHz crystal", "Crystals", "3225",
         [_pin(1, "X1", "passive"), _pin(2, "GND", "passive"), _pin(3, "X2", "passive"),
          _pin(4, "GND2", "passive")]),
    ]
    out: list[dict[str, Any]] = []
    for gn, mpn, mfr, sku, desc, cat, pkg, pins in specs:
        sym, fp = _PACKING[gn]
        out.append(
            {
                "generic_name": gn,
                "kicad_symbol": sym,
                "kicad_footprint": fp,
                "db_category": cat,
                "product": _digikey_product(
                    mpn=mpn,
                    manufacturer=mfr,
                    dk_sku=sku,
                    description=desc,
                    category=cat,
                    package=pkg,
                    pinout=pins,
                ),
            }
        )
    return out


def jlcsearch_payload() -> dict[str, list[dict[str, Any]]]:
    """Typed jlcsearch category lists (resistance/capacitance in SI units)."""
    def r(lcsc: int, mfr: str, ohms: float, pkg: str = "0805") -> dict[str, Any]:
        return {
            "lcsc": lcsc,
            "mfr": mfr,
            "package": pkg,
            "resistance": ohms,
            "description": f"{ohms} ohm {pkg}",
            "stock": 50000,
            "price": '[{"qFrom": 1, "qTo": null, "price": 0.01}]',
            "category": "Resistors",
        }

    def c(lcsc: int, mfr: str, farads: float, pkg: str) -> dict[str, Any]:
        return {
            "lcsc": lcsc,
            "mfr": mfr,
            "package": pkg,
            "capacitance": farads,
            "description": f"{farads} F {pkg}",
            "stock": 40000,
            "price": '[{"qFrom": 1, "qTo": null, "price": 0.02}]',
            "category": "Capacitors",
        }

    return {
        "resistors": [
            r(17513, "RC0805FR-0710KL", 10000),
            r(17512, "RC0805FR-071KL", 1000),
            r(23149, "RC0805FR-074K7L", 4700),
            r(23150, "RC0805FR-075K1L", 5100),
            r(17520, "RC0805FR-07100KL", 100000),
            r(17521, "RC0805FR-07120RL", 120),
            r(17522, "RC0805FR-0749RL", 49),
            r(17523, "RC0805FR-071RL", 1),
        ],
        "capacitors": [
            c(14663, "CL10B104KB8NNNC", 100e-9, "0603"),
            c(15850, "CL21A106KAYNNNE", 10e-6, "0805"),
            c(15851, "CL21A226KAYNNNE", 22e-6, "0805"),
            c(15852, "CL21A107KAYNNNE", 100e-6, "0805"),
            c(15853, "CL21A475KAYNNNE", 4.7e-6, "0805"),
            c(15854, "CL10C180JB8NNNC", 18e-12, "0603"),
        ],
        "leds": [
            {
                "lcsc": 2286,
                "mfr": "19-217/GHC-YR1S2/3T",
                "package": "0805",
                "color": "Green",
                "description": "Green LED 0805",
                "stock": 20000,
                "price": '[{"qFrom": 1, "qTo": null, "price": 0.03}]',
                "category": "LEDs",
            }
        ],
        "fuses": [
            {
                "lcsc": 18980,
                "mfr": "F0805",
                "package": "0805",
                "description": "2A fuse 0805",
                "stock": 8000,
                "price": '[{"qFrom": 1, "qTo": null, "price": 0.05}]',
                "category": "Fuses",
            }
        ],
    }


def dump_cassette_json(dest: Path | None = None) -> tuple[Path, Path]:
    dest = dest or _CASSETTE_DIR
    dest.mkdir(parents=True, exist_ok=True)
    dk = dest / "grid_edge_rtu_digikey.json"
    jlc = dest / "grid_edge_rtu_jlcsearch.json"
    dk.write_text(json.dumps(digikey_records(), indent=2) + "\n", encoding="utf-8")
    jlc.write_text(json.dumps(jlcsearch_payload(), indent=2) + "\n", encoding="utf-8")
    return dk, jlc


def load_cassette_json(src: Path | None = None) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    src = src or _CASSETTE_DIR
    dk_path = src / "grid_edge_rtu_digikey.json"
    jlc_path = src / "grid_edge_rtu_jlcsearch.json"
    if dk_path.is_file() and jlc_path.is_file():
        dk = json.loads(dk_path.read_text(encoding="utf-8"))
        jlc = json.loads(jlc_path.read_text(encoding="utf-8"))
        return dk, jlc
    return digikey_records(), jlcsearch_payload()


def ingest_vendor_cassettes(dm, *, cassette_dir: Path | None = None) -> dict[str, int]:
    """Parse cassettes with real vendor parsers and insert a packed catalog. No HTTP."""
    from openhac.database.vendor_cassettes import ingest_cassette_directory

    root = cassette_dir if cassette_dir is not None else Path(__file__).resolve().parent
    return ingest_cassette_directory(dm, root)
