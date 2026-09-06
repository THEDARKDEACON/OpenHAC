#!/usr/bin/env python3
"""
complex_grid_edge_rtu.py — C&I / microgrid field RTU (workflow-gates stress board)

A single DIN-rail brick you would actually put next to a feeder or battery
inverter: dual-MCU, isolated analog, industrial buses, optional radios.

Inspired by real open / industrial classes (not a clone of any one product):

  • OpenEnergyMonitor emonTx — CT / shunt analog front-end
  • OpenPLC / UniPi — RS-485 + digital I/O
  • Victron-style GX / IEC RTU lite — CAN + logging + optional radio
  • FigCNC / superGateway — opto DIs + dual-MCU split

Architecture
------------
  24 V DIN + USB-C debug → 5 V / 3.3 V LDOs (stand-in bucks)
  ESP32-S3  — MQTT/Wi-Fi edge, OLED, SPI flash, optional LoRa + nRF24 + microSD
  STM32F103 — hard realtime: CAN + RS-485 + opto DIs + analog IRQ
  Analog island (SPICE): AD620 shunt amp + 1N4007 + PC817 (bundled Apache physics)
  I2C fabric: PCA9548A mux, ADS1115, MCP4725, DS3231, BMP280, MPU6050, EEPROM
  USB-UART CH340C, TXS0108E 5 V field DAC, 74HC595 + 2N7002 DO

Workflow gates exercised
------------------------
  PWR-010  declare_rail + draws_from
  VAR-001  variant ``field`` (full) vs ``lite`` (LoRa / nRF / microSD DNP)
  TST-001  testpoints on VIN / 5V / 3V3 / GND / analog mid
  SPS-043  spice island = AnalogFrontEnd only (MCUs omitted)
  PLC-001  keep_together / cluster_with
  ECO/LOCK compile with ``compile_profile=logic`` writes eco + lockable BOM

Catalog-backed: every ``Component("GENERIC")`` is a SQLite row. IC pin *names*
come from vendor parse (Digi-Key-shaped named pinout). Passives come from
jlcsearch rows packed by ``_component_row_from_jlc_item`` (CAT-004 two-terminal
policy). This file does **not** import the offline pin encyclopedia.

Compile is one command. Parts next to this script are loaded first::

    openhac compile examples/complex_grid_edge_rtu.py -o /tmp/rtu

Do **not** pass ``--auto-enrich-board`` unless you want optional 3D attach.
That flag must not replace the packed KiCad USB-C footprint.

``complex_grid_edge_rtu.openhac.json`` points at recorded vendor JSON
(``tests/fixtures/vendor``). No ``--pre-seed-file``, no ``openhac sync``,
no ``--auto-enrich-board`` for this board. ``--production`` stays offline.
"""

from __future__ import annotations

import os

import openhac.core  # noqa: F401
from openhac.core import Board
from openhac.core.base import Component, Module
from openhac.core.net import Net
from openhac.database.sync_jlc import _format_capacitance, _format_resistance

VARIANTS = ("field", "lite")


def _ohms(text: str) -> float:
    s = text.strip().lower().replace("ohm", "").replace("ω", "").replace(" ", "")
    if s.endswith("k"):
        return float(s[:-1]) * 1000.0
    if s.endswith("m"):
        return float(s[:-1]) * 1e6
    if s.endswith("r"):
        return float(s[:-1])
    return float(s)


def _farads(text: str) -> float:
    sl = text.strip().replace(" ", "").lower()
    if sl.endswith("uf"):
        return float(sl[:-2]) / 1e6
    if sl.endswith("nf"):
        return float(sl[:-2]) / 1e9
    if sl.endswith("pf"):
        return float(sl[:-2]) / 1e12
    if sl.endswith("f"):
        return float(sl[:-1])
    raise ValueError(f"unparsed capacitance {text!r}")


def _r(mod: Module, ohms: str, a, b):
    gn = f"R_{_format_resistance(_ohms(ohms))}_0805"
    c = mod.add(Component(gn))
    c["1"] += a
    c["2"] += b
    return c


def _c(mod: Module, val: str, a, b, *, pkg: str = "0805"):
    gn = f"C_{_format_capacitance(_farads(val))}_{pkg}"
    c = mod.add(Component(gn))
    c["1"] += a
    c["2"] += b
    return c


def _ic(mod: Module, generic_name: str):
    return mod.add(Component(generic_name))


# ---------------------------------------------------------------------------
# Power
# ---------------------------------------------------------------------------


