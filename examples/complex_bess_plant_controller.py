#!/usr/bin/env python3
"""
complex_bess_plant_controller.py — Hybrid BESS / microgrid plant controller

Catalog-backed (no ``_offline_parts``). Every IC is ``Component("GENERIC")``
resolved from Digi-Key-shaped vendor cassettes next to this script via
``complex_bess_plant_controller.openhac.json`` (plus the shared grid-edge
cassette for AMS1117 / USB-C / ESP32-S3 / TJA1051 / passives).

Real-world-shaped brick: multi-rail DC, AC sensing (scaled), dual CAN,
Modbus RS-485, Ethernet, LoRa + nRF, PLC-class + power-conversion MCUs,
and a dense sensor island.

Architecture (4-layer, KiCad 10)::

  VIN_48V pack + VIN_24V DIN + USB-C → 12 V / 5 V / 3.3 V / 1.8 V
  ESP32-S3      — cloud / HMI / Ethernet / radios
  ESP32-C3      — safety watchdog
  STM32F407VE   — PLC-class plant logic (dual CAN + RS-485 + DI)
  STM32G474CE   — power-conversion MCU (PWM + ACS712 / thermocouple)
  Sensors       — BME280, SCD41, LM75, TMP117, INA219, MAX31855, ACS712,
                  AD620 shunt, ADS1115
  Field         — ISO1050 isolated BMS CAN + TJA1051 inverter CAN + RS-485

Compile (cassette ingest, no HTTP)::

    python3 -m openhac.cli compile examples/complex_bess_plant_controller.py \\
      --name bess_plant_controller --target-kicad 10 --compile-goal handoff \\
      --no-route -o /tmp/openhac_bess

Live catalog (optional):: ``openhac sync`` / network JIT — then the same
``Component("…")`` names resolve from SQLite instead of fixtures.
"""

from __future__ import annotations

from pathlib import Path

import openhac.core  # noqa: F401
from openhac.core import Board
from openhac.core.base import Component, Module
from openhac.core.net import Net
from openhac.database.sync_jlc import _format_capacitance, _format_resistance


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
# POWER
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
        self.usb["SH"] += self.gnd
        self.usb.nc_unused_pins()
        self.pwr = self.declare_interface("pwr_5v", self.vbus, self.gnd)
        self.draws_from("VBUS_5V", ma=80)


class UsbCcStraps(Module):
    def __init__(self) -> None:
        super().__init__("UsbCcStraps", schematic_sheet="POWER")
        self.vbus, self.gnd = Net("VBUS_5V"), Net("GND")
        self.cc1, self.cc2 = Net("USB_CC1"), Net("USB_CC2")
        _r(self, "5.1k", self.cc1, self.gnd)
        _r(self, "5.1k", self.cc2, self.gnd)
        _c(self, "10uF", self.vbus, self.gnd)
        self.pwr = self.declare_interface("pwr_5v", self.vbus, self.gnd)


class Batt48VIn(Module):
    def __init__(self) -> None:
        super().__init__("Batt48VIn", schematic_sheet="POWER")
        self.v48, self.gnd = Net("VIN_48V"), Net("GND")
        self.sense = Net("PACK_V_SENSE")
        self.hdr = _ic(self, "HDR_1x04")
        self.fuse = _ic(self, "FUSE_0805")
        self.hdr["P1"] += self.v48
        self.hdr["P2"] += self.gnd
        self.hdr["P3"] += self.gnd
        self.hdr["P4"] += self.gnd
        self.fuse["1"] += self.v48
        self.fuse["2"] += Net("VIN_48V_FUSED")
        _r(self, "100k", Net("VIN_48V_FUSED"), self.sense)
        _r(self, "10k", self.sense, self.gnd)
        _c(self, "100uF", Net("VIN_48V_FUSED"), self.gnd)
        self.pwr = self.declare_interface("pwr_48v", self.v48, self.gnd)


class PdnFilter48(Module):
    def __init__(self) -> None:
        super().__init__("PdnFilter48", schematic_sheet="POWER")
        self.vin, self.vout, self.gnd = Net("VIN_48V_FUSED"), Net("VIN_48V_FILT"), Net("GND")
        self.fb = _ic(self, "FERRITE_0805")
        self.l = _ic(self, "L_0805_10UH")
        self.fb["1"] += self.vin
        self.fb["2"] += Net("VIN_48V_FB")
        self.l["1"] += Net("VIN_48V_FB")
        self.l["2"] += self.vout
        _c(self, "10uF", self.vout, self.gnd)
        self.pwr_in = self.declare_interface("pwr_48v", self.vin, self.gnd)
        self.pwr_out = self.declare_interface("pwr_48v_filt", self.vout, self.gnd)


