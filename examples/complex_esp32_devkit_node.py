"""
complex_esp32_devkit_node.py — Espressif ESP32-DevKitC–inspired multi-IC board.

Inspired by public ESP32-DevKitC / similar maker boards:
  USB-C → 5 V → AMS1117-3.3 → ESP32-WROOM-32 + I2C EEPROM + headers.

Modules are split so Z3/placement can space large footprints (WROOM, USB-C)
without packing every passive into the same bbox.

Offline explicit pinouts + stock KiCad footprints (FAB-001/002/003 friendly).

  OPENHAC_NO_NETWORK=1 openhac compile examples/complex_esp32_devkit_node.py \\
    --name esp32_devkit --production --compile-goal fabrication \\
    --no-schematic --no-route --bbox-padding-mm 1.0 -o build/esp32
"""

from __future__ import annotations

import sys
from pathlib import Path

_EX = Path(__file__).resolve().parent
if str(_EX) not in sys.path:
    sys.path.insert(0, str(_EX))

import openhac.core  # noqa: F401
from openhac.core import Board
from openhac.core.base import Component, Module
from openhac.core.net import Net

from _offline_parts import (
    AMS1117_33,
    C_0603,
    C_0805,
    EEPROM_24LC256,
    ESP32_WROOM32,
    HEADER_1x04,
    LED_0805,
    R_0805,
    USB_C_HRO,
)


def _mk(name: str, data: dict) -> Component:
    c = Component(name, comp_data=dict(data))
    part = getattr(c, "part", None)
    if part is not None and data.get("kicad_footprint"):
        part.footprint = data["kicad_footprint"]
        fields = getattr(part, "fields", None)
        if isinstance(fields, dict):
            fields["Footprint"] = data["kicad_footprint"]
            fields["Value"] = name
    return c


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
        # CC lines are local to USB jack nets — recreate named nets used on jack
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
        self.cc = self.declare_interface("cc", self.cc1, self.cc2, self.gnd)


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


class Esp32Module(Module):
    """ESP32-WROOM alone (large RF module footprint)."""

    def __init__(self) -> None:
        super().__init__("Esp32Module")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.en, self.io0 = Net("EN"), Net("IO0")
        self.tx, self.rx = Net("UART0_TX"), Net("UART0_RX")
        self.sda, self.scl = Net("I2C_SDA"), Net("I2C_SCL")
        self.io2 = Net("IO2")

        self.mcu = self.add(_mk("ESP32_WROOM_32", ESP32_WROOM32))

        self.mcu["VDD"] += self.v3v3
        for n in (1, 15, 38, 39):
            self.mcu[n] += self.gnd
        self.mcu["EN"] += self.en
        self.mcu["IO0"] += self.io0
        self.mcu["TXD0_IO1"] += self.tx
        self.mcu["RXD0_IO3"] += self.rx
        self.mcu["IO21"] += self.sda
        self.mcu["IO22"] += self.scl
        self.mcu["IO2"] += self.io2
        self.mcu.nc_unused_pins()

        self.pwr = self.declare_interface("pwr", self.v3v3, self.gnd)
        self.i2c = self.declare_interface("i2c", self.sda, self.scl, self.gnd)
        self.uart = self.declare_interface("uart", self.tx, self.rx, self.gnd)
        self.boot = self.declare_interface("boot", self.en, self.io0, self.gnd)
        self.led_net = self.declare_interface("led", self.io2, self.gnd)


class Esp32LocalCaps(Module):
    def __init__(self) -> None:
        super().__init__("Esp32LocalCaps")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.c_bulk = self.add(_mk("C_MCU_10U", C_0805("C_MCU_10U", "10uF")))
        self.c_dec = self.add(_mk("C_MCU_100N", C_0603("C_MCU_100N", "100nF")))
        self.c_bulk[1] += self.v3v3
        self.c_bulk[2] += self.gnd
        self.c_dec[1] += self.v3v3
        self.c_dec[2] += self.gnd
        self.pwr = self.declare_interface("pwr", self.v3v3, self.gnd)


class BootStraps(Module):
    def __init__(self) -> None:
        super().__init__("BootStraps")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.en, self.io0 = Net("EN"), Net("IO0")
        self.r_en = self.add(_mk("R_EN_10K", R_0805("R_EN_10K", "10k")))
        self.r_io0 = self.add(_mk("R_IO0_10K", R_0805("R_IO0_10K", "10k")))
        self.r_en[1] += self.v3v3
        self.r_en[2] += self.en
        self.r_io0[1] += self.v3v3
        self.r_io0[2] += self.io0
        self.pwr = self.declare_interface("pwr", self.v3v3, self.gnd)
        self.boot = self.declare_interface("boot", self.en, self.io0, self.gnd)