class UsbJack(Module):
    def __init__(self) -> None:
        super().__init__("UsbJack", schematic_sheet="POWER")
        self.vbus, self.gnd = Net("VBUS_5V"), Net("GND")
        self.usb = _ic(self, "USB_C_HRO_TYPE_C_31_M_12")
        for p in ("A4", "A9", "B4", "B9"):
            self.usb[p] += self.vbus
        for p in ("A1", "A12", "B1", "B12"):
            self.usb[p] += self.gnd
        self.usb["S1"] += self.gnd
        self.pwr = self.declare_interface("pwr_5v", self.vbus, self.gnd)
        self.draws_from("VBUS_5V", ma=50)


class UsbCcStraps(Module):
    def __init__(self) -> None:
        super().__init__("UsbCcStraps", schematic_sheet="POWER")
        self.vbus, self.gnd = Net("VBUS_5V"), Net("GND")
        self.cc1, self.cc2 = Net("USB_CC1"), Net("USB_CC2")
        _r(self, "5.1k", self.cc1, self.gnd)
        _r(self, "5.1k", self.cc2, self.gnd)
        _c(self, "10uF", self.vbus, self.gnd)
        self.pwr = self.declare_interface("pwr_5v", self.vbus, self.gnd)


class Din24VIn(Module):
    def __init__(self) -> None:
        super().__init__("Din24VIn", schematic_sheet="POWER")
        self.v24, self.gnd = Net("VIN_24V"), Net("GND")
        self.sense = Net("VIN_24V_SENSE")
        self.hdr = _ic(self, "HDR_1x04")
        self.fuse = _ic(self, "FUSE_0805")
        self.hdr["P1"] += self.v24
        self.hdr["P2"] += self.gnd
        self.hdr["P3"] += self.gnd
        self.hdr["P4"] += self.gnd
        self.fuse["1"] += self.v24
        self.fuse["2"] += self.v24
        _r(self, "100k", self.v24, self.sense)
        _r(self, "10k", self.sense, self.gnd)
        _c(self, "100uF", self.v24, self.gnd)
        self.pwr = self.declare_interface("pwr_24v", self.v24, self.gnd)
        self.draws_from("VIN_24V", ma=80)


class Ldo5VFrom24(Module):
    """SOT-223 stand-in for a 24→5 V buck (same family as the mesh gateway)."""

    def __init__(self) -> None:
        super().__init__("Ldo5VFrom24", schematic_sheet="POWER")
        self.vin, self.v5, self.gnd = Net("VIN_24V"), Net("VBUS_5V"), Net("GND")
        self.reg = _ic(self, "AMS1117_3V3")
        self.reg["VIN"] += self.vin
        self.reg["GND"] += self.gnd
        self.reg["VOUT"] += self.v5
        _c(self, "10uF", self.vin, self.gnd)
        _c(self, "22uF", self.v5, self.gnd)
        self.pwr_in = self.declare_interface("pwr_24v", self.vin, self.gnd)
        self.pwr_out = self.declare_interface("pwr_5v", self.v5, self.gnd)


class Ldo3V3(Module):
    def __init__(self) -> None:
        super().__init__("Ldo3V3", schematic_sheet="POWER")
        self.vin, self.v3v3, self.gnd = Net("VBUS_5V"), Net("3V3"), Net("GND")
        self.ldo = _ic(self, "AMS1117_3V3")
        self.ldo["VIN"] += self.vin
        self.ldo["GND"] += self.gnd
        self.ldo["VOUT"] += self.v3v3
        _c(self, "10uF", self.vin, self.gnd)
        _c(self, "100nF", self.v3v3, self.gnd, pkg="0603")
        _c(self, "10uF", self.v3v3, self.gnd)
        self.pwr_in = self.declare_interface("pwr_5v", self.vin, self.gnd)
        self.pwr_out = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)


# ---------------------------------------------------------------------------
# Compute
# ---------------------------------------------------------------------------


class Esp32S3Module(Module):
    def __init__(self) -> None:
        super().__init__("Esp32S3Module", schematic_sheet="MCU")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.en = Net("ESP_EN")
        self.uart_tx, self.uart_rx = Net("MCU_BRIDGE_TX"), Net("MCU_BRIDGE_RX")
        self.usb_tx, self.usb_rx = Net("USB_UART_TX"), Net("USB_UART_RX")
        self.i2c_sda, self.i2c_scl = Net("I2C_SDA"), Net("I2C_SCL")
        self.spi_mosi, self.spi_miso, self.spi_sck = Net("SPI_MOSI"), Net("SPI_MISO"), Net("SPI_SCK")
        self.lora_cs, self.nrf_cs, self.flash_cs = Net("LORA_CS"), Net("NRF_CS"), Net("FLASH_CS")
        self.sd_cs = Net("SD_CS")
        self.lora_dio0 = Net("LORA_DIO0")
        self.m = _ic(self, "ESP32_S3_WROOM_1")
        self.m["3V3"] += self.v3v3
        self.m["GND"] += self.gnd
        self.m["GND_P40"] += self.gnd
        self.m["EPAD"] += self.gnd
        self.m["EN"] += self.en
        self.m["TXD0"] += self.uart_tx
        self.m["RXD0"] += self.uart_rx
        self.m["IO47"] += self.usb_tx
        self.m["IO48"] += self.usb_rx
        self.m["IO15"] += self.i2c_sda
        self.m["IO16"] += self.i2c_scl
        self.m["IO18"] += self.spi_mosi
        self.m["IO19"] += self.spi_miso
        self.m["IO8"] += self.spi_sck
        self.m["IO17"] += self.lora_cs
        self.m["IO20"] += self.nrf_cs
        self.m["IO9"] += self.flash_cs
        self.m["IO10"] += self.sd_cs
        self.m["IO4"] += self.lora_dio0
        self.m.nc_unused_pins()
        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)
        self.draws_from("3V3", ma=240)