class Din24VIn(Module):
    def __init__(self) -> None:
        super().__init__("Din24VIn", schematic_sheet="POWER")
        self.v24, self.gnd = Net("VIN_24V"), Net("GND")
        self.hdr = _ic(self, "HDR_1x04")
        self.fuse = _ic(self, "FUSE_0805")
        self.hdr["P1"] += self.v24
        self.hdr["P2"] += self.gnd
        self.hdr["P3"] += self.gnd
        self.hdr["P4"] += self.gnd
        self.fuse["1"] += self.v24
        self.fuse["2"] += Net("VIN_24V_FUSED")
        _c(self, "100uF", Net("VIN_24V_FUSED"), self.gnd)
        self.pwr = self.declare_interface("pwr_24v", self.v24, self.gnd)


class Buck12From48(Module):
    """Catalog AMS1117 stand-in for a 48→12 V buck (η declared separately)."""

    def __init__(self) -> None:
        super().__init__("Buck12From48", schematic_sheet="POWER")
        self.vin, self.v12, self.gnd = Net("VIN_48V_FILT"), Net("VSYS_12V"), Net("GND")
        self.reg = _ic(self, "AMS1117_3V3")
        self.reg["VIN"] += self.vin
        self.reg["GND"] += self.gnd
        self.reg["VOUT"] += self.v12
        _c(self, "10uF", self.v12, self.gnd)
        self.pwr_in = self.declare_interface("pwr_48v_filt", self.vin, self.gnd)
        self.pwr_out = self.declare_interface("pwr_12v", self.v12, self.gnd)


class Buck5From12(Module):
    def __init__(self) -> None:
        super().__init__("Buck5From12", schematic_sheet="POWER")
        self.vin, self.v5, self.gnd = Net("VSYS_12V"), Net("VBUS_5V"), Net("GND")
        self.reg = _ic(self, "AMS1117_3V3")
        self.reg["VIN"] += self.vin
        self.reg["GND"] += self.gnd
        self.reg["VOUT"] += self.v5
        _c(self, "10uF", self.v5, self.gnd)
        self.pwr_in = self.declare_interface("pwr_12v", self.vin, self.gnd)
        self.pwr_out = self.declare_interface("pwr_5v", self.v5, self.gnd)


class Buck5From24(Module):
    def __init__(self) -> None:
        super().__init__("Buck5From24", schematic_sheet="POWER")
        self.vin, self.gnd = Net("VIN_24V_FUSED"), Net("GND")
        self.v5raw = Net("V5_FROM_24")
        self.reg = _ic(self, "AMS1117_3V3")
        self.d = _ic(self, "D_1N4007")
        self.reg["VIN"] += self.vin
        self.reg["GND"] += self.gnd
        self.reg["VOUT"] += self.v5raw
        self.d["A"] += self.v5raw
        self.d["K"] += Net("VBUS_5V")
        self.pwr_in = self.declare_interface("pwr_24v", self.vin, self.gnd)
        self.pwr_out = self.declare_interface("pwr_5v", Net("VBUS_5V"), self.gnd)


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


class Ldo1V8(Module):
    def __init__(self) -> None:
        super().__init__("Ldo1V8", schematic_sheet="POWER")
        self.vin, self.v1v8, self.gnd = Net("3V3"), Net("1V8"), Net("GND")
        self.ldo = _ic(self, "AMS1117_1V8")
        self.ldo["VIN"] += self.vin
        self.ldo["GND"] += self.gnd
        self.ldo["VOUT"] += self.v1v8
        _c(self, "100nF", self.v1v8, self.gnd, pkg="0603")
        _c(self, "10uF", self.v1v8, self.gnd)
        self.pwr_in = self.declare_interface("pwr_3v3", self.vin, self.gnd)
        self.pwr_out = self.declare_interface("pwr_1v8", self.v1v8, self.gnd)


class AgndTie(Module):
    def __init__(self) -> None:
        super().__init__("AgndTie", schematic_sheet="POWER")
        self.agnd, self.gnd = Net("AGND"), Net("GND")
        self.tie = _ic(self, "NETTIE_2")
        self.tie["1"] += self.agnd
        self.tie["2"] += self.gnd


# ---------------------------------------------------------------------------
# EDGE
# ---------------------------------------------------------------------------


class Esp32S3Edge(Module):
    def __init__(self) -> None:
        super().__init__("Esp32S3Edge", schematic_sheet="EDGE")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.en = Net("ESP_EN")
        self.m = _ic(self, "ESP32_S3_WROOM_1")
        self.m["3V3"] += self.v3v3
        self.m["GND"] += self.gnd
        self.m["EN"] += self.en
        self.m["TXD0"] += Net("MCU_BRIDGE_TX")
        self.m["RXD0"] += Net("MCU_BRIDGE_RX")
        self.m["IO15"] += Net("I2C_SDA")
        self.m["IO16"] += Net("I2C_SCL")
        self.m["IO18"] += Net("SPI_MOSI")
        self.m["IO19"] += Net("SPI_MISO")
        self.m["IO8"] += Net("SPI_SCK")
        self.m["IO17"] += Net("ETH_CS")
        self.m["IO20"] += Net("LORA_CS")
        self.m["IO9"] += Net("NRF_CS")
        self.m["IO10"] += Net("SD_CS")
        self.m["IO4"] += Net("LORA_DIO0")
        self.m.nc_unused_pins()
        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)
        self.draws_from("3V3", ma=250)


