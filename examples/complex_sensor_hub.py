"""
complex_sensor_hub.py — ESP32-C3 + BMP280 + EEPROM I2C sensor hub.

USB-C → LDO → ESP32-C3-WROOM-02 + Bosch BMP280 + 24LC256 + I2C header.
"""

from __future__ import annotations

import sys
from pathlib import Path

_EX = Path(__file__).resolve().parent
if str(_EX) not in sys.path:
    sys.path.insert(0, str(_EX))

import openhac.core  # noqa: F401
from openhac.core import Board
from openhac.core.base import Module
from openhac.core.net import Net

from _offline_parts import (
    AMS1117_33,
    BMP280,
    C_0603,
    C_0805,
    EEPROM_24LC256,
    ESP32_C3_WROOM02,
    HEADER_1x04,
    LED_0805,
    R_0805,
    USB_C_HRO,
    mk_component as _mk,
)


class UsbJack(Module):
    def __init__(self) -> None:
        super().__init__("UsbJack")
        self.vbus, self.gnd = Net("VBUS_5V"), Net("GND")
        self.usb = self.add(_mk("USB_C", USB_C_HRO))
        for p in ("A4", "A9", "B4", "B9"):
            self.usb[p] += self.vbus
        for p in ("A1", "A12", "B1", "B12"):
            self.usb[p] += self.gnd
        self.usb["S1"] += self.gnd
        self.usb.nc_unused_pins()
        self.pwr = self.declare_interface("pwr_5v", self.vbus, self.gnd)


class UsbCcStraps(Module):
    def __init__(self) -> None:
        super().__init__("UsbCcStraps")
        self.vbus, self.gnd = Net("VBUS_5V"), Net("GND")
        self.cc1, self.cc2 = Net("USB_CC1"), Net("USB_CC2")
        self.r1 = self.add(_mk("R_CC1_5K1", R_0805("R_CC1_5K1", "5.1k")))
        self.r2 = self.add(_mk("R_CC2_5K1", R_0805("R_CC2_5K1", "5.1k")))
        self.cin = self.add(_mk("C_VBUS_10U", C_0805("C_VBUS_10U", "10uF")))
        self.r1[1] += self.cc1
        self.r1[2] += self.gnd
        self.r2[1] += self.cc2
        self.r2[2] += self.gnd
        self.cin[1] += self.vbus
        self.cin[2] += self.gnd
        self.pwr = self.declare_interface("pwr_5v", self.vbus, self.gnd)


class LdoChip(Module):
    def __init__(self) -> None:
        super().__init__("LdoChip")
        self.vin, self.v3v3, self.gnd = Net("VBUS_5V"), Net("3V3"), Net("GND")
        self.ldo = self.add(_mk("AMS1117_3V3", AMS1117_33))
        self.ldo["VIN"] += self.vin
        self.ldo["GND"] += self.gnd
        self.ldo["VOUT"] += self.v3v3
        self.pwr_in = self.declare_interface("pwr_5v", self.vin, self.gnd)
        self.pwr_out = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)


class LdoCaps(Module):
    def __init__(self) -> None:
        super().__init__("LdoCaps")
        self.vin, self.v3v3, self.gnd = Net("VBUS_5V"), Net("3V3"), Net("GND")
        self.cin = self.add(_mk("C_LDO_IN_10U", C_0805("C_LDO_IN_10U", "10uF")))
        self.cout = self.add(_mk("C_LDO_OUT_10U", C_0805("C_LDO_OUT_10U", "10uF")))
        self.cby = self.add(_mk("C_LDO_OUT_100N", C_0603("C_LDO_OUT_100N", "100nF")))
        self.cin[1] += self.vin
        self.cin[2] += self.gnd
        self.cout[1] += self.v3v3
        self.cout[2] += self.gnd
        self.cby[1] += self.v3v3
        self.cby[2] += self.gnd
        self.pwr_5v = self.declare_interface("pwr_5v", self.vin, self.gnd)
        self.pwr_3v3 = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)


