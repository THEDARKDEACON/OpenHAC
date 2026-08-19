"""
complex_rs485_node.py — STM32F103 + MAX3485 RS-485 industrial node.

USB-C → AMS1117-3.3 → LQFP-48 MCU + RS-485 PHY + EEPROM + bus header.
Offline pinouts + stock KiCad footprints (fab-place friendly).
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
    C_0603,
    C_0805,
    EEPROM_24LC256,
    HEADER_1x04,
    LED_0805,
    MAX3485,
    R_0805,
    STM32F103C8,
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


class Lqfp48Core(Module):
    def __init__(self) -> None:
        super().__init__("Lqfp48Core")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.tx, self.rx = Net("UART_TX"), Net("UART_RX")
        self.de = Net("RS485_DE")
        self.sda, self.scl = Net("I2C_SDA"), Net("I2C_SCL")
        self.nrst, self.pc13 = Net("NRST"), Net("PC13")
        self.mcu = self.add(_mk("STM32F103C8T6", STM32F103C8))
        for p in ("VDD_1", "VDD_2", "VDD_3", "VDDA", "VBAT"):
            self.mcu[p] += self.v3v3
        for p in ("VSS_1", "VSS_2", "VSS_3", "VSSA"):
            self.mcu[p] += self.gnd
        self.mcu["NRST"] += self.nrst
        self.mcu["BOOT0"] += self.gnd
        self.mcu["PA9"] += self.tx
        self.mcu["PA10"] += self.rx
        self.mcu["PA8"] += self.de
        self.mcu["PB6"] += self.scl
        self.mcu["PB7"] += self.sda
        self.mcu["PC13"] += self.pc13
        self.mcu.nc_unused_pins()
        self.pwr = self.declare_interface("pwr", self.v3v3, self.gnd)
        self.uart = self.declare_interface("uart", self.tx, self.rx, self.gnd)
        self.de_if = self.declare_interface("de", self.de, self.gnd)
        self.i2c = self.declare_interface("i2c", self.sda, self.scl, self.gnd)
        self.reset = self.declare_interface("reset", self.nrst, self.gnd)
        self.led = self.declare_interface("led", self.pc13, self.gnd)


class McuLocalCaps(Module):
    def __init__(self) -> None:
        super().__init__("McuLocalCaps")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.c_bulk = self.add(_mk("C_MCU_10U", C_0805("C_MCU_10U", "10uF")))
        self.c_dec1 = self.add(_mk("C_MCU_100N_A", C_0603("C_MCU_100N_A", "100nF")))
        self.c_dec2 = self.add(_mk("C_MCU_100N_B", C_0603("C_MCU_100N_B", "100nF")))
        self.c_bulk[1] += self.v3v3
        self.c_bulk[2] += self.gnd
        self.c_dec1[1] += self.v3v3
        self.c_dec1[2] += self.gnd
        self.c_dec2[1] += self.v3v3
        self.c_dec2[2] += self.gnd
        self.pwr = self.declare_interface("pwr", self.v3v3, self.gnd)


class ResetLedStraps(Module):
    def __init__(self) -> None:
        super().__init__("ResetLedStraps")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.nrst, self.pc13 = Net("NRST"), Net("PC13")
        self.r_nrst = self.add(_mk("R_NRST_10K", R_0805("R_NRST_10K", "10k")))
        self.r_led = self.add(_mk("R_LED_1K", R_0805("R_LED_1K", "1k")))
        self.led = self.add(_mk("LED_STATUS", LED_0805("LED_STATUS")))
        self.r_nrst[1] += self.v3v3
        self.r_nrst[2] += self.nrst
        self.r_led[1] += self.pc13
        self.r_led[2] += self.led["A"]
        self.led["K"] += self.gnd
        self.pwr = self.declare_interface("pwr", self.v3v3, self.gnd)
        self.reset = self.declare_interface("reset", self.nrst, self.gnd)
        self.led_if = self.declare_interface("led", self.pc13, self.gnd)


class Rs485Phy(Module):
    def __init__(self) -> None:
        super().__init__("Rs485Phy")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.tx, self.rx, self.de = Net("UART_TX"), Net("UART_RX"), Net("RS485_DE")
        self.a, self.b = Net("RS485_A"), Net("RS485_B")
        self.phy = self.add(_mk("MAX3485", MAX3485))
        self.phy["VCC"] += self.v3v3
        self.phy["GND"] += self.gnd
        self.phy["DI"] += self.tx
        self.phy["RO"] += self.rx
        self.phy["DE"] += self.de
        self.phy["RE"] += self.de
        self.phy["A"] += self.a
        self.phy["B"] += self.b
        self.pwr = self.declare_interface("pwr", self.v3v3, self.gnd)
        self.uart = self.declare_interface("uart", self.tx, self.rx, self.gnd)
        self.de_if = self.declare_interface("de", self.de, self.gnd)


class Rs485Passives(Module):
    def __init__(self) -> None:
        super().__init__("Rs485Passives")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.a, self.b = Net("RS485_A"), Net("RS485_B")
        self.c = self.add(_mk("C_RS485_100N", C_0603("C_RS485_100N", "100nF")))
        self.rt = self.add(_mk("R_TERM_120", R_0805("R_TERM_120", "120")))
        self.c[1] += self.v3v3
        self.c[2] += self.gnd
        self.rt[1] += self.a
        self.rt[2] += self.b
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


class EepromPullups(Module):
    def __init__(self) -> None:
        super().__init__("EepromPullups")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.sda, self.scl = Net("I2C_SDA"), Net("I2C_SCL")
        self.c = self.add(_mk("C_EE_100N", C_0603("C_EE_100N", "100nF")))
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


class BusHeader(Module):
    def __init__(self) -> None:
        super().__init__("BusHeader")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.a, self.b = Net("RS485_A"), Net("RS485_B")
        self.hdr = self.add(_mk("HDR_RS485", HEADER_1x04))
        self.hdr[1] += self.v3v3
        self.hdr[2] += self.gnd
        self.hdr[3] += self.a
        self.hdr[4] += self.b
        self.pwr = self.declare_interface("pwr", self.v3v3, self.gnd)


def build_board() -> Board:
    board = Board(
        size_mm=None,
        layers=2,
        compile_goal="fabrication",
        declared_supply_voltages_v={"VBUS_5V": 5.0, "3V3": 3.3},
    )
    usb, cc = UsbJack(), UsbCcStraps()
    ldo, ldo_c = LdoChip(), LdoCaps()
    mcu, mcu_c = Lqfp48Core(), McuLocalCaps()
    straps = ResetLedStraps()
    phy, phy_p = Rs485Phy(), Rs485Passives()
    ee, ee_pu, hdr = EepromChip(), EepromPullups(), BusHeader()
    for m in (usb, cc, ldo, ldo_c, mcu, mcu_c, straps, phy, phy_p, ee, ee_pu, hdr):
        board.add_module(m)
    usb.usb["CC1"] += cc.cc1
    usb.usb["CC2"] += cc.cc2
    board.connect(usb.pwr, cc.pwr)
    board.connect(usb.pwr, ldo.pwr_in)
    board.connect(usb.pwr, ldo_c.pwr_5v)
    board.connect(ldo.pwr_out, ldo_c.pwr_3v3)
    for iface in (mcu.pwr, mcu_c.pwr, straps.pwr, phy.pwr, phy_p.pwr, ee.pwr, ee_pu.pwr, hdr.pwr):
        board.connect(ldo.pwr_out, iface)
    board.connect(mcu.uart, phy.uart)
    board.connect(mcu.de_if, phy.de_if)
    board.connect(mcu.i2c, ee.i2c)
    board.connect(mcu.i2c, ee_pu.i2c)
    board.connect(mcu.reset, straps.reset)
    board.connect(mcu.led, straps.led_if)
    board.declare_power_rail("VBUS_5V", usb.vbus)
    board.declare_power_rail("3V3", ldo.v3v3)
    board.declare_power_rail("GND", usb.gnd)
    board.declare_rail_conversion("VBUS_5V", "3V3", efficiency=0.85)
    board.constrain_distance_min(usb, mcu, min_distance_mm=8.0)
    board.constrain_distance_min(mcu, phy, min_distance_mm=8.0)
    board.declare_copper_pour_intent(usb.gnd, layer="F.Cu", purpose="ground")
    board.declare_copper_pour_intent(usb.gnd, layer="B.Cu", purpose="ground")
    return board


board = build_board()

if __name__ == "__main__":
    board.compile(project_name="rs485_node", generate_bom=True, export_schematic=False, auto_route=False)