class EspLocalCaps(Module):
    def __init__(self) -> None:
        super().__init__("EspLocalCaps", schematic_sheet="EDGE")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        _c(self, "100nF", self.v3v3, self.gnd, pkg="0603")
        _c(self, "10uF", self.v3v3, self.gnd)
        _r(self, "10k", self.v3v3, Net("ESP_EN"))
        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)


class Esp32C3Watchdog(Module):
    def __init__(self) -> None:
        super().__init__("Esp32C3Watchdog", schematic_sheet="EDGE")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.m = _ic(self, "ESP32_C3_WROOM_02")
        self.m["3V3"] += self.v3v3
        self.m["GND"] += self.gnd
        self.m["EN"] += Net("C3_EN")
        self.m["IO21"] += Net("C3_UART_TX")
        self.m["IO20"] += Net("C3_UART_RX")
        self.m["IO9"] += Net("C3_HEARTBEAT")
        self.m["IO6"] += Net("ESTOP_LATCH")
        _r(self, "10k", self.v3v3, Net("ESTOP_LATCH"))
        self.m.nc_unused_pins()
        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)
        self.draws_from("3V3", ma=80)


class C3LocalCaps(Module):
    def __init__(self) -> None:
        super().__init__("C3LocalCaps", schematic_sheet="EDGE")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        _c(self, "100nF", self.v3v3, self.gnd, pkg="0603")
        _c(self, "10uF", self.v3v3, self.gnd)
        _r(self, "10k", self.v3v3, Net("C3_EN"))
        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)


class PlcCoreF407(Module):
    """STM32F407VE — PLC-class plant controller."""

    def __init__(self) -> None:
        super().__init__("PlcCoreF407", schematic_sheet="EDGE")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.m = _ic(self, "STM32F407VET6")
        for p in (11, 19, 28, 50, 75, 100, 22, 21):
            self.m[p] += self.v3v3
        for p in (10, 20, 27, 74, 99):
            self.m[p] += self.gnd
        self.m["NRST"] += Net("PLC_NRST")
        self.m["PH0"] += Net("OSC_IN")
        self.m["PH1"] += Net("OSC_OUT")
        self.m["PA9"] += Net("MCU_BRIDGE_RX")
        self.m["PA10"] += Net("MCU_BRIDGE_TX")
        self.m["PA2"] += Net("C3_UART_RX")
        self.m["PA3"] += Net("C3_UART_TX")
        self.m["PD0"] += Net("CAN_BMS_RX")
        self.m["PD1"] += Net("CAN_BMS_TX")
        self.m["PB8"] += Net("CAN_INV_RX")
        self.m["PB9"] += Net("CAN_INV_TX")
        self.m["PD5"] += Net("RS485_DI")
        self.m["PD6"] += Net("RS485_RO")
        self.m["PD7"] += Net("RS485_DE")
        self.m["PB0"] += Net("OPTO_DI0")
        self.m["PB1"] += Net("OPTO_DI1")
        self.m["PB2"] += Net("OPTO_DI2")
        self.m["PA8"] += Net("CONTACTOR_G")
        self.m["PA0"] += Net("C3_HEARTBEAT")
        self.m["PE11"] += Net("PWR_MCU_TX")
        self.m["PE12"] += Net("PWR_MCU_RX")
        self.m["VCAP_1"] += Net("VCAP1")
        self.m["VCAP_2"] += Net("VCAP2")
        self.m.nc_unused_pins()
        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)
        self.draws_from("3V3", ma=180)


class PlcLocalCaps(Module):
    def __init__(self) -> None:
        super().__init__("PlcLocalCaps", schematic_sheet="EDGE")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        for _ in range(4):
            _c(self, "100nF", self.v3v3, self.gnd, pkg="0603")
        _c(self, "10uF", self.v3v3, self.gnd)
        _r(self, "10k", self.v3v3, Net("PLC_NRST"))
        _c(self, "4.7uF", Net("VCAP1"), self.gnd)
        _c(self, "4.7uF", Net("VCAP2"), self.gnd)
        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)