class EspLocalCaps(Module):
    def __init__(self) -> None:
        super().__init__("EspLocalCaps", schematic_sheet="MCU")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.en = Net("ESP_EN")
        _c(self, "100nF", self.v3v3, self.gnd, pkg="0603")
        _c(self, "10uF", self.v3v3, self.gnd)
        _r(self, "10k", self.v3v3, self.en)
        _r(self, "10k", self.v3v3, Net("LORA_CS"))
        _r(self, "10k", self.v3v3, Net("NRF_CS"))
        _r(self, "10k", self.v3v3, Net("SD_CS"))
        _r(self, "10k", self.v3v3, Net("FLASH_CS"))
        _r(self, "10k", Net("LORA_DIO0"), self.gnd)
        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)


class Lqfp48Core(Module):
    def __init__(self) -> None:
        super().__init__("Lqfp48Core", schematic_sheet="MCU")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.nrst = Net("STM_NRST")
        self.uart_tx, self.uart_rx = Net("MCU_BRIDGE_RX"), Net("MCU_BRIDGE_TX")
        self.can_tx, self.can_rx = Net("CAN_TX"), Net("CAN_RX")
        self.rs485_di, self.rs485_ro, self.rs485_de = Net("RS485_DI"), Net("RS485_RO"), Net("RS485_DE")
        self.i2c_sda, self.i2c_scl = Net("I2C_SDA"), Net("I2C_SCL")
        self.di0, self.di1 = Net("OPTO_DI0"), Net("OPTO_DI1")
        self.xtal_in, self.xtal_out = Net("OSC_IN"), Net("OSC_OUT")
        self.ina_rdy = Net("INA_RDY")
        self.do_clk, self.do_dat, self.do_lat = Net("DO_SRCLK"), Net("DO_SER"), Net("DO_RCLK")
        self.m = _ic(self, "STM32F103C8T6")
        for p in ("VBAT", "VDDA", "VDD_1", "VDD_2", "VDD_3"):
            self.m[p] += self.v3v3
        for p in ("VSSA", "VSS_1", "VSS_2", "VSS_3"):
            self.m[p] += self.gnd
        self.m["NRST"] += self.nrst
        self.m["PA9"] += self.uart_tx
        self.m["PA10"] += self.uart_rx
        self.m["PB6"] += self.i2c_scl
        self.m["PB7"] += self.i2c_sda
        self.m["PB10"] += self.can_rx
        self.m["PB11"] += self.can_tx
        self.m["PB13"] += self.rs485_di
        self.m["PB14"] += self.rs485_ro
        self.m["PB15"] += self.rs485_de
        self.m["PB0"] += self.di0
        self.m["PB1"] += self.di1
        self.m["PD0"] += self.xtal_in
        self.m["PD1"] += self.xtal_out
        self.m["PA0"] += self.ina_rdy
        self.m["PB3"] += self.do_clk
        self.m["PA15"] += self.do_dat
        self.m["PA14"] += self.do_lat
        self.m.nc_unused_pins()
        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)
        self.draws_from("3V3", ma=80)


class Stm32LocalCaps(Module):
    def __init__(self) -> None:
        super().__init__("Stm32LocalCaps", schematic_sheet="MCU")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.nrst = Net("STM_NRST")
        xin, xout = Net("OSC_IN"), Net("OSC_OUT")
        _c(self, "100nF", self.v3v3, self.gnd, pkg="0603")
        _c(self, "100nF", self.v3v3, self.gnd, pkg="0603")
        _c(self, "4.7uF", self.v3v3, self.gnd)
        _c(self, "10uF", self.v3v3, self.gnd)
        _c(self, "18pF", xin, self.gnd, pkg="0603")
        _c(self, "18pF", xout, self.gnd, pkg="0603")
        _r(self, "10k", self.v3v3, self.nrst)
        self.xtal = _ic(self, "XTAL_8MHZ")
        self.xtal["X1"] += xin
        self.xtal["X2"] += xout
        self.xtal["GND"] += self.gnd
        self.xtal["GND2"] += self.gnd
        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)


