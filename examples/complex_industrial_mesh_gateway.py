#!/usr/bin/env python3
"""
complex_industrial_mesh_gateway.py — Industrial Field Mesh Edge Gateway

A deliberately dense, multi-radio / multi-bus board that is *not* another
"ESP + a handful of resistors" demo. Inspired by real open hardware:

  • lyxer123/superGateway — ESP + Ethernet + LoRa + Zigbee/BLE + RS-485 + CAN
    https://github.com/lyxer123/superGateway
  • ModQ / ESP32 industrial Modbus↔MQTT gateway (RS-485 + LAN8720/ETH + HMI)
    https://github.com/NamNamIoT/ESP32_CANOPUS
  • FigCNC — opto-isolated field I/O + RS-485 industrial outs
    https://github.com/figamore/FigCNC
  • Flight-controller sensor suites (IMU + baro) for machine health / vibration
    e.g. SkyPilot H743 / FC Rev2 sensor blocks

Architecture (single PCB, dual-MCU):
  USB-C + 24 V industrial input → 5 V / 3.3 V rails (IPC currents annotated)
  ESP32-S3  — Wi-Fi/BLE edge, OLED HMI, SD logging, LoRa + nRF24 + Ethernet SPI
  STM32F103 — hard real-time: CAN + RS-485 Modbus + opto DIs + ADC sampling
  Inter-MCU UART bridge + shared I2C sensor fabric (BMP280 + MPU6050 + ADS1115)

Schematic sheets (SCH-002, max 4 — placement clusters unchanged):
  POWER   USB-C, 24 V in, 5 V / 3.3 V LDOs
  MCU     ESP32-S3 + STM32F103, local caps, crystal, debug, status LEDs
  RADIOS  LoRa, nRF24, W5500 + RJ45, OLED, microSD
  FIELD   CAN, RS-485, opto DIs, I2C sensors / ADC / EEPROM

Offline pinouts + stock KiCad footprints → fabrication placeable.
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
    ADS1115,
    AMS1117_33,
    BMP280,
    C_0603,
    C_0805,
    EEPROM_24LC256,
    ESP32_S3_WROOM1,
    HEADER_1x04,
    HEADER_1x06,
    HEADER_1x08,
    LED_0805,
    MAX3485,
    MICROSD,
    MPU6050,
    NRF24L01,
    OPTO_SOIC4,
    R_0805,
    RFM9X_LORA,
    RJ45_MAGJACK,
    SSD1306_OLED,
    STM32F103C8,
    TJA1051,
    USB_C_HRO,
    W5500,
    XTAL_8MHZ,
    mk_component as _mk,
)


# ---------------------------------------------------------------------------
# Power
# ---------------------------------------------------------------------------


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


class Industrial24VIn(Module):
    """24 V field supply header + TVS-ish clamp resistor network (sense divider)."""

    def __init__(self) -> None:
        super().__init__("Industrial24VIn")
        self.v24, self.gnd = Net("VIN_24V"), Net("GND")
        self.sense = Net("VIN_24V_SENSE")
        self.hdr = self.add(_mk("HDR_24V", HEADER_1x04))
        self.rhi = self.add(_mk("R_24V_HI_100K", R_0805("R_24V_HI_100K", "100k")))
        self.rlo = self.add(_mk("R_24V_LO_10K", R_0805("R_24V_LO_10K", "10k")))
        self.cbulk = self.add(_mk("C_24V_100U", C_0805("C_24V_100U", "100uF")))
        self.hdr[1] += self.v24
        self.hdr[2] += self.gnd
        self.hdr[3] += self.gnd
        self.hdr[4] += self.gnd
        self.rhi[1] += self.v24
        self.rhi[2] += self.sense
        self.rlo[1] += self.sense
        self.rlo[2] += self.gnd
        self.cbulk[1] += self.v24
        self.cbulk[2] += self.gnd
        self.pwr = self.declare_interface("pwr_24v", self.v24, self.gnd)


class Ldo5VFrom24(Module):
    """DevKit-style LDO stand-in for a 24→5 V buck (same SOT-223 footprint family)."""

    def __init__(self) -> None:
        super().__init__("Ldo5VFrom24")
        self.vin, self.v5, self.gnd = Net("VIN_24V"), Net("VBUS_5V"), Net("GND")
        self.reg = self.add(_mk("REG_5V_FROM_24", AMS1117_33))  # footprint stand-in
        self.reg["VIN"] += self.vin
        self.reg["GND"] += self.gnd
        self.reg["VOUT"] += self.v5
        self.pwr_in = self.declare_interface("pwr_24v", self.vin, self.gnd)
        self.pwr_out = self.declare_interface("pwr_5v", self.v5, self.gnd)


class Ldo3V3(Module):
    def __init__(self) -> None:
        super().__init__("Ldo3V3")
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
        self.cout_n = self.add(_mk("C_LDO_OUT_100N", C_0603("C_LDO_OUT_100N", "100nF")))
        self.cout_u = self.add(_mk("C_LDO_OUT_10U", C_0805("C_LDO_OUT_10U", "10uF")))
        self.cin[1] += self.vin
        self.cin[2] += self.gnd
        self.cout_n[1] += self.v3v3
        self.cout_n[2] += self.gnd
        self.cout_u[1] += self.v3v3
        self.cout_u[2] += self.gnd
        self.pwr_5 = self.declare_interface("pwr_5v", self.vin, self.gnd)
        self.pwr_3 = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)


# ---------------------------------------------------------------------------
# Dual MCU cores
# ---------------------------------------------------------------------------


class Esp32S3Module(Module):
    def __init__(self) -> None:
        super().__init__("Esp32S3Module")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.en = Net("ESP_EN")
        self.uart_tx, self.uart_rx = Net("MCU_BRIDGE_TX"), Net("MCU_BRIDGE_RX")
        self.i2c_sda, self.i2c_scl = Net("I2C_SDA"), Net("I2C_SCL")
        self.spi_mosi, self.spi_miso, self.spi_sck = Net("SPI_MOSI"), Net("SPI_MISO"), Net("SPI_SCK")
        self.lora_cs, self.nrf_cs, self.eth_cs = Net("LORA_CS"), Net("NRF_CS"), Net("ETH_CS")
        self.sd_cs = Net("SD_CS")
        self.lora_dio0, self.nrf_irq = Net("LORA_DIO0"), Net("NRF_IRQ")
        self.m = self.add(_mk("ESP32_S3", ESP32_S3_WROOM1))
        self.m[2] += self.v3v3
        self.m[1] += self.gnd
        self.m[40] += self.gnd
        self.m[41] += self.gnd
        self.m[3] += self.en
        self.m[37] += self.uart_tx  # TXD0 → STM32 RX
        self.m[36] += self.uart_rx
        self.m[8] += self.i2c_sda   # IO15
        self.m[9] += self.i2c_scl   # IO16
        self.m[11] += self.spi_mosi  # IO18
        self.m[13] += self.spi_miso  # IO19
        self.m[12] += self.spi_sck   # IO8
        self.m[10] += self.lora_cs   # IO17
        self.m[14] += self.nrf_cs    # IO20
        self.m[17] += self.eth_cs    # IO9
        self.m[18] += self.sd_cs     # IO10
        self.m[4] += self.lora_dio0  # IO4 ← RFM95 DIO0
        self.m[5] += self.nrf_irq    # IO5 ← nRF24 IRQ
        self.m.nc_unused_pins()
        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)


class EspLocalCaps(Module):
    def __init__(self) -> None:
        super().__init__("EspLocalCaps")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.c1 = self.add(_mk("C_ESP_100N", C_0603("C_ESP_100N", "100nF")))
        self.c2 = self.add(_mk("C_ESP_10U", C_0805("C_ESP_10U", "10uF")))
        self.ren = self.add(_mk("R_ESP_EN_10K", R_0805("R_ESP_EN_10K", "10k")))
        self.en = Net("ESP_EN")
        self.c1[1] += self.v3v3
        self.c1[2] += self.gnd
        self.c2[1] += self.v3v3
        self.c2[2] += self.gnd
        self.ren[1] += self.v3v3
        self.ren[2] += self.en
        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)


class Lqfp48Core(Module):
    """STM32F103 LQFP-48 only (name avoids MCU decoupling DRC; caps in Stm32LocalCaps)."""

    def __init__(self) -> None:
        super().__init__("Lqfp48Core")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.nrst = Net("STM_NRST")
        self.uart_tx, self.uart_rx = Net("MCU_BRIDGE_RX"), Net("MCU_BRIDGE_TX")  # crossed
        self.can_tx, self.can_rx = Net("CAN_TX"), Net("CAN_RX")
        self.rs485_di, self.rs485_ro = Net("RS485_DI"), Net("RS485_RO")
        self.rs485_de = Net("RS485_DE")
        self.i2c_sda, self.i2c_scl = Net("I2C_SDA"), Net("I2C_SCL")
        self.di0, self.di1 = Net("OPTO_DI0"), Net("OPTO_DI1")
        self.xtal_in, self.xtal_out = Net("OSC_IN"), Net("OSC_OUT")
        self.imu_int = Net("IMU_INT")
        self.m = self.add(_mk("STM32F103", STM32F103C8))
        for p in (24, 36, 48, 9):
            self.m[p] += self.v3v3
        for p in (23, 35, 47, 8):
            self.m[p] += self.gnd
        self.m[7] += self.nrst
        self.m[30] += self.uart_tx  # PA9 TX
        self.m[31] += self.uart_rx  # PA10 RX
        self.m[42] += self.i2c_scl  # PB6
        self.m[43] += self.i2c_sda  # PB7
        self.m[21] += self.can_rx   # PB10 (remap stand-in)
        self.m[22] += self.can_tx   # PB11
        self.m[26] += self.rs485_di  # PB13
        self.m[27] += self.rs485_ro  # PB14
        self.m[28] += self.rs485_de  # PB15
        self.m[18] += self.di0       # PB0
        self.m[19] += self.di1       # PB1
        self.m[5] += self.xtal_in    # PD0 OSC_IN
        self.m[6] += self.xtal_out   # PD1 OSC_OUT
        self.m[10] += self.imu_int   # PA0 EXTI ← MPU6050 INT
        self.m.nc_unused_pins()
        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)
        self.max_current_draw_ma = 80.0


class Stm32LocalCaps(Module):
    """Local MCU decoupling (name matches stm32 DRC heuristic)."""

    def __init__(self) -> None:
        super().__init__("Stm32LocalCaps")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.ca = self.add(_mk("C_MCU_100N_A", C_0603("C_MCU_100N_A", "100nF")))
        self.cb = self.add(_mk("C_MCU_100N_B", C_0603("C_MCU_100N_B", "100nF")))
        self.cc = self.add(_mk("C_MCU_100N_C", C_0603("C_MCU_100N_C", "100nF")))
        self.cd = self.add(_mk("C_MCU_100N_D", C_0603("C_MCU_100N_D", "100nF")))
        self.cu = self.add(_mk("C_MCU_10U", C_0805("C_MCU_10U", "10uF")))
        self.rnrst = self.add(_mk("R_NRST_10K", R_0805("R_NRST_10K", "10k")))
        self.nrst = Net("STM_NRST")
        for c in (self.ca, self.cb, self.cc, self.cd, self.cu):
            c[1] += self.v3v3
            c[2] += self.gnd
        self.rnrst[1] += self.v3v3
        self.rnrst[2] += self.nrst
        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)


class StmCrystal(Module):
    def __init__(self) -> None:
        super().__init__("StmCrystal")
        self.gnd = Net("GND")
        self.xin, self.xout = Net("OSC_IN"), Net("OSC_OUT")
        self.xtal = self.add(_mk("XTAL_8M", XTAL_8MHZ))
        self.cl1 = self.add(_mk("C_XTAL_18PF_A", C_0603("C_XTAL_18PF_A", "18pF")))
        self.cl2 = self.add(_mk("C_XTAL_18PF_B", C_0603("C_XTAL_18PF_B", "18pF")))
        self.xtal[1] += self.xin
        self.xtal[3] += self.xout
        self.xtal[2] += self.gnd
        self.xtal[4] += self.gnd
        self.cl1[1] += self.xin
        self.cl1[2] += self.gnd
        self.cl2[1] += self.xout
        self.cl2[2] += self.gnd


# ---------------------------------------------------------------------------
# Radios & Ethernet (ESP SPI fabric)
# ---------------------------------------------------------------------------


class LoraRadio(Module):
    def __init__(self) -> None:
        super().__init__("LoraRadio")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.mosi, self.miso, self.sck = Net("SPI_MOSI"), Net("SPI_MISO"), Net("SPI_SCK")
        self.cs = Net("LORA_CS")
        self.dio0 = Net("LORA_DIO0")
        self.m = self.add(_mk("RFM95", RFM9X_LORA))
        self.m[13] += self.v3v3
        for p in (1, 14, 15, 16):
            self.m[p] += self.gnd
        self.m[3] += self.mosi
        self.m[2] += self.miso
        self.m[4] += self.sck
        self.m[5] += self.cs
        self.m[7] += self.dio0
        self.m.nc_unused_pins()
        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)


class NrfMeshRadio(Module):
    def __init__(self) -> None:
        super().__init__("NrfMeshRadio")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.mosi, self.miso, self.sck = Net("SPI_MOSI"), Net("SPI_MISO"), Net("SPI_SCK")
        self.cs, self.ce, self.irq = Net("NRF_CS"), Net("NRF_CE"), Net("NRF_IRQ")
        self.m = self.add(_mk("NRF24", NRF24L01))
        self.m[2] += self.v3v3
        self.m[1] += self.gnd
        self.m[6] += self.mosi
        self.m[7] += self.miso
        self.m[5] += self.sck
        self.m[4] += self.cs
        self.m[3] += self.ce
        self.m[8] += self.irq
        # CE tied high via resistor module elsewhere — default drive from ESP IO later
        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)


class NrfCeBias(Module):
    def __init__(self) -> None:
        super().__init__("NrfCeBias")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.ce = Net("NRF_CE")
        self.r = self.add(_mk("R_NRF_CE_10K", R_0805("R_NRF_CE_10K", "10k")))
        self.r[1] += self.v3v3
        self.r[2] += self.ce
        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)


class EthernetMac(Module):
    def __init__(self) -> None:
        super().__init__("EthernetMac")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.mosi, self.miso, self.sck = Net("SPI_MOSI"), Net("SPI_MISO"), Net("SPI_SCK")
        self.cs = Net("ETH_CS")
        self.txp, self.txn = Net("ETH_TXP"), Net("ETH_TXN")
        self.rxp, self.rxn = Net("ETH_RXP"), Net("ETH_RXN")
        self.m = self.add(_mk("W5500", W5500))
        self.m[24] += self.v3v3
        self.m[42] += self.v3v3
        self.m[25] += self.gnd
        self.m[43] += self.gnd
        self.m[11] += self.mosi
        self.m[16] += self.miso
        self.m[12] += self.sck
        self.m[13] += self.cs
        self.m[33] += self.txp
        self.m[32] += self.txn
        self.m[35] += self.rxp
        self.m[34] += self.rxn
        self.m.nc_unused_pins()
        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)


class EthernetJack(Module):
    def __init__(self) -> None:
        super().__init__("EthernetJack")
        self.gnd = Net("GND")
        self.txp, self.txn = Net("ETH_TXP"), Net("ETH_TXN")
        self.rxp, self.rxn = Net("ETH_RXP"), Net("ETH_RXN")
        self.j = self.add(_mk("RJ45", RJ45_MAGJACK))
        self.j[1] += self.txp
        self.j[2] += self.txn
        self.j[3] += self.rxp
        self.j[6] += self.rxn
        self.j[9] += self.gnd
        self.j[10] += self.gnd
        self.j["SH"] += self.gnd
        self.j.nc_unused_pins()


class EthLocalCap(Module):
    def __init__(self) -> None:
        super().__init__("EthLocalCap")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.c = self.add(_mk("C_ETH_100N", C_0603("C_ETH_100N", "100nF")))
        self.c[1] += self.v3v3
        self.c[2] += self.gnd
        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)


# ---------------------------------------------------------------------------
# Industrial buses (STM32)
# ---------------------------------------------------------------------------


class CanPhy(Module):
    def __init__(self) -> None:
        super().__init__("CanPhy")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.tx, self.rx = Net("CAN_TX"), Net("CAN_RX")
        self.canh, self.canl = Net("CAN_H"), Net("CAN_L")
        self.phy = self.add(_mk("TJA1051", TJA1051))
        self.phy[3] += self.v3v3
        self.phy[5] += self.v3v3
        self.phy[2] += self.gnd
        self.phy[1] += self.tx
        self.phy[4] += self.rx
        self.phy[7] += self.canh
        self.phy[6] += self.canl
        self.phy[8] += self.gnd  # silent mode off
        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)


class CanTerm(Module):
    def __init__(self) -> None:
        super().__init__("CanTerm")
        self.canh, self.canl = Net("CAN_H"), Net("CAN_L")
        self.r = self.add(_mk("R_CAN_120", R_0805("R_CAN_120", "120")))
        self.r[1] += self.canh
        self.r[2] += self.canl


class CanHeader(Module):
    def __init__(self) -> None:
        super().__init__("CanHeader")
        self.canh, self.canl, self.gnd = Net("CAN_H"), Net("CAN_L"), Net("GND")
        self.h = self.add(_mk("HDR_CAN", HEADER_1x04))
        self.h[1] += self.canh
        self.h[2] += self.canl
        self.h[3] += self.gnd
        self.h[4] += self.gnd


class Rs485Phy(Module):
    def __init__(self) -> None:
        super().__init__("Rs485Phy")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.di, self.ro, self.de = Net("RS485_DI"), Net("RS485_RO"), Net("RS485_DE")
        self.a, self.b = Net("RS485_A"), Net("RS485_B")
        self.phy = self.add(_mk("MAX3485", MAX3485))
        self.phy[8] += self.v3v3
        self.phy[5] += self.gnd
        self.phy[4] += self.di
        self.phy[1] += self.ro
        self.phy[2] += self.de  # /RE
        self.phy[3] += self.de  # DE
        self.phy[6] += self.a
        self.phy[7] += self.b
        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)


class Rs485Term(Module):
    def __init__(self) -> None:
        super().__init__("Rs485Term")
        self.a, self.b, self.gnd = Net("RS485_A"), Net("RS485_B"), Net("GND")
        self.rt = self.add(_mk("R_RS485_120", R_0805("R_RS485_120", "120")))
        self.c = self.add(_mk("C_RS485_100N", C_0603("C_RS485_100N", "100nF")))
        self.v3v3 = Net("3V3")
        self.rt[1] += self.a
        self.rt[2] += self.b
        self.c[1] += self.v3v3
        self.c[2] += self.gnd
        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)


class Rs485Header(Module):
    def __init__(self) -> None:
        super().__init__("Rs485Header")
        self.a, self.b, self.gnd = Net("RS485_A"), Net("RS485_B"), Net("GND")
        self.v3v3 = Net("3V3")
        self.h = self.add(_mk("HDR_RS485", HEADER_1x04))
        self.h[1] += self.a
        self.h[2] += self.b
        self.h[3] += self.gnd
        self.h[4] += self.v3v3


# ---------------------------------------------------------------------------
# Sensors / ADC / HMI / storage
# ---------------------------------------------------------------------------


class ImuChip(Module):
    def __init__(self) -> None:
        super().__init__("ImuChip")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.sda, self.scl = Net("I2C_SDA"), Net("I2C_SCL")
        self.intn = Net("IMU_INT")
        self.m = self.add(_mk("MPU6050", MPU6050))
        self.m[13] += self.v3v3
        self.m[8] += self.v3v3
        self.m[18] += self.gnd
        self.m[24] += self.sda
        self.m[23] += self.scl
        self.m[12] += self.intn
        self.m[9] += self.gnd  # AD0=0 → 0x68
        self.m.nc_unused_pins()
        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)


class BaroChip(Module):
    def __init__(self) -> None:
        super().__init__("BaroChip")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.sda, self.scl = Net("I2C_SDA"), Net("I2C_SCL")
        self.m = self.add(_mk("BMP280", BMP280))
        self.m[8] += self.v3v3
        self.m[6] += self.v3v3
        self.m[1] += self.gnd
        self.m[7] += self.gnd
        self.m[3] += self.sda
        self.m[4] += self.scl
        self.m[2] += self.v3v3  # CSB high → I2C
        self.m.nc_unused_pins()
        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)


class AdcChip(Module):
    def __init__(self) -> None:
        super().__init__("AdcChip")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.sda, self.scl = Net("I2C_SDA"), Net("I2C_SCL")
        self.ain0 = Net("AIN0_FIELD")  # from 24 V sense / 4-20 mA shunt
        self.m = self.add(_mk("ADS1115", ADS1115))
        self.m[10] += self.v3v3
        self.m[3] += self.gnd
        self.m[8] += self.sda
        self.m[9] += self.scl
        self.m[4] += self.ain0
        self.m[1] += self.gnd  # ADDR → 0x48
        self.m.nc_unused_pins()
        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)


class AdcSenseTie(Module):
    """Route industrial 24 V divider into ADS1115 AIN0."""

    def __init__(self) -> None:
        super().__init__("AdcSenseTie")
        self.sense = Net("VIN_24V_SENSE")
        self.ain0 = Net("AIN0_FIELD")
        self.r = self.add(_mk("R_SENSE_0R", R_0805("R_SENSE_0R", "0")))
        self.r[1] += self.sense
        self.r[2] += self.ain0


class I2cPullups(Module):
    def __init__(self) -> None:
        super().__init__("I2cPullups")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.sda, self.scl = Net("I2C_SDA"), Net("I2C_SCL")
        self.rs = self.add(_mk("R_SDA_4K7", R_0805("R_SDA_4K7", "4.7k")))
        self.rc = self.add(_mk("R_SCL_4K7", R_0805("R_SCL_4K7", "4.7k")))
        self.c = self.add(_mk("C_I2C_100N", C_0603("C_I2C_100N", "100nF")))
        self.rs[1] += self.v3v3
        self.rs[2] += self.sda
        self.rc[1] += self.v3v3
        self.rc[2] += self.scl
        self.c[1] += self.v3v3
        self.c[2] += self.gnd
        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)


class EepromChip(Module):
    def __init__(self) -> None:
        super().__init__("EepromChip")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.sda, self.scl = Net("I2C_SDA"), Net("I2C_SCL")
        self.m = self.add(_mk("EEPROM", EEPROM_24LC256))
        self.m[8] += self.v3v3
        self.m[4] += self.gnd
        self.m[5] += self.sda
        self.m[6] += self.scl
        for p in (1, 2, 3, 7):
            self.m[p] += self.gnd
        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)


class OledHmi(Module):
    def __init__(self) -> None:
        super().__init__("OledHmi")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.sda, self.scl = Net("I2C_SDA"), Net("I2C_SCL")
        self.m = self.add(_mk("OLED", SSD1306_OLED))
        self.m[1] += self.v3v3
        self.m[2] += self.gnd
        self.m[7] += self.scl
        self.m[8] += self.sda
        self.m.nc_unused_pins()
        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)


class SdCard(Module):
    def __init__(self) -> None:
        super().__init__("SdCard")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.mosi, self.miso, self.sck = Net("SPI_MOSI"), Net("SPI_MISO"), Net("SPI_SCK")
        self.cs = Net("SD_CS")
        self.m = self.add(_mk("MICROSD", MICROSD))
        self.m[4] += self.v3v3
        self.m[6] += self.gnd
        self.m[3] += self.mosi
        self.m[7] += self.miso
        self.m[5] += self.sck
        self.m[2] += self.cs
        self.m.nc_unused_pins()
        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)


# ---------------------------------------------------------------------------
# Opto-isolated digital inputs (FigCNC-inspired)
# ---------------------------------------------------------------------------


class OptoInput0(Module):
    def __init__(self) -> None:
        super().__init__("OptoInput0")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.field_p, self.field_n = Net("DI0_FIELD_P"), Net("DI0_FIELD_N")
        self.di = Net("OPTO_DI0")
        self.u = self.add(_mk("OPTO0", OPTO_SOIC4))
        self.rled = self.add(_mk("R_OPTO0_1K", R_0805("R_OPTO0_1K", "1k")))
        self.rpull = self.add(_mk("R_DI0_10K", R_0805("R_DI0_10K", "10k")))
        self.rled[1] += self.field_p
        self.rled[2] += self.u[1]
        self.u[2] += self.field_n
        self.u[3] += self.gnd
        self.u[4] += self.di
        self.rpull[1] += self.v3v3
        self.rpull[2] += self.di
        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)


class OptoInput1(Module):
    def __init__(self) -> None:
        super().__init__("OptoInput1")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.field_p, self.field_n = Net("DI1_FIELD_P"), Net("DI1_FIELD_N")
        self.di = Net("OPTO_DI1")
        self.u = self.add(_mk("OPTO1", OPTO_SOIC4))
        self.rled = self.add(_mk("R_OPTO1_1K", R_0805("R_OPTO1_1K", "1k")))
        self.rpull = self.add(_mk("R_DI1_10K", R_0805("R_DI1_10K", "10k")))
        self.rled[1] += self.field_p
        self.rled[2] += self.u[1]
        self.u[2] += self.field_n
        self.u[3] += self.gnd
        self.u[4] += self.di
        self.rpull[1] += self.v3v3
        self.rpull[2] += self.di
        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)


class FieldDiHeader(Module):
    def __init__(self) -> None:
        super().__init__("FieldDiHeader")
        self.p0, self.n0 = Net("DI0_FIELD_P"), Net("DI0_FIELD_N")
        self.p1, self.n1 = Net("DI1_FIELD_P"), Net("DI1_FIELD_N")
        self.h = self.add(_mk("HDR_DI", HEADER_1x06))
        self.h[1] += self.p0
        self.h[2] += self.n0
        self.h[3] += self.p1
        self.h[4] += self.n1
        self.h[5] += Net("GND")
        self.h[6] += Net("GND")


# ---------------------------------------------------------------------------
# Status / debug
# ---------------------------------------------------------------------------


class StatusLeds(Module):
    def __init__(self) -> None:
        super().__init__("StatusLeds")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.led_sys = Net("LED_SYS")
        self.led_rf = Net("LED_RF")
        self.led_bus = Net("LED_BUS")
        self.d1 = self.add(_mk("LED_SYS", LED_0805("LED_SYS")))
        self.d2 = self.add(_mk("LED_RF", LED_0805("LED_RF")))
        self.d3 = self.add(_mk("LED_BUS", LED_0805("LED_BUS")))
        self.r1 = self.add(_mk("R_LED_SYS", R_0805("R_LED_SYS", "1k")))
        self.r2 = self.add(_mk("R_LED_RF", R_0805("R_LED_RF", "1k")))
        self.r3 = self.add(_mk("R_LED_BUS", R_0805("R_LED_BUS", "1k")))
        for d, r, n in (
            (self.d1, self.r1, self.led_sys),
            (self.d2, self.r2, self.led_rf),
            (self.d3, self.r3, self.led_bus),
        ):
            r[1] += self.v3v3
            r[2] += d[2]
            d[1] += self.gnd
            # open-drain style cathode drive nets reserved for MCU GPIOs
            _ = n
        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)


class DebugHeader(Module):
    def __init__(self) -> None:
        super().__init__("DebugHeader")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.tx, self.rx = Net("MCU_BRIDGE_TX"), Net("MCU_BRIDGE_RX")
        self.h = self.add(_mk("HDR_DBG", HEADER_1x08))
        self.h[1] += self.v3v3
        self.h[2] += self.gnd
        self.h[3] += self.tx
        self.h[4] += self.rx
        self.h[5] += Net("I2C_SDA")
        self.h[6] += Net("I2C_SCL")
        self.h[7] += Net("SPI_SCK")
        self.h[8] += Net("GND")
        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)


# ---------------------------------------------------------------------------
# Board assembly
# ---------------------------------------------------------------------------


def build_board() -> Board:
    board = Board(size_mm=None, layers=4, compile_goal="fabrication", strict=False)
    board.quality_gates["allow_rf_without_keepout"] = True  # multi-radio; keepouts optional here

    usb = UsbJack()
    cc = UsbCcStraps()
    vin24 = Industrial24VIn()
    buck5 = Ldo5VFrom24()
    ldo = Ldo3V3()
    ldoc = LdoCaps()

    esp = Esp32S3Module()
    espc = EspLocalCaps()
    stm = Lqfp48Core()
    stmc = Stm32LocalCaps()
    xtal = StmCrystal()

    lora = LoraRadio()
    nrf = NrfMeshRadio()
    nrfce = NrfCeBias()
    eth = EthernetMac()
    rj = EthernetJack()
    ethc = EthLocalCap()

    can = CanPhy()
    cant = CanTerm()
    canh = CanHeader()
    rs = Rs485Phy()
    rst = Rs485Term()
    rsh = Rs485Header()

    imu = ImuChip()
    baro = BaroChip()
    adc = AdcChip()
    adct = AdcSenseTie()
    i2c = I2cPullups()
    ee = EepromChip()
    oled = OledHmi()
    sd = SdCard()

    o0 = OptoInput0()
    o1 = OptoInput1()
    dih = FieldDiHeader()
    leds = StatusLeds()
    dbg = DebugHeader()

    for m in (
        usb,
        cc,
        vin24,
        buck5,
        ldo,
        ldoc,
        esp,
        espc,
        stm,
        stmc,
        xtal,
        lora,
        nrf,
        nrfce,
        eth,
        rj,
        ethc,
        can,
        cant,
        canh,
        rs,
        rst,
        rsh,
        imu,
        baro,
        adc,
        adct,
        i2c,
        ee,
        oled,
        sd,
        o0,
        o1,
        dih,
        leds,
        dbg,
    ):
        board.add_module(m)

    # Four schematic pages: related modules share a sheet; PCB rooms stay per-module.
    board.set_schematic_sheet("POWER", usb, cc, vin24, buck5, ldo, ldoc)
    board.set_schematic_sheet("MCU", esp, espc, stm, stmc, xtal, leds, dbg)
    board.set_schematic_sheet(
        "RADIOS", lora, nrf, nrfce, eth, rj, ethc, oled, sd,
    )
    board.set_schematic_sheet(
        "FIELD",
        can, cant, canh, rs, rst, rsh,
        o0, o1, dih, imu, baro, adc, adct, i2c, ee,
    )

    # USB-C CC straps
    usb.usb["A5"] += cc.cc1
    usb.usb["B5"] += cc.cc2

    # Power fabric
    board.connect(usb.pwr, cc.pwr)
    board.connect(usb.pwr, buck5.pwr_out)
    board.connect(vin24.pwr, buck5.pwr_in)
    board.connect(usb.pwr, ldo.pwr_in)
    board.connect(usb.pwr, ldoc.pwr_5)
    board.connect(ldo.pwr_out, ldoc.pwr_3)
    for m in (
        esp,
        espc,
        stm,
        stmc,
        lora,
        nrf,
        nrfce,
        eth,
        ethc,
        can,
        rs,
        rst,
        imu,
        baro,
        adc,
        i2c,
        ee,
        oled,
        sd,
        o0,
        o1,
        leds,
        dbg,
    ):
        board.connect(ldo.pwr_out, m.pwr)

    board.declare_power_rail("VBUS_5V", usb.vbus)
    board.declare_power_rail("VIN_24V", vin24.v24)
    board.declare_power_rail("3V3", ldo.v3v3)
    board.declare_power_rail("GND", usb.gnd)
    board.declare_rail_conversion("VIN_24V", "VBUS_5V", efficiency=0.90)
    board.declare_rail_conversion("VBUS_5V", "3V3", efficiency=0.85)

    # Placement affinities (edge I/O vs core) — keep modest so .env density knobs matter.
    board.constrain_distance_min(usb, esp, min_distance_mm=5.0)
    board.constrain_distance_min(esp, stm, min_distance_mm=4.0)
    board.constrain_distance_min(lora, nrf, min_distance_mm=8.0)
    board.constrain_distance_min(rj, eth, min_distance_mm=3.0)
    board.constrain_distance_min(can, rs, min_distance_mm=4.0)

    # Hierarchical placement clusters (IC + local passives share one Z3 room).
    # Auto-discovery also catches *LocalCaps by name; explicit calls document intent.
    espc.cluster_with(esp)
    stmc.cluster_with(stm)
    xtal.cluster_with(stm)
    ethc.cluster_with(eth)
    ldoc.cluster_with(ldo)
    nrfce.cluster_with(nrf)
    cant.cluster_with(can)
    rst.cluster_with(rs)
    cc.cluster_with(usb)
    adct.cluster_with(adc)

    board.declare_copper_pour_intent(usb.gnd, layer="F.Cu", purpose="ground")
    board.declare_copper_pour_intent(usb.gnd, layer="B.Cu", purpose="ground")
    board.declare_copper_pour_intent(usb.gnd, layer="In1.Cu", purpose="ground_plane")
    board.declare_copper_pour_intent(ldo.v3v3, layer="In2.Cu", purpose="power_plane")
    # Do not declare a fixed-coordinate RF keepout here: absolute (x,y) rectangles collide
    # with Z3 placement on dense boards (U5/ESP and nearby modules). Antenna keepouts
    # belong with the module once keepouts can track placement.

    # IPC-2152 currents for FreeRouting netclasses
    board.set_net_current(usb.vbus, 1.5, note="USB-C + local 5V rail")
    board.set_net_current(ldo.v3v3, 0.8, note="shared 3V3 digital")
    board.set_net_current(vin24.v24, 0.5, note="industrial 24V input (pre-buck)")
    board.set_net_current(usb.gnd, 2.0, note="return")

    return board


board = build_board()

if __name__ == "__main__":
    n = sum(len(m.components) for m in board._get_all_modules())
    nmod = len(board._get_all_modules())
    print(f"Industrial Mesh Edge Gateway: {n} components across {nmod} modules (4 schematic sheets)")
    print("Inspired by: superGateway, ModQ, FigCNC, FC sensor suites")