class StmCrystal(Module):
    def __init__(self) -> None:
        super().__init__("StmCrystal", schematic_sheet="EDGE")
        self.gnd = Net("GND")
        self.xtal = _ic(self, "XTAL_8MHZ")
        self.xtal["X1"] += Net("OSC_IN")
        self.xtal["X2"] += Net("OSC_OUT")
        self.xtal["GND"] += self.gnd
        self.xtal["GND2"] += self.gnd
        _c(self, "18pF", Net("OSC_IN"), self.gnd, pkg="0603")
        _c(self, "18pF", Net("OSC_OUT"), self.gnd, pkg="0603")


class PowerCoreG474(Module):
    def __init__(self) -> None:
        super().__init__("PowerCoreG474", schematic_sheet="EDGE")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.m = _ic(self, "STM32G474CET6")
        for p in (24, 36, 48, 21, 20):
            self.m[p] += self.v3v3
        for p in (23, 35, 47, 19):
            self.m[p] += self.gnd
        self.m["NRST"] += Net("PWR_NRST")
        self.m["PA9"] += Net("PWR_MCU_RX")
        self.m["PA10"] += Net("PWR_MCU_TX")
        self.m["PA5"] += Net("PWR_SPI_SCK")
        self.m["PA6"] += Net("PWR_SPI_MISO")
        self.m["PA4"] += Net("TC_CS")
        self.m["PA8"] += Net("INV_PWM_A")
        self.m["PA0"] += Net("INV_PWM_B")
        self.m["PA1"] += Net("I_AC_SENSE")
        self.pwm = _ic(self, "HDR_1x04")
        self.pwm["P1"] += Net("INV_PWM_A")
        self.pwm["P2"] += Net("INV_PWM_B")
        self.pwm["P3"] += self.gnd
        self.pwm["P4"] += self.gnd
        self.m.nc_unused_pins()
        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)
        self.draws_from("3V3", ma=120)


class G474LocalCaps(Module):
    def __init__(self) -> None:
        super().__init__("G474LocalCaps", schematic_sheet="EDGE")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        for _ in range(4):
            _c(self, "100nF", self.v3v3, self.gnd, pkg="0603")
        _c(self, "10uF", self.v3v3, self.gnd)
        _r(self, "10k", self.v3v3, Net("PWR_NRST"))
        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)


# ---------------------------------------------------------------------------
# FIELD
# ---------------------------------------------------------------------------


class CanBmsIso(Module):
    def __init__(self) -> None:
        super().__init__("CanBmsIso", schematic_sheet="FIELD")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.phy = _ic(self, "ISO1050DUB")
        self.phy["VCC1"] += self.v3v3
        self.phy["GND1"] += self.gnd
        self.phy["TXD"] += Net("CAN_BMS_TX")
        self.phy["RXD"] += Net("CAN_BMS_RX")
        self.phy["VCC2"] += Net("CAN_BMS_VISO")
        self.phy["GND2"] += Net("CAN_BMS_GISO")
        self.phy["CANH"] += Net("CAN_BMS_H")
        self.phy["CANL"] += Net("CAN_BMS_L")
        _c(self, "100nF", Net("CAN_BMS_VISO"), Net("CAN_BMS_GISO"), pkg="0603")
        _r(self, "120", Net("CAN_BMS_H"), Net("CAN_BMS_L"))
        self.h = _ic(self, "HDR_1x04")
        self.h["P1"] += Net("CAN_BMS_H")
        self.h["P2"] += Net("CAN_BMS_L")
        self.h["P3"] += self.gnd
        self.h["P4"] += self.gnd
        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)


class CanInvPhy(Module):
    def __init__(self) -> None:
        super().__init__("CanInvPhy", schematic_sheet="FIELD")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.phy = _ic(self, "CAN_TJA1051T")
        self.phy["VCC"] += self.v3v3
        self.phy["GND"] += self.gnd
        self.phy["TXD"] += Net("CAN_INV_TX")
        self.phy["RXD"] += Net("CAN_INV_RX")
        self.phy["CANH"] += Net("CAN_INV_H")
        self.phy["CANL"] += Net("CAN_INV_L")
        self.phy["S"] += self.gnd
        self.phy["VIO"] += self.v3v3
        _r(self, "120", Net("CAN_INV_H"), Net("CAN_INV_L"))
        self.h = _ic(self, "HDR_1x04")
        self.h["P1"] += Net("CAN_INV_H")
        self.h["P2"] += Net("CAN_INV_L")
        self.h["P3"] += self.gnd
        self.h["P4"] += self.gnd
        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)


class Rs485Phy(Module):
    def __init__(self) -> None:
        super().__init__("Rs485Phy", schematic_sheet="FIELD")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.phy = _ic(self, "RS485_MAX3485")
        self.phy["VCC"] += self.v3v3
        self.phy["GND"] += self.gnd
        self.phy["DI"] += Net("RS485_DI")
        self.phy["RO"] += Net("RS485_RO")
        self.phy["DE"] += Net("RS485_DE")
        self.phy["RE"] += Net("RS485_DE")
        self.phy["A"] += Net("RS485_A")
        self.phy["B"] += Net("RS485_B")
        _r(self, "120", Net("RS485_A"), Net("RS485_B"))
        self.h = _ic(self, "HDR_1x04")
        self.h["P1"] += Net("RS485_A")
        self.h["P2"] += Net("RS485_B")
        self.h["P3"] += self.gnd
        self.h["P4"] += self.v3v3
        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)