class Esp32c3Module(Module):
    def __init__(self) -> None:
        super().__init__("Esp32c3Module")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.en = Net("EN")
        self.sda, self.scl = Net("I2C_SDA"), Net("I2C_SCL")
        self.io2 = Net("IO2")
        self.mcu = self.add(_mk("ESP32_C3_WROOM_02", ESP32_C3_WROOM02))
        self.mcu[1] += self.v3v3
        self.mcu[9] += self.gnd
        self.mcu[19] += self.gnd
        self.mcu[2] += self.en
        self.mcu[7] += self.sda
        self.mcu[10] += self.scl
        self.mcu[16] += self.io2
        self.mcu.nc_unused_pins()
        self.pwr = self.declare_interface("pwr", self.v3v3, self.gnd)
        self.boot = self.declare_interface("boot", self.en, self.gnd)
        self.i2c = self.declare_interface("i2c", self.sda, self.scl, self.gnd)
        self.led_net = self.declare_interface("led", self.io2, self.gnd)


class EspLocalCaps(Module):
    def __init__(self) -> None:
        super().__init__("EspLocalCaps")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.c_bulk = self.add(_mk("C_MCU_10U", C_0805("C_MCU_10U", "10uF")))
        self.c_dec = self.add(_mk("C_MCU_100N", C_0603("C_MCU_100N", "100nF")))
        self.c_bulk[1] += self.v3v3
        self.c_bulk[2] += self.gnd
        self.c_dec[1] += self.v3v3
        self.c_dec[2] += self.gnd
        self.pwr = self.declare_interface("pwr", self.v3v3, self.gnd)


class EnPullup(Module):
    def __init__(self) -> None:
        super().__init__("EnPullup")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.en = Net("EN")
        self.r = self.add(_mk("R_EN_10K", R_0805("R_EN_10K", "10k")))
        self.r[1] += self.v3v3
        self.r[2] += self.en
        self.pwr = self.declare_interface("pwr", self.v3v3, self.gnd)
        self.boot = self.declare_interface("boot", self.en, self.gnd)


class StatusLed(Module):
    def __init__(self) -> None:
        super().__init__("StatusLed")
        self.gnd, self.io2 = Net("GND"), Net("IO2")
        self.r = self.add(_mk("R_LED_1K", R_0805("R_LED_1K", "1k")))
        self.led = self.add(_mk("LED_STATUS", LED_0805("LED_STATUS")))
        self.r[1] += self.io2
        self.r[2] += self.led["A"]
        self.led["K"] += self.gnd
        self.led_if = self.declare_interface("led", self.io2, self.gnd)


class Bmp280Chip(Module):
    def __init__(self) -> None:
        super().__init__("Bmp280Chip")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.sda, self.scl = Net("I2C_SDA"), Net("I2C_SCL")
        self.ic = self.add(_mk("BMP280", BMP280))
        self.ic["VDD"] += self.v3v3
        self.ic["VDDIO"] += self.v3v3
        self.ic[1] += self.gnd
        self.ic[7] += self.gnd
        self.ic["SDI"] += self.sda
        self.ic["SCK"] += self.scl
        self.ic["CSB"] += self.v3v3  # I2C mode
        self.ic["SDO"] += self.gnd  # addr 0x76
        self.pwr = self.declare_interface("pwr", self.v3v3, self.gnd)
        self.i2c = self.declare_interface("i2c", self.sda, self.scl, self.gnd)


class BmpLocalCap(Module):
    def __init__(self) -> None:
        super().__init__("BmpLocalCap")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.c = self.add(_mk("C_BMP_100N", C_0603("C_BMP_100N", "100nF")))
        self.c[1] += self.v3v3
        self.c[2] += self.gnd
        self.pwr = self.declare_interface("pwr", self.v3v3, self.gnd)


class EepromChip(Module):
    def __init__(self) -> None:
        super().__init__("EepromChip")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.sda, self.scl = Net("I2C_SDA"), Net("I2C_SCL")
        self.ic = self.add(_mk("EEPROM_24LC256", EEPROM_24LC256))
        self.ic["VCC"] += self.v3v3
        self.ic["VSS"] += self.gnd
        self.ic["SDA"] += self.sda
        self.ic["SCL"] += self.scl
        self.ic["WP"] += self.gnd
        for a in ("A0", "A1", "A2"):
            self.ic[a] += self.gnd
        self.pwr = self.declare_interface("pwr", self.v3v3, self.gnd)
        self.i2c = self.declare_interface("i2c", self.sda, self.scl, self.gnd)