class StatusLed(Module):
    def __init__(self) -> None:
        super().__init__("StatusLed")
        self.gnd = Net("GND")
        self.io2 = Net("IO2")
        self.r = self.add(_mk("R_LED_1K", R_0805("R_LED_1K", "1k")))
        self.led = self.add(_mk("LED_STATUS", LED_0805("LED_STATUS")))
        self.r[1] += self.io2
        self.r[2] += self.led["A"]
        self.led["K"] += self.gnd
        self.led_if = self.declare_interface("led", self.io2, self.gnd)


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


class UartHeader(Module):
    def __init__(self) -> None:
        super().__init__("UartHeader")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.tx, self.rx = Net("UART0_TX"), Net("UART0_RX")
        self.hdr = self.add(_mk("HDR_UART", HEADER_1x04))
        self.hdr[1] += self.v3v3
        self.hdr[2] += self.gnd
        self.hdr[3] += self.tx
        self.hdr[4] += self.rx
        self.pwr = self.declare_interface("pwr", self.v3v3, self.gnd)
        self.uart = self.declare_interface("uart", self.tx, self.rx, self.gnd)


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
    # Leave outline unspecified so compile autosizes from footprint pack
    # (multi-IC + USB-C + WROOM needs ~200+ mm; a fixed DevKit outline is too small).
    board = Board(
        size_mm=None,
        layers=2,
        compile_goal="fabrication",
        declared_supply_voltages_v={"VBUS_5V": 5.0, "3V3": 3.3},
    )

    usb = UsbJack()
    cc = UsbCcStraps()
    ldo = LdoChip()
    ldo_c = LdoCaps()
    esp = Esp32Module()
    esp_c = Esp32LocalCaps()
    boot = BootStraps()
    led = StatusLed()
    ee = EepromChip()
    ee_pu = EepromPullups()
    uart_h = UartHeader()
    i2c_h = I2cHeader()

    mods = [usb, cc, ldo, ldo_c, esp, esp_c, boot, led, ee, ee_pu, uart_h, i2c_h]
    for m in mods:
        board.add_module(m)

    # Wire USB CC pins onto strap nets (same Net names merge via connect on power only —
    # attach CC pads here by sharing Net objects created above).
    usb.usb["CC1"] += cc.cc1
    usb.usb["CC2"] += cc.cc2

    board.connect(usb.pwr, cc.pwr)
    board.connect(usb.pwr, ldo.pwr_in)
    board.connect(usb.pwr, ldo_c.pwr_5v)
    board.connect(ldo.pwr_out, ldo_c.pwr_3v3)
    board.connect(ldo.pwr_out, esp.pwr)
    board.connect(ldo.pwr_out, esp_c.pwr)
    board.connect(ldo.pwr_out, boot.pwr)
    board.connect(ldo.pwr_out, ee.pwr)
    board.connect(ldo.pwr_out, ee_pu.pwr)
    board.connect(ldo.pwr_out, uart_h.pwr)
    board.connect(ldo.pwr_out, i2c_h.pwr)
    board.connect(esp.boot, boot.boot)
    board.connect(esp.led_net, led.led_if)
    board.connect(esp.i2c, ee.i2c)
    board.connect(esp.i2c, ee_pu.i2c)
    board.connect(esp.i2c, i2c_h.i2c)
    board.connect(esp.uart, uart_h.uart)

    board.declare_power_rail("VBUS_5V", usb.vbus)
    board.declare_power_rail("3V3", ldo.v3v3)
    board.declare_power_rail("GND", usb.gnd)
    board.declare_rail_conversion("VBUS_5V", "3V3", efficiency=0.85)

    # Soft placement hints only — hard edge+distance stacks fight autosize packing.
    board.constrain_distance_min(usb, esp, min_distance_mm=8.0)
    board.constrain_distance_min(esp, ee, min_distance_mm=6.0)

    board.declare_copper_pour_intent(usb.gnd, layer="F.Cu", purpose="ground")
    board.declare_copper_pour_intent(usb.gnd, layer="B.Cu", purpose="ground")
    # Skip fixed mounting-hole footprints: absolute coords collide under autosize.

    return board


board = build_board()


if __name__ == "__main__":
    board.compile(project_name="esp32_devkit", generate_bom=True, export_schematic=False, auto_route=False)