class OptoBank(Module):
    def __init__(self) -> None:
        super().__init__("OptoBank", schematic_sheet="FIELD")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.h = _ic(self, "HDR_1x08")
        for i, net in enumerate(("OPTO_DI0", "OPTO_DI1", "OPTO_DI2"), start=0):
            u = _ic(self, "OPTO_PC817")
            fp, fn = Net(f"DI{i}_FIELD_P"), Net(f"DI{i}_FIELD_N")
            _r(self, "1k", fp, u["A"])
            u["K"] += fn
            u["E"] += self.gnd
            u["C"] += Net(net)
            _r(self, "10k", self.v3v3, Net(net))
            self.h[str(2 * i + 1)] += fp
            self.h[str(2 * i + 2)] += fn
        self.h["7"] += self.gnd
        self.h["8"] += self.gnd
        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)


class ContactorFet(Module):
    def __init__(self) -> None:
        super().__init__("ContactorFet", schematic_sheet="FIELD")
        self.v12, self.gnd = Net("VSYS_12V"), Net("GND")
        self.q = _ic(self, "2N7002")
        _r(self, "120", Net("CONTACTOR_G"), self.q["G"])
        self.q["S"] += self.gnd
        self.q["D"] += Net("CONT_DRAIN")
        self.h = _ic(self, "HDR_1x04")
        self.h["P1"] += self.v12
        self.h["P2"] += Net("CONT_DRAIN")
        self.h["P3"] += self.gnd
        self.h["P4"] += self.gnd
        self.pwr = self.declare_interface("pwr_12v", self.v12, self.gnd)


# ---------------------------------------------------------------------------
# ANALOG / SENSORS
# ---------------------------------------------------------------------------


class SensorIsland(Module):
    def __init__(self) -> None:
        super().__init__("SensorIsland", schematic_sheet="ANALOG")
        self.v3v3, self.agnd = Net("3V3"), Net("AGND")
        self.sda, self.scl = Net("I2C_SDA"), Net("I2C_SCL")
        _r(self, "4.7k", self.v3v3, self.sda)
        _r(self, "4.7k", self.v3v3, self.scl)

        self.adc = _ic(self, "ADC_ADS1115")
        self.adc["VDD"] += self.v3v3
        self.adc["GND"] += self.agnd
        self.adc["SDA"] += self.sda
        self.adc["SCL"] += self.scl
        self.adc["AIN0"] += Net("I_PACK_SENSE")
        self.adc["AIN1"] += Net("PACK_V_SENSE")
        self.adc["AIN2"] += Net("VAC_SENSE")
        self.adc["AIN3"] += Net("CT_SENSE")
        self.adc.nc_unused_pins()

        self.shunt = _ic(self, "AD620")
        self.shunt["VSP"] += self.v3v3
        self.shunt["VSM"] += self.agnd
        self.shunt["INP"] += Net("SHUNT_P")
        self.shunt["INN"] += Net("SHUNT_N")
        self.shunt["OUT"] += Net("I_PACK_SENSE")
        self.shunt["REF"] += self.agnd
        _r(self, "49", self.shunt["RG1"], self.shunt["RG2"])

        self.bme = _ic(self, "SENSOR_BME280")
        self.bme["VDD"] += self.v3v3
        self.bme["VDDIO"] += self.v3v3
        self.bme["GND"] += self.agnd
        self.bme["SDI"] += self.sda
        self.bme["SCK"] += self.scl
        self.bme["CSB"] += self.v3v3
        self.bme.nc_unused_pins()

        self.co2 = _ic(self, "SENSOR_SCD41")
        self.co2["VDD"] += self.v3v3
        self.co2["VDD2"] += self.v3v3
        self.co2["GND"] += self.agnd
        self.co2["GND2"] += self.agnd
        self.co2["SCL"] += self.scl
        self.co2["SDA"] += self.sda
        self.co2.nc_unused_pins()

        self.lm75 = _ic(self, "SENSOR_LM75B")
        self.lm75["VS"] += self.v3v3
        self.lm75["GND"] += self.agnd
        self.lm75["SDA"] += self.sda
        self.lm75["SCL"] += self.scl
        self.lm75["A0"] += self.agnd
        self.lm75["A1"] += self.agnd
        self.lm75["A2"] += self.agnd
        self.lm75.nc_unused_pins()

        self.tmp = _ic(self, "SENSOR_TMP117")
        self.tmp["V+"] += self.v3v3
        self.tmp["GND"] += self.agnd
        self.tmp["SDA"] += self.sda
        self.tmp["SCL"] += self.scl
        self.tmp["ADD0"] += self.agnd
        self.tmp.nc_unused_pins()

        self.ina = _ic(self, "SENSOR_INA219")
        self.ina["VS"] += self.v3v3
        self.ina["GND"] += self.agnd
        self.ina["SDA"] += self.sda
        self.ina["SCL"] += self.scl
        self.ina["IN+"] += Net("VIN_48V_FILT")
        self.ina["IN-"] += Net("INA_LOAD")
        self.ina["A0"] += self.agnd
        self.ina["A1"] += self.agnd
        _r(self, "1", Net("VIN_48V_FILT"), Net("INA_LOAD"))

        self.ee = _ic(self, "EEPROM_24LC256")
        self.ee["VCC"] += self.v3v3
        self.ee["VSS"] += self.agnd
        self.ee["SDA"] += self.sda
        self.ee["SCL"] += self.scl
        self.ee.nc_unused_pins()

        self.rtc = _ic(self, "DS3231M")
        self.rtc["VCC"] += self.v3v3
        self.rtc["GND"] += self.agnd
        self.rtc["SDA"] += self.sda
        self.rtc["SCL"] += self.scl
        self.rtc.nc_unused_pins()

        self.acs = _ic(self, "HDR_1x06")
        self.acs["P1"] += Net("VAC_SENSE")
        self.acs["P2"] += self.agnd
        self.acs["P3"] += Net("CT_SENSE")
        self.acs["P4"] += self.agnd
        self.acs["P5"] += Net("SHUNT_P")
        self.acs["P6"] += Net("SHUNT_N")

        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.agnd)