class UsbUart(Module):
    def __init__(self) -> None:
        super().__init__("UsbUart", schematic_sheet="MCU")
        self.v5, self.gnd = Net("VBUS_5V"), Net("GND")
        self.v3v3 = Net("3V3")
        self.tx, self.rx = Net("USB_UART_RX"), Net("USB_UART_TX")
        self.dp, self.dm = Net("USB_DP"), Net("USB_DM")
        self.u = _ic(self, "CH340C")
        self.u["VCC"] += self.v5
        self.u["GND"] += self.gnd
        self.u["TXD"] += self.tx
        self.u["RXD"] += self.rx
        self.u["UDP"] += self.dp
        self.u["UDM"] += self.dm
        self.u.nc_unused_pins()
        _c(self, "100nF", self.v5, self.gnd, pkg="0603")
        self.pwr = self.declare_interface("pwr_5v", self.v5, self.gnd)
        self.draws_from("VBUS_5V", ma=40)


# ---------------------------------------------------------------------------
# Analog island (SPICE)
# ---------------------------------------------------------------------------


class AnalogFrontEnd(Module):
    """Shunt / CT front-end. Bundled Apache AD620 + 1N4007 + PC817 — not vendor .lib."""

    def __init__(self) -> None:
        super().__init__("AnalogFrontEnd", schematic_sheet="ANALOG")
        self.v5, self.gnd = Net("VBUS_5V"), Net("GND")
        self.v3v3 = Net("3V3")
        self.shunt_p, self.shunt_n = Net("SHUNT_P"), Net("SHUNT_N")
        self.ina_out = Net("INA_OUT")
        self.ina_rdy = Net("INA_RDY")
        self.rg = Net("INA_RG")
        self.u = _ic(self, "AD620")
        self.d = _ic(self, "D_1N4007")
        self.opto = _ic(self, "OPTO_PC817")
        self.u["VSP"] += self.v5
        self.u["VSM"] += self.gnd
        self.u["INP"] += self.shunt_p
        self.u["INN"] += self.shunt_n
        self.u["OUT"] += self.ina_out
        self.u["REF"] += self.gnd
        self.u["RG1"] += self.rg
        self.u["RG2"] += self.rg
        _r(self, "49", self.rg, self.gnd)
        _r(self, "1", self.shunt_p, self.shunt_n)
        _c(self, "100nF", self.v5, self.gnd, pkg="0603")
        self.d["A"] += self.v5
        self.d["K"] += self.gnd
        _r(self, "1k", self.ina_out, self.opto["A"])
        self.opto["K"] += self.gnd
        self.opto["E"] += self.gnd
        self.opto["C"] += self.ina_rdy
        _r(self, "10k", self.v3v3, self.ina_rdy)
        self.j = _ic(self, "HDR_1x04")
        self.j["P1"] += self.shunt_p
        self.j["P2"] += self.shunt_n
        self.j["P3"] += self.gnd
        self.j["P4"] += self.gnd
        self.pwr5 = self.declare_interface("pwr_5v", self.v5, self.gnd)
        self.pwr3 = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)
        self.draws_from("VBUS_5V", ma=15)
        self.draws_from("3V3", ma=5)


# ---------------------------------------------------------------------------
# Field buses / I/O
# ---------------------------------------------------------------------------


class CanPhy(Module):
    def __init__(self) -> None:
        super().__init__("CanPhy", schematic_sheet="FIELD")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.tx, self.rx = Net("CAN_TX"), Net("CAN_RX")
        self.canh, self.canl = Net("CAN_H"), Net("CAN_L")
        self.phy = _ic(self, "CAN_TJA1051T")
        self.phy["VCC"] += self.v3v3
        self.phy["VIO"] += self.v3v3
        self.phy["GND"] += self.gnd
        self.phy["TXD"] += self.tx
        self.phy["RXD"] += self.rx
        self.phy["CANH"] += self.canh
        self.phy["CANL"] += self.canl
        self.phy["S"] += self.gnd
        _r(self, "120", self.canh, self.canl)
        self.h = _ic(self, "HDR_1x04")
        self.h["P1"] += self.canh
        self.h["P2"] += self.canl
        self.h["P3"] += self.gnd
        self.h["P4"] += self.gnd
        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)
        self.draws_from("3V3", ma=50)