class I2cPullups(Module):
    def __init__(self) -> None:
        super().__init__("I2cPullups")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.sda, self.scl = Net("I2C_SDA"), Net("I2C_SCL")
        self.c = self.add(_mk("C_I2C_100N", C_0603("C_I2C_100N", "100nF")))
        self.r_sda = self.add(_mk("R_SDA_4K7", R_0805("R_SDA_4K7", "4.7k")))
        self.r_scl = self.add(_mk("R_SCL_4K7", R_0805("R_SCL_4K7", "4.7k")))
        self.c[1] += self.v3v3
        self.c[2] += self.gnd
        self.r_sda[1] += self.v3v3
        self.r_sda[2] += self.sda
        self.r_scl[1] += self.v3v3
        self.r_scl[2] += self.scl
        self.pwr = self.declare_interface("pwr", self.v3v3, self.gnd)
        self.i2c = self.declare_interface("i2c", self.sda, self.scl, self.gnd)


class I2cHeader(Module):
    def __init__(self) -> None:
        super().__init__("I2cHeader")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.sda, self.scl = Net("I2C_SDA"), Net("I2C_SCL")
        self.hdr = self.add(_mk("HDR_I2C", HEADER_1x04))
        self.hdr[1] += self.v3v3
        self.hdr[2] += self.gnd
        self.hdr[3] += self.sda
        self.hdr[4] += self.scl
        self.pwr = self.declare_interface("pwr", self.v3v3, self.gnd)
        self.i2c = self.declare_interface("i2c", self.sda, self.scl, self.gnd)


def build_board() -> Board:
    board = Board(
        size_mm=None,
        layers=2,
        compile_goal="fabrication",
        declared_supply_voltages_v={"VBUS_5V": 5.0, "3V3": 3.3},
    )
    usb, cc = UsbJack(), UsbCcStraps()
    ldo, ldo_c = LdoChip(), LdoCaps()
    esp, esp_c = Esp32c3Module(), EspLocalCaps()
    en, led = EnPullup(), StatusLed()
    bmp, bmp_c = Bmp280Chip(), BmpLocalCap()
    ee, pu, hdr = EepromChip(), I2cPullups(), I2cHeader()
    for m in (usb, cc, ldo, ldo_c, esp, esp_c, en, led, bmp, bmp_c, ee, pu, hdr):
        board.add_module(m)
    usb.usb["CC1"] += cc.cc1
    usb.usb["CC2"] += cc.cc2
    board.connect(usb.pwr, cc.pwr)
    board.connect(usb.pwr, ldo.pwr_in)
    board.connect(usb.pwr, ldo_c.pwr_5v)
    board.connect(ldo.pwr_out, ldo_c.pwr_3v3)
    for iface in (esp.pwr, esp_c.pwr, en.pwr, bmp.pwr, bmp_c.pwr, ee.pwr, pu.pwr, hdr.pwr):
        board.connect(ldo.pwr_out, iface)
    board.connect(esp.boot, en.boot)
    board.connect(esp.led_net, led.led_if)
    board.connect(esp.i2c, bmp.i2c)
    board.connect(esp.i2c, ee.i2c)
    board.connect(esp.i2c, pu.i2c)
    board.connect(esp.i2c, hdr.i2c)
    board.declare_power_rail("VBUS_5V", usb.vbus)
    board.declare_power_rail("3V3", ldo.v3v3)
    board.declare_power_rail("GND", usb.gnd)
    board.declare_rail_conversion("VBUS_5V", "3V3", efficiency=0.85)
    board.constrain_distance_min(usb, esp, min_distance_mm=8.0)
    board.constrain_distance_min(esp, bmp, min_distance_mm=6.0)
    board.declare_copper_pour_intent(usb.gnd, layer="F.Cu", purpose="ground")
    board.declare_copper_pour_intent(usb.gnd, layer="B.Cu", purpose="ground")
    return board


board = build_board()

if __name__ == "__main__":
    board.compile(project_name="sensor_hub", generate_bom=True, export_schematic=False, auto_route=False)