class PowerStageSensors(Module):
    def __init__(self) -> None:
        super().__init__("PowerStageSensors", schematic_sheet="ANALOG")
        self.v3v3, self.v5, self.gnd = Net("3V3"), Net("VBUS_5V"), Net("GND")
        self.tc = _ic(self, "SENSOR_MAX31855")
        self.tc["VCC"] += self.v3v3
        self.tc["GND"] += self.gnd
        self.tc["SCK"] += Net("PWR_SPI_SCK")
        self.tc["SO"] += Net("PWR_SPI_MISO")
        self.tc["CS"] += Net("TC_CS")
        self.tc["T+"] += Net("TC_PLUS")
        self.tc["T-"] += Net("TC_MINUS")
        self.tc.nc_unused_pins()
        self.h = _ic(self, "HDR_1x04")
        self.h["P1"] += Net("TC_PLUS")
        self.h["P2"] += Net("TC_MINUS")
        self.h["P3"] += self.gnd
        self.h["P4"] += self.gnd

        self.hall = _ic(self, "SENSOR_ACS712_20A")
        self.hall["VCC"] += self.v5
        self.hall["GND"] += self.gnd
        self.hall["VIOUT"] += Net("I_AC_SENSE")
        self.hall["IP+"] += Net("AC_IP_P")
        self.hall["IP+_2"] += Net("AC_IP_P")
        self.hall["IP-"] += Net("AC_IP_N")
        self.hall["IP-_2"] += Net("AC_IP_N")
        _c(self, "100nF", self.hall["FILTER"], self.gnd, pkg="0603")
        self.hh = _ic(self, "HDR_1x04")
        self.hh["P1"] += Net("AC_IP_P")
        self.hh["P2"] += Net("AC_IP_N")
        self.hh["P3"] += self.gnd
        self.hh["P4"] += Net("I_AC_SENSE")
        self.pwr3 = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)
        self.pwr5 = self.declare_interface("pwr_5v", self.v5, self.gnd)


# ---------------------------------------------------------------------------
# RADIO
# ---------------------------------------------------------------------------


class EthernetBlock(Module):
    def __init__(self) -> None:
        super().__init__("EthernetBlock", schematic_sheet="RADIO")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.eth = _ic(self, "W5500_ETH")
        self.eth["VDD"] += self.v3v3
        self.eth["VDD2"] += self.v3v3
        self.eth["GND"] += self.gnd
        self.eth["GND2"] += self.gnd
        self.eth["MOSI"] += Net("SPI_MOSI")
        self.eth["MISO"] += Net("SPI_MISO")
        self.eth["SCLK"] += Net("SPI_SCK")
        self.eth["SCS"] += Net("ETH_CS")
        self.eth["RST"] += self.v3v3
        self.eth["TXP"] += Net("ETH_TXP")
        self.eth["TXN"] += Net("ETH_TXN")
        self.eth["RXP"] += Net("ETH_RXP")
        self.eth["RXN"] += Net("ETH_RXN")
        self.eth.nc_unused_pins()
        self.rj = _ic(self, "RJ45_MAGJACK")
        self.rj["TD_P"] += Net("ETH_TXP")
        self.rj["TD_N"] += Net("ETH_TXN")
        self.rj["RD_P"] += Net("ETH_RXP")
        self.rj["RD_N"] += Net("ETH_RXN")
        self.rj["GND"] += self.gnd
        self.rj["SHIELD"] += self.gnd
        self.rj.nc_unused_pins()
        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)
        self.draws_from("3V3", ma=150)