class Rs485Phy(Module):
    def __init__(self) -> None:
        super().__init__("Rs485Phy", schematic_sheet="FIELD")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.di, self.ro, self.de = Net("RS485_DI"), Net("RS485_RO"), Net("RS485_DE")
        self.a, self.b = Net("RS485_A"), Net("RS485_B")
        self.phy = _ic(self, "RS485_MAX3485")
        self.phy["VCC"] += self.v3v3
        self.phy["GND"] += self.gnd
        self.phy["DI"] += self.di
        self.phy["RO"] += self.ro
        self.phy["DE"] += self.de
        self.phy["RE"] += self.de
        self.phy["A"] += self.a
        self.phy["B"] += self.b
        _r(self, "120", self.a, self.b)
        self.h = _ic(self, "HDR_1x04")
        self.h["P1"] += self.a
        self.h["P2"] += self.b
        self.h["P3"] += self.gnd
        self.h["P4"] += self.v3v3
        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)
        self.draws_from("3V3", ma=30)


class OptoBank(Module):
    def __init__(self) -> None:
        super().__init__("OptoBank", schematic_sheet="FIELD")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.h = _ic(self, "HDR_1x06")
        for i, (fp, fn, dn) in enumerate(
            (
                (Net("DI0_FIELD_P"), Net("DI0_FIELD_N"), Net("OPTO_DI0")),
                (Net("DI1_FIELD_P"), Net("DI1_FIELD_N"), Net("OPTO_DI1")),
            )
        ):
            u = _ic(self, "OPTO_PC817")
            _r(self, "1k", fp, u["A"])
            u["K"] += fn
            u["E"] += self.gnd
            u["C"] += dn
            _r(self, "10k", self.v3v3, dn)
            self.h[f"P{1 + i * 2}"] += fp
            self.h[f"P{2 + i * 2}"] += fn
        self.h["P5"] += self.gnd
        self.h["P6"] += self.gnd
        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)
        self.draws_from("3V3", ma=10)


class DoShift(Module):
    """74HC595 + 2N7002 low-side for a contact / lamp DO."""

    def __init__(self) -> None:
        super().__init__("DoShift", schematic_sheet="FIELD")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.clk, self.dat, self.lat = Net("DO_SRCLK"), Net("DO_SER"), Net("DO_RCLK")
        self.do0 = Net("DO0_GATE")
        self.u = _ic(self, "74HC595")
        self.q = _ic(self, "2N7002")
        self.u["VCC"] += self.v3v3
        self.u["GND"] += self.gnd
        self.u["SRCLK"] += self.clk
        self.u["SER"] += self.dat
        self.u["RCLK"] += self.lat
        self.u["OE"] += self.gnd
        self.u["SRCLR"] += self.v3v3
        self.u["QA"] += self.do0
        self.q["G"] += self.do0
        self.q["S"] += self.gnd
        self.do_d = Net("DO0_DRAIN")
        self.q["D"] += self.do_d
        _r(self, "10k", self.do0, self.gnd)
        self.u.nc_unused_pins()
        self.h = _ic(self, "HDR_1x04")
        self.h["P1"] += self.do_d
        self.h["P2"] += self.gnd
        self.h["P3"] += self.v3v3
        self.h["P4"] += self.gnd
        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)
        self.draws_from("3V3", ma=8)


# ---------------------------------------------------------------------------
# I2C fabric / converters / storage
# ---------------------------------------------------------------------------


class I2cPullups(Module):
    def __init__(self) -> None:
        super().__init__("I2cPullups", schematic_sheet="ANALOG")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.sda, self.scl = Net("I2C_SDA"), Net("I2C_SCL")
        _r(self, "4.7k", self.v3v3, self.sda)
        _r(self, "4.7k", self.v3v3, self.scl)
        _c(self, "100nF", self.v3v3, self.gnd, pkg="0603")
        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)


class I2cMux(Module):
    def __init__(self) -> None:
        super().__init__("I2cMux", schematic_sheet="ANALOG")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.sda, self.scl = Net("I2C_SDA"), Net("I2C_SCL")
        self.sd0, self.sc0 = Net("I2C0_SDA"), Net("I2C0_SCL")
        self.u = _ic(self, "PCA9548APW")
        self.u["VCC"] += self.v3v3
        self.u["GND"] += self.gnd
        self.u["SDA"] += self.sda
        self.u["SCL"] += self.scl
        self.u["SD0"] += self.sd0
        self.u["SC0"] += self.sc0
        self.u["RESET"] += self.v3v3
        self.u["A0"] += self.gnd
        self.u["A1"] += self.gnd
        self.u["A2"] += self.gnd
        self.u.nc_unused_pins()
        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)
        self.draws_from("3V3", ma=5)