class RadiosHmi(Module):
    def __init__(self) -> None:
        super().__init__("RadiosHmi", schematic_sheet="RADIO")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.lora = _ic(self, "RFM95_LORA")
        self.lora["VDD"] += self.v3v3
        self.lora["GND"] += self.gnd
        self.lora["MOSI"] += Net("SPI_MOSI")
        self.lora["MISO"] += Net("SPI_MISO")
        self.lora["SCK"] += Net("SPI_SCK")
        self.lora["NSS"] += Net("LORA_CS")
        self.lora["DIO0"] += Net("LORA_DIO0")
        self.lora.nc_unused_pins()

        self.nrf = _ic(self, "NRF24L01")
        self.nrf["VCC"] += self.v3v3
        self.nrf["GND"] += self.gnd
        self.nrf["MOSI"] += Net("SPI_MOSI")
        self.nrf["MISO"] += Net("SPI_MISO")
        self.nrf["SCK"] += Net("SPI_SCK")
        self.nrf["CSN"] += Net("NRF_CS")
        self.nrf["CE"] += Net("NRF_CE")
        self.nrf.nc_unused_pins()
        _r(self, "10k", self.v3v3, Net("NRF_CE"))

        self.oled = _ic(self, "OLED_SSD1306")
        self.oled["VIN"] += self.v3v3
        self.oled["GND"] += self.gnd
        self.oled["SDA"] += Net("I2C_SDA")
        self.oled["SCL"] += Net("I2C_SCL")
        self.oled.nc_unused_pins()

        self.sd = _ic(self, "MICROSD_SLOT")
        self.sd["VDD"] += self.v3v3
        self.sd["VSS"] += self.gnd
        self.sd["CMD_DI"] += Net("SPI_MOSI")
        self.sd["DAT0_DO"] += Net("SPI_MISO")
        self.sd["CLK"] += Net("SPI_SCK")
        self.sd["DAT3_CS"] += Net("SD_CS")
        self.sd.nc_unused_pins()

        self.flash = _ic(self, "W25Q32JVSS")
        self.flash["VCC"] += self.v3v3
        self.flash["GND"] += self.gnd
        self.flash["DI"] += Net("SPI_MOSI")
        self.flash["DO"] += Net("SPI_MISO")
        self.flash["CLK"] += Net("SPI_SCK")
        self.flash["CS"] += Net("FLASH_CS")
        self.flash.nc_unused_pins()
        _r(self, "10k", self.v3v3, Net("FLASH_CS"))

        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)


# ---------------------------------------------------------------------------
# Board
# ---------------------------------------------------------------------------


def build_board() -> Board:
    board = Board(
        size_mm=None,
        layers=4,
        compile_goal="handoff",
        strict_footprint_pin_pad_match=True,
        target_kicad=10,
        strict=False,
    )

    usb, cc = UsbJack(), UsbCcStraps()
    batt, pdn, din = Batt48VIn(), PdnFilter48(), Din24VIn()
    b12, b5, b5a = Buck12From48(), Buck5From12(), Buck5From24()
    ldo, ldo18, agnd = Ldo3V3(), Ldo1V8(), AgndTie()

    esp, espc = Esp32S3Edge(), EspLocalCaps()
    c3, c3c = Esp32C3Watchdog(), C3LocalCaps()
    plc, plcc, xtal = PlcCoreF407(), PlcLocalCaps(), StmCrystal()
    pwr_mcu, pwr_c = PowerCoreG474(), G474LocalCaps()

    can_b, can_i, rs = CanBmsIso(), CanInvPhy(), Rs485Phy()
    opto, cont = OptoBank(), ContactorFet()
    senses, pwr_sens = SensorIsland(), PowerStageSensors()
    eth, radios = EthernetBlock(), RadiosHmi()

    modules = [
        usb, cc, batt, pdn, din, b12, b5, b5a, ldo, ldo18, agnd,
        esp, espc, c3, c3c, plc, plcc, xtal, pwr_mcu, pwr_c,
        can_b, can_i, rs, opto, cont, senses, pwr_sens, eth, radios,
    ]
    for m in modules:
        board.add_module(m)

    board.set_schematic_sheet("POWER", usb, cc, batt, pdn, din, b12, b5, b5a, ldo, ldo18, agnd)
    board.set_schematic_sheet("EDGE", esp, espc, c3, c3c, plc, plcc, xtal, pwr_mcu, pwr_c)
    board.set_schematic_sheet("FIELD", can_b, can_i, rs, opto, cont)
    board.set_schematic_sheet("ANALOG", senses, pwr_sens)
    board.set_schematic_sheet("RADIO", eth, radios)

    usb.usb["A5"] += cc.cc1
    usb.usb["B5"] += cc.cc2

    board.connect(batt.pwr, pdn.pwr_in)
    board.connect(pdn.pwr_out, b12.pwr_in)
    board.connect(b12.pwr_out, b5.pwr_in)
    board.connect(b12.pwr_out, cont.pwr)
    board.connect(din.pwr, b5a.pwr_in)
    board.connect(usb.pwr, cc.pwr)
    board.connect(usb.pwr, b5.pwr_out)
    board.connect(usb.pwr, b5a.pwr_out)
    board.connect(usb.pwr, ldo.pwr_in)
    board.connect(usb.pwr, pwr_sens.pwr5)
    board.connect(ldo.pwr_out, ldo18.pwr_in)

    for m in (
        esp, espc, c3, c3c, plc, plcc, pwr_mcu, pwr_c,
        can_b, can_i, rs, opto, senses, eth, radios,
    ):
        board.connect(ldo.pwr_out, m.pwr)
    board.connect(ldo.pwr_out, pwr_sens.pwr3)

    board.declare_power_rail("VIN_48V", batt.v48)
    board.declare_power_rail("VIN_24V", din.v24)
    board.declare_power_rail("VSYS_12V", b12.v12)
    board.declare_power_rail("VBUS_5V", usb.vbus)
    board.declare_power_rail("3V3", ldo.v3v3)
    board.declare_power_rail("1V8", ldo18.v1v8)
    board.declare_power_rail("GND", usb.gnd)
    board.declare_power_rail("AGND", agnd.agnd)

    board.declare_rail_conversion("VIN_48V", "VSYS_12V", efficiency=0.92)
    board.declare_rail_conversion("VSYS_12V", "VBUS_5V", efficiency=0.90)
    board.declare_rail_conversion("VIN_24V", "VBUS_5V", efficiency=0.90)
    board.declare_rail_conversion("VBUS_5V", "3V3", efficiency=0.85)
    board.declare_rail_conversion("3V3", "1V8", efficiency=0.85)

    board.declare_net_role(agnd.agnd, "analog_ground")
    board.declare_net_role(usb.gnd, "digital_ground")
    board.declare_net_merge_hint(agnd.agnd, usb.gnd, via="star_point")

    board.route_differential_pair(Net("ETH_TXP"), Net("ETH_TXN"), target_impedance_ohms=100.0)
    board.route_differential_pair(Net("ETH_RXP"), Net("ETH_RXN"), target_impedance_ohms=100.0)
    board.declare_stackup_reference(
        Path(__file__).resolve().parents[1] / "docs" / "stackup_template.yaml",
        role="si_documentation",
        documentation_note="4-layer BESS plant brick",
    )

    board.constrain_distance_min(esp, plc, min_distance_mm=4.0)
    board.constrain_distance_min(plc, pwr_mcu, min_distance_mm=6.0)
    board.constrain_distance_min(can_b, can_i, min_distance_mm=8.0)
    board.constrain_distance_min(eth, radios, min_distance_mm=8.0)

    espc.cluster_with(esp)
    c3c.cluster_with(c3)
    plcc.cluster_with(plc)
    xtal.cluster_with(plc)
    pwr_c.cluster_with(pwr_mcu)
    pdn.cluster_with(batt)
    b12.cluster_with(pdn)
    b5.cluster_with(b12)
    senses.cluster_with(agnd)
    pwr_sens.cluster_with(pwr_mcu)

    board.declare_copper_pour_intent(usb.gnd, layer="F.Cu", purpose="ground")
    board.declare_copper_pour_intent(usb.gnd, layer="B.Cu", purpose="ground")
    board.declare_copper_pour_intent(usb.gnd, layer="In1.Cu", purpose="ground_plane")
    board.declare_copper_pour_intent(ldo.v3v3, layer="In2.Cu", purpose="power_plane")

    board.set_net_current(batt.v48, 5.0, note="pack bus")
    board.set_net_current(b12.v12, 1.5, note="12V")
    board.set_net_current(usb.vbus, 2.0, note="5V")
    board.set_net_current(ldo.v3v3, 1.5, note="3V3")
    board.set_net_current(usb.gnd, 3.0, note="return")
    return board


board = build_board()

if __name__ == "__main__":
    n = sum(len(m.components) for m in board._get_all_modules())
    print(f"BESS plant (catalog): {n} components / {len(board._get_all_modules())} modules")
    print("MCUs: ESP32-S3 + ESP32-C3 + STM32F407 (PLC) + STM32G474 (power)")
    print("Sensors: BME280 SCD41 LM75 TMP117 INA219 MAX31855 ACS712 AD620 ADS1115")