class AdcDac(Module):
    def __init__(self) -> None:
        super().__init__("AdcDac", schematic_sheet="ANALOG")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.sda, self.scl = Net("I2C_SDA"), Net("I2C_SCL")
        self.ain0 = Net("INA_OUT")
        self.dac = Net("DAC_OUT")
        self.adc = _ic(self, "ADC_ADS1115")
        self.dac_ic = _ic(self, "MCP4725")
        self.adc["VDD"] += self.v3v3
        self.adc["GND"] += self.gnd
        self.adc["SDA"] += self.sda
        self.adc["SCL"] += self.scl
        self.adc["AIN0"] += self.ain0
        self.adc["ADDR"] += self.gnd
        self.adc.nc_unused_pins()
        self.dac_ic["VDD"] += self.v3v3
        self.dac_ic["VSS"] += self.gnd
        self.dac_ic["SDA"] += self.sda
        self.dac_ic["SCL"] += self.scl
        self.dac_ic["VOUT"] += self.dac
        self.dac_ic["A0"] += self.gnd
        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)
        self.draws_from("3V3", ma=4)


class LevelShiftDac(Module):
    """3V3 DAC → 5 V field analog out via TXS0108E (one channel)."""

    def __init__(self) -> None:
        super().__init__("LevelShiftDac", schematic_sheet="ANALOG")
        self.v3v3, self.v5, self.gnd = Net("3V3"), Net("VBUS_5V"), Net("GND")
        self.a1, self.b1 = Net("DAC_OUT"), Net("DAC_OUT_5V")
        self.u = _ic(self, "TXS0108EPW")
        self.u["VCCA"] += self.v3v3
        self.u["VCCB"] += self.v5
        self.u["GND"] += self.gnd
        self.u["OE"] += self.v3v3
        self.u["A1"] += self.a1
        self.u["B1"] += self.b1
        self.u.nc_unused_pins()
        self.h = _ic(self, "HDR_1x04")
        self.h["P1"] += self.b1
        self.h["P2"] += self.gnd
        self.h["P3"] += self.v5
        self.h["P4"] += self.gnd
        self.pwr3 = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)
        self.pwr5 = self.declare_interface("pwr_5v", self.v5, self.gnd)
        self.draws_from("3V3", ma=2)
        self.draws_from("VBUS_5V", ma=2)


class RtcEepromFlash(Module):
    def __init__(self) -> None:
        super().__init__("RtcEepromFlash", schematic_sheet="MCU")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.sda, self.scl = Net("I2C_SDA"), Net("I2C_SCL")
        self.mosi, self.miso, self.sck, self.cs = (
            Net("SPI_MOSI"),
            Net("SPI_MISO"),
            Net("SPI_SCK"),
            Net("FLASH_CS"),
        )
        self.rtc = _ic(self, "DS3231M")
        self.ee = _ic(self, "EEPROM_24LC256")
        self.flash = _ic(self, "W25Q32JVSS")
        self.rtc["VCC"] += self.v3v3
        self.rtc["GND"] += self.gnd
        self.rtc["VBAT"] += self.v3v3
        self.rtc["SDA"] += self.sda
        self.rtc["SCL"] += self.scl
        self.rtc.nc_unused_pins()
        self.ee["VCC"] += self.v3v3
        self.ee["VSS"] += self.gnd
        self.ee["SDA"] += self.sda
        self.ee["SCL"] += self.scl
        for p in ("A0", "A1", "A2", "WP"):
            self.ee[p] += self.gnd
        self.flash["VCC"] += self.v3v3
        self.flash["GND"] += self.gnd
        self.flash["CS"] += self.cs
        self.flash["DI"] += self.mosi
        self.flash["DO"] += self.miso
        self.flash["CLK"] += self.sck
        self.flash["WP"] += self.v3v3
        self.flash["HOLD"] += self.v3v3
        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)
        self.draws_from("3V3", ma=20)


class MuxSensors(Module):
    def __init__(self) -> None:
        super().__init__("MuxEnv", schematic_sheet="ANALOG")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.sda, self.scl = Net("I2C0_SDA"), Net("I2C0_SCL")
        self.imu = _ic(self, "IMU_MPU6050")
        self.baro = _ic(self, "SENSOR_BMP280")
        self.imu["VDD"] += self.v3v3
        self.imu["VDDIO"] += self.v3v3
        self.imu["GND"] += self.gnd
        self.imu["SCL"] += self.scl
        self.imu["SDA"] += self.sda
        self.imu.nc_unused_pins()
        self.baro["VDD"] += self.v3v3
        self.baro["VDDIO"] += self.v3v3
        self.baro["GND"] += self.gnd
        self.baro["GND7"] += self.gnd
        self.baro["SDI"] += self.sda
        self.baro["SCK"] += self.scl
        self.baro["CSB"] += self.v3v3
        self.baro.nc_unused_pins()
        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)
        self.draws_from("3V3", ma=8)


class OledHmi(Module):
    def __init__(self) -> None:
        super().__init__("OledHmi", schematic_sheet="COMMS")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.sda, self.scl = Net("I2C_SDA"), Net("I2C_SCL")
        self.m = _ic(self, "OLED_SSD1306")
        self.m["VIN"] += self.v3v3
        self.m["GND"] += self.gnd
        self.m["SCL"] += self.scl
        self.m["SDA"] += self.sda
        self.m.nc_unused_pins()
        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)
        self.draws_from("3V3", ma=25)


# ---------------------------------------------------------------------------
# Optional radios / logging (VAR-001)
# ---------------------------------------------------------------------------


class LoRaRadio(Module):
    def __init__(self) -> None:
        super().__init__("LoRaRadio", schematic_sheet="COMMS")
        self.include_in_variants("field")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.mosi, self.miso, self.sck = Net("SPI_MOSI"), Net("SPI_MISO"), Net("SPI_SCK")
        self.cs, self.dio0 = Net("LORA_CS"), Net("LORA_DIO0")
        self.m = _ic(self, "RFM95_LORA")
        self.m["VDD"] += self.v3v3
        for p in ("GND", "GND14", "GND15", "GND16"):
            self.m[p] += self.gnd
        self.m["MOSI"] += self.mosi
        self.m["MISO"] += self.miso
        self.m["SCK"] += self.sck
        self.m["NSS"] += self.cs
        self.m["DIO0"] += self.dio0
        self.m.nc_unused_pins()
        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)
        self.draws_from("3V3", ma=120)


class NrfMesh(Module):
    def __init__(self) -> None:
        super().__init__("NrfMesh", schematic_sheet="COMMS")
        self.include_in_variants("field")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.mosi, self.miso, self.sck, self.cs = (
            Net("SPI_MOSI"),
            Net("SPI_MISO"),
            Net("SPI_SCK"),
            Net("NRF_CS"),
        )
        self.m = _ic(self, "NRF24L01")
        self.m["VCC"] += self.v3v3
        self.m["GND"] += self.gnd
        self.m["MOSI"] += self.mosi
        self.m["MISO"] += self.miso
        self.m["SCK"] += self.sck
        self.m["CSN"] += self.cs
        self.m["CE"] += self.gnd
        self.m.nc_unused_pins()
        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)
        self.draws_from("3V3", ma=15)


class MicroSdLog(Module):
    def __init__(self) -> None:
        super().__init__("MicroSdLog", schematic_sheet="COMMS")
        self.include_in_variants("field")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.mosi, self.miso, self.sck, self.cs = (
            Net("SPI_MOSI"),
            Net("SPI_MISO"),
            Net("SPI_SCK"),
            Net("SD_CS"),
        )
        self.m = _ic(self, "MICROSD_SLOT")
        self.m["VDD"] += self.v3v3
        self.m["VSS"] += self.gnd
        self.m["CMD_DI"] += self.mosi
        self.m["DAT0_DO"] += self.miso
        self.m["CLK"] += self.sck
        self.m["DAT3_CS"] += self.cs
        self.m.nc_unused_pins()
        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)
        self.draws_from("3V3", ma=40)


class StatusLeds(Module):
    def __init__(self) -> None:
        super().__init__("StatusLeds", schematic_sheet="MCU")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        for name in ("SYS", "RF", "BUS"):
            d = self.add(Component("LED_GREEN_0805"))
            r = self.add(Component("R_1k_0805"))
            n = Net(f"LED_{name}")
            r["1"] += self.v3v3
            r["2"] += n
            d["2"] += n
            d["1"] += self.gnd
        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)


class SwdHeader(Module):
    def __init__(self) -> None:
        super().__init__("SwdHeader", schematic_sheet="MCU")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.h = _ic(self, "HDR_1x04")
        self.h["P1"] += self.v3v3
        self.h["P2"] += self.gnd
        self.h["P3"] += Net("STM_NRST")
        self.h["P4"] += self.gnd


# ---------------------------------------------------------------------------
# Board
# ---------------------------------------------------------------------------


def build_board(*, variant: str = "field") -> Board:
    if variant not in VARIANTS:
        raise ValueError(f"variant must be one of {VARIANTS}, got {variant!r}")

    usb, cc = UsbJack(), UsbCcStraps()
    vin, buck, ldo = Din24VIn(), Ldo5VFrom24(), Ldo3V3()
    esp, espc = Esp32S3Module(), EspLocalCaps()
    stm, stmc = Lqfp48Core(), Stm32LocalCaps()
    uart = UsbUart()
    analog = AnalogFrontEnd()
    can, rs, opto, do = CanPhy(), Rs485Phy(), OptoBank(), DoShift()
    i2c, mux, conv, xlate = I2cPullups(), I2cMux(), AdcDac(), LevelShiftDac()
    mem, sens, oled = RtcEepromFlash(), MuxSensors(), OledHmi()
    lora, nrf, sd = LoRaRadio(), NrfMesh(), MicroSdLog()
    leds, swd = StatusLeds(), SwdHeader()

    board = Board(
        size_mm=(160.0, 100.0),
        compile_goal="handoff",
        strict=False,
        variant=variant,
        declared_supply_voltages_v={"VIN_24V": 24.0, "VBUS_5V": 5.0, "3V3": 3.3},
    )
    for m in (
        usb,
        cc,
        vin,
        buck,
        ldo,
        esp,
        espc,
        stm,
        stmc,
        uart,
        analog,
        can,
        rs,
        opto,
        do,
        i2c,
        mux,
        conv,
        xlate,
        mem,
        sens,
        oled,
        lora,
        nrf,
        sd,
        leds,
        swd,
    ):
        board.add_module(m)

    usb.usb["A5"] += cc.cc1
    usb.usb["B5"] += cc.cc2
    usb.usb["A6"] += uart.dp
    usb.usb["A7"] += uart.dm
    usb.usb.nc_unused_pins()

    board.connect(usb.pwr, cc.pwr)
    board.connect(usb.pwr, buck.pwr_out)
    board.connect(vin.pwr, buck.pwr_in)
    board.connect(usb.pwr, ldo.pwr_in)
    board.connect(usb.pwr, analog.pwr5)
    board.connect(usb.pwr, xlate.pwr5)
    board.connect(usb.pwr, uart.pwr)
    board.connect(ldo.pwr_out, analog.pwr3)
    board.connect(ldo.pwr_out, xlate.pwr3)
    for m in (
        esp,
        espc,
        stm,
        stmc,
        can,
        rs,
        opto,
        do,
        i2c,
        mux,
        conv,
        mem,
        sens,
        oled,
        lora,
        nrf,
        sd,
        leds,
    ):
        board.connect(ldo.pwr_out, m.pwr)

    board.declare_rail("VIN_24V", voltage_v=24.0, max_amp=1.0)
    board.declare_rail("VBUS_5V", voltage_v=5.0, max_amp=1.5)
    board.declare_rail("3V3", voltage_v=3.3, max_amp=0.8)
    board.declare_power_rail("VIN_24V", vin.v24)
    board.declare_power_rail("VBUS_5V", usb.vbus)
    board.declare_power_rail("3V3", ldo.v3v3)
    board.declare_power_rail("GND", usb.gnd)

    board.declare_testpoint(vin.v24)
    board.declare_testpoint(usb.vbus)
    board.declare_testpoint(ldo.v3v3)
    board.declare_testpoint(usb.gnd)
    board.declare_testpoint(analog.ina_out)

    board.declare_spice_ground("GND")
    board.declare_spice_island(analog)
    board.declare_spice_rail("VBUS_5V", 5.0)
    board.declare_spice_rail("3V3", 3.3)

    espc.cluster_with(esp)
    stmc.cluster_with(stm)
    cc.cluster_with(usb)
    board.keep_together(analog, conv)
    board.keep_together(lora, nrf)

    board.constrain_distance_min(usb, esp, min_distance_mm=8.0)
    board.constrain_distance_min(esp, stm, min_distance_mm=6.0)
    board.constrain_distance_min(lora, nrf, min_distance_mm=10.0)
    board.constrain_distance_min(can, rs, min_distance_mm=5.0)

    board.set_net_current(usb.vbus, 1.0, note="5 V local")
    board.set_net_current(ldo.v3v3, 0.7, note="3V3 digital")
    board.set_net_current(vin.v24, 0.4, note="DIN 24 V")
    board.set_net_current(usb.gnd, 1.5, note="return")

    board.declare_copper_pour_intent(usb.gnd, layer="F.Cu", purpose="ground")
    board.declare_copper_pour_intent(usb.gnd, layer="B.Cu", purpose="ground")
    return board


if __name__ == "__main__":
    from openhac.core.dnp import part_is_dnp
    from openhac.core.variant import apply_board_variant

    board = build_board(variant=os.environ.get("OPENHAC_BOARD_VARIANT", "field").strip() or "field")
    apply_board_variant(board)
    mods = board._get_all_modules()
    parts = [c for m in mods for c in getattr(m, "components", [])]
    n_dnp = sum(1 for p in parts if part_is_dnp(p) or part_is_dnp(getattr(p, "part", None)))
    print(f"grid-edge RTU variant={board.variant} parts={len(parts)} dnp={n_dnp}")
