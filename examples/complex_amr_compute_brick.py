#!/usr/bin/env python3
"""
complex_amr_compute_brick.py — Factory AMR / AGV compute brick (compiler ceiling)

A 6-layer, triple-MCU motion brick that is *not* another radio gateway.
It exists to stress OpenHaC APIs the industrial mesh example does not hit:

  • Board(layers=6) + inner pours In1–In4
  • Bus() for daisy-chained 74HC595 outputs
  • route_differential_pair + declare_length_match_intent (USB D+/D−)
  • declare_net_tie / analog_ground vs digital_ground (AGND star)
  • declare_stackup_reference
  • ferrite + fuse + inductor on the 24 V PDN
  • 4 schematic sheets (POWER / COMPUTE / IOEXP / FIELD)
  • I2C mux with *per-channel* nets (not one shared I2C fabric)
  • CH340C USB-UART, W25Q SPI flash, TXS0108, MCP4725, DS3231, 2N7002

Inspired by real open hardware (topology only — stock KiCad parts):

  • linorobot2 / ROS 2 base controllers — MCU + encoder + motor FET
  • OpenBot / Donkeycar compute hats — ESP companion + STM32 motion
  • industrial AGV CAN + RS-485 field buses

Architecture:
  24 V fused/filtered input + USB-C debug → 5 V / 3.3 V / 1.8 V
  ESP32-S3  — nav / logging, I2C mux, SPI flash, 595 daisy, USB via CH340
  STM32F103 — motion: CAN + RS-485 + opto DIs + FET driver
  ESP32-C3  — safety / heartbeat UART to STM32
  Analog island (ADS1115 + MCP4725) on AGND, net-tied to GND

Caller / stress test only — no compiler special-cases for AMR/CH340/PCA9548.
Offline pinouts + stock KiCad footprints → fabrication placeable.

Compile (logic + schematic sign-off)::

    OPENHAC_NO_NETWORK=1 OPENHAC_SCHEMATIC_MULTI_SHEET=1 python3 -m openhac.cli compile \\
      examples/complex_amr_compute_brick.py --name amr_compute_brick \\
      --production --compile-goal fabrication --skip-layout --schematic-signoff \\
      -o /tmp/openhac_amr

Place uses the complex-board packing knobs (see ``scripts/ci_validate_complex_boards.py``)::

    OPENHAC_NO_NETWORK=1 python3 scripts/ci_validate_complex_boards.py --place --only amr_compute_brick
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
from openhac.core.net import Bus, Net

from _offline_parts import (
    ADS1115,
    AMS1117_18,
    AMS1117_33,
    BMP280,
    C_0603,
    C_0805,
    CH340C,
    DS3231M,
    EEPROM_24LC256,
    ESP32_C3_WROOM02,
    ESP32_S3_WROOM1,
    FERRITE_0805,
    FUSE_0805,
    HC595,
    HEADER_1x04,
    HEADER_1x06,
    HEADER_1x08,
    L_0805,
    LED_0805,
    MAX3485,
    MCP4725,
    MPU6050,
    NETTIE_2,
    OPTO_SOIC4,
    PCA9548A,
    Q_2N7002,
    R_0805,
    STM32F103C8,
    TJA1051,
    TXS0108E,
    USB_C_HRO,
    W25Q32JVSS,
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
        self.dp, self.dm = Net("USB_DP"), Net("USB_DM")
        self.usb = self.add(_mk("USB_C", USB_C_HRO))
        for p in ("A4", "A9", "B4", "B9"):
            self.usb[p] += self.vbus
        for p in ("A1", "A12", "B1", "B12"):
            self.usb[p] += self.gnd
        self.usb["A6"] += self.dp
        self.usb["B7"] += self.dp
        self.usb["A7"] += self.dm
        self.usb["B6"] += self.dm
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


class PdnFilter24(Module):
    """Fuse → ferrite → inductor on the 24 V feed (PDN stress, not a buck model)."""

    def __init__(self) -> None:
        super().__init__("PdnFilter24")
        self.vin, self.vout, self.gnd = Net("VIN_24V"), Net("VIN_24V_FILT"), Net("GND")
        self.fuse = self.add(_mk("F_24V", FUSE_0805("F_24V")))
        self.fb = self.add(_mk("FB_24V", FERRITE_0805("FB_24V")))
        self.l = self.add(_mk("L_24V_10U", L_0805("L_24V_10U", "10uH")))
        self.c = self.add(_mk("C_24V_FILT_10U", C_0805("C_24V_FILT_10U", "10uF")))
        self.fuse[1] += self.vin
        self.fuse[2] += Net("VIN_24V_FUSED")
        self.fb[1] += Net("VIN_24V_FUSED")
        self.fb[2] += Net("VIN_24V_FB")
        self.l[1] += Net("VIN_24V_FB")
        self.l[2] += self.vout
        self.c[1] += self.vout
        self.c[2] += self.gnd
        self.pwr_in = self.declare_interface("pwr_24v", self.vin, self.gnd)
        self.pwr_out = self.declare_interface("pwr_24v_filt", self.vout, self.gnd)


class Ldo5VFrom24(Module):
    def __init__(self) -> None:
        super().__init__("Ldo5VFrom24")
        self.vin, self.v5, self.gnd = Net("VIN_24V_FILT"), Net("VBUS_5V"), Net("GND")
        self.reg = self.add(_mk("REG_5V_FROM_24", AMS1117_33))
        self.reg["VIN"] += self.vin
        self.reg["GND"] += self.gnd
        self.reg["VOUT"] += self.v5
        self.pwr_in = self.declare_interface("pwr_24v_filt", self.vin, self.gnd)
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


class Ldo1V8(Module):
    def __init__(self) -> None:
        super().__init__("Ldo1V8")
        self.vin, self.v1v8, self.gnd = Net("3V3"), Net("1V8"), Net("GND")
        self.ldo = self.add(_mk("AMS1117_1V8", AMS1117_18))
        self.ldo["VIN"] += self.vin
        self.ldo["GND"] += self.gnd
        self.ldo["VOUT"] += self.v1v8
        self.pwr_in = self.declare_interface("pwr_3v3", self.vin, self.gnd)
        self.pwr_out = self.declare_interface("pwr_1v8", self.v1v8, self.gnd)


class LdoCaps(Module):
    def __init__(self) -> None:
        super().__init__("LdoCaps")
        self.vin, self.v3v3, self.gnd = Net("VBUS_5V"), Net("3V3"), Net("GND")
        self.v1v8 = Net("1V8")
        self.cin = self.add(_mk("C_LDO_IN_10U", C_0805("C_LDO_IN_10U", "10uF")))
        self.cout_n = self.add(_mk("C_LDO_OUT_100N", C_0603("C_LDO_OUT_100N", "100nF")))
        self.cout_u = self.add(_mk("C_LDO_OUT_10U", C_0805("C_LDO_OUT_10U", "10uF")))
        self.c18n = self.add(_mk("C_1V8_100N", C_0603("C_1V8_100N", "100nF")))
        self.c18u = self.add(_mk("C_1V8_10U", C_0805("C_1V8_10U", "10uF")))
        self.cin[1] += self.vin
        self.cin[2] += self.gnd
        self.cout_n[1] += self.v3v3
        self.cout_n[2] += self.gnd
        self.cout_u[1] += self.v3v3
        self.cout_u[2] += self.gnd
        self.c18n[1] += self.v1v8
        self.c18n[2] += self.gnd
        self.c18u[1] += self.v1v8
        self.c18u[2] += self.gnd
        self.pwr_5 = self.declare_interface("pwr_5v", self.vin, self.gnd)
        self.pwr_3 = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)
        self.pwr_18 = self.declare_interface("pwr_1v8", self.v1v8, self.gnd)


class AgndTie(Module):
    """Single star-point net-tie between analog and digital ground."""

    def __init__(self) -> None:
        super().__init__("AgndTie")
        self.agnd, self.gnd = Net("AGND"), Net("GND")
        self.tie = self.add(_mk("NT_AGND", NETTIE_2))
        self.tie[1] += self.agnd
        self.tie[2] += self.gnd


# ---------------------------------------------------------------------------
# Compute
# ---------------------------------------------------------------------------


class Esp32S3Module(Module):
    def __init__(self) -> None:
        super().__init__("Esp32S3Module")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.en = Net("ESP_EN")
        self.usb_tx, self.usb_rx = Net("USB_UART_TX"), Net("USB_UART_RX")
        self.uart_tx, self.uart_rx = Net("MCU_BRIDGE_TX"), Net("MCU_BRIDGE_RX")
        self.i2c_sda, self.i2c_scl = Net("I2C_SDA"), Net("I2C_SCL")
        self.spi_mosi, self.spi_miso, self.spi_sck = Net("SPI_MOSI"), Net("SPI_MISO"), Net("SPI_SCK")
        self.flash_cs = Net("FLASH_CS")
        self.shift_rclk = Net("SHIFT_RCLK")
        self.enc = [Net(f"ENC_A{i}") for i in range(1, 5)]
        self.m = self.add(_mk("ESP32_S3", ESP32_S3_WROOM1))
        self.m[2] += self.v3v3
        self.m[1] += self.gnd
        self.m[40] += self.gnd
        self.m[41] += self.gnd
        self.m[3] += self.en
        self.m[37] += self.usb_tx  # TXD0 → CH340 RXD
        self.m[36] += self.usb_rx
        self.m[10] += self.uart_tx  # IO17 → STM32 RX
        self.m[14] += self.uart_rx  # IO20
        self.m[8] += self.i2c_sda  # IO15
        self.m[9] += self.i2c_scl  # IO16
        self.m[11] += self.spi_mosi  # IO18
        self.m[13] += self.spi_miso  # IO19
        self.m[12] += self.spi_sck  # IO8
        self.m[18] += self.flash_cs  # IO10
        self.m[22] += self.shift_rclk  # IO14
        self.m[17] += self.enc[0]  # IO9
        self.m[4] += self.enc[1]  # IO4
        self.m[5] += self.enc[2]  # IO5
        self.m[6] += self.enc[3]  # IO6
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


class Esp32C3Safety(Module):
    def __init__(self) -> None:
        super().__init__("Esp32C3Safety")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.en = Net("C3_EN")
        self.tx, self.rx = Net("C3_UART_TX"), Net("C3_UART_RX")
        self.hb = Net("C3_HEARTBEAT")
        self.m = self.add(_mk("ESP32_C3", ESP32_C3_WROOM02))
        self.m[1] += self.v3v3
        self.m[9] += self.gnd
        self.m[19] += self.gnd
        self.m[2] += self.en
        self.m[12] += self.tx  # IO21
        self.m[11] += self.rx  # IO20
        self.m[8] += self.hb  # IO9
        self.m.nc_unused_pins()
        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)


class C3LocalCaps(Module):
    def __init__(self) -> None:
        super().__init__("C3LocalCaps")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.c1 = self.add(_mk("C_C3_100N", C_0603("C_C3_100N", "100nF")))
        self.c2 = self.add(_mk("C_C3_10U", C_0805("C_C3_10U", "10uF")))
        self.ren = self.add(_mk("R_C3_EN_10K", R_0805("R_C3_EN_10K", "10k")))
        self.en = Net("C3_EN")
        self.c1[1] += self.v3v3
        self.c1[2] += self.gnd
        self.c2[1] += self.v3v3
        self.c2[2] += self.gnd
        self.ren[1] += self.v3v3
        self.ren[2] += self.en
        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)


class Lqfp48Core(Module):
    def __init__(self) -> None:
        super().__init__("Lqfp48Core")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.nrst = Net("STM_NRST")
        self.uart_tx, self.uart_rx = Net("MCU_BRIDGE_RX"), Net("MCU_BRIDGE_TX")
        self.c3_tx, self.c3_rx = Net("C3_UART_RX"), Net("C3_UART_TX")
        self.can_tx, self.can_rx = Net("CAN_TX"), Net("CAN_RX")
        self.rs485_di, self.rs485_ro = Net("RS485_DI"), Net("RS485_RO")
        self.rs485_de = Net("RS485_DE")
        self.di0, self.di1 = Net("OPTO_DI0"), Net("OPTO_DI1")
        self.xtal_in, self.xtal_out = Net("OSC_IN"), Net("OSC_OUT")
        self.fet_g = Net("MOT_FET_G")
        self.c3_hb = Net("C3_HEARTBEAT")
        self.m = self.add(_mk("STM32F103", STM32F103C8))
        for p in (24, 36, 48, 9):
            self.m[p] += self.v3v3
        for p in (23, 35, 47, 8):
            self.m[p] += self.gnd
        self.m[7] += self.nrst
        self.m[30] += self.uart_tx  # PA9
        self.m[31] += self.uart_rx  # PA10
        self.m[12] += self.c3_tx  # PA2 USART2 TX → C3 RX
        self.m[13] += self.c3_rx  # PA3
        self.m[21] += self.can_rx
        self.m[22] += self.can_tx
        self.m[26] += self.rs485_di
        self.m[27] += self.rs485_ro
        self.m[28] += self.rs485_de
        self.m[18] += self.di0
        self.m[19] += self.di1
        self.m[5] += self.xtal_in
        self.m[6] += self.xtal_out
        self.m[29] += self.fet_g  # PA8
        self.m[10] += self.c3_hb  # PA0
        self.m.nc_unused_pins()
        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)
        self.max_current_draw_ma = 80.0


class Stm32LocalCaps(Module):
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


class Ch340UsbUart(Module):
    """USB 2.0 FS transceiver. V3 is locally bypassed — not tied to the 3V3 LDO."""

    def __init__(self) -> None:
        super().__init__("Ch340UsbUart")
        self.v5, self.gnd = Net("VBUS_5V"), Net("GND")
        self.dp, self.dm = Net("USB_DP"), Net("USB_DM")
        self.tx, self.rx = Net("USB_UART_RX"), Net("USB_UART_TX")  # crossed vs ESP
        self.u = self.add(_mk("CH340C", CH340C))
        self.cv3 = self.add(_mk("C_CH340_V3_100N", C_0603("C_CH340_V3_100N", "100nF")))
        self.cvcc = self.add(_mk("C_CH340_VCC_100N", C_0603("C_CH340_VCC_100N", "100nF")))
        self.u[16] += self.v5
        self.u[1] += self.gnd
        self.u[5] += self.dp
        self.u[6] += self.dm
        self.u[2] += self.tx
        self.u[3] += self.rx
        self.cv3[1] += Net("CH340_V3")
        self.u[4] += Net("CH340_V3")
        self.cv3[2] += self.gnd
        self.cvcc[1] += self.v5
        self.cvcc[2] += self.gnd
        self.u.nc_unused_pins()
        self.pwr = self.declare_interface("pwr_5v", self.v5, self.gnd)


class SpiFlash(Module):
    def __init__(self) -> None:
        super().__init__("SpiFlash")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.mosi, self.miso, self.sck = Net("SPI_MOSI"), Net("SPI_MISO"), Net("SPI_SCK")
        self.cs = Net("FLASH_CS")
        self.u = self.add(_mk("W25Q32", W25Q32JVSS))
        self.c = self.add(_mk("C_FLASH_100N", C_0603("C_FLASH_100N", "100nF")))
        self.u[8] += self.v3v3
        self.u[4] += self.gnd
        self.u[1] += self.cs
        self.u[6] += self.sck
        self.u[5] += self.mosi
        self.u[2] += self.miso
        self.u[3] += self.v3v3  # WP
        self.u[7] += self.v3v3  # HOLD
        self.c[1] += self.v3v3
        self.c[2] += self.gnd
        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)


# ---------------------------------------------------------------------------
# I/O expansion
# ---------------------------------------------------------------------------


class ShiftDaisy(Module):
    """Two 74HC595s daisy-chained onto a Bus of 16 LED/solenoid bits."""

    def __init__(self) -> None:
        super().__init__("ShiftDaisy")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.ser, self.sck, self.rclk = Net("SPI_MOSI"), Net("SPI_SCK"), Net("SHIFT_RCLK")
        self.q = Bus("SHIFT_Q", width=16)
        self.u1 = self.add(_mk("U_595_A", HC595))
        self.u2 = self.add(_mk("U_595_B", HC595))
        self.h0 = self.add(_mk("HDR_SHIFT_A", HEADER_1x08))
        self.h1 = self.add(_mk("HDR_SHIFT_B", HEADER_1x08))
        daisy = Net("SHIFT_DAISY")
        for u in (self.u1, self.u2):
            u[16] += self.v3v3
            u[8] += self.gnd
            u[11] += self.sck
            u[12] += self.rclk
            u[10] += self.v3v3  # ~SRCLR
            u[13] += self.gnd  # ~OE
        self.u1[14] += self.ser
        self.u1[9] += daisy
        self.u2[14] += daisy
        # QA,QB,...,QH = pads 15,1,2,3,4,5,6,7
        order = (15, 1, 2, 3, 4, 5, 6, 7)
        for i, pad in enumerate(order):
            self.u1[pad] += self.q[i]
            self.u2[pad] += self.q[i + 8]
            self.h0[i + 1] += self.q[i]
            self.h1[i + 1] += self.q[i + 8]
        self.u2.nc_unused_pins()  # QH' unused on last stage
        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)


class I2cMux(Module):
    def __init__(self) -> None:
        super().__init__("I2cMux")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.sda, self.scl = Net("I2C_SDA"), Net("I2C_SCL")
        self.ch_sda = [Net(f"I2C{i}_SDA") for i in range(6)]
        self.ch_scl = [Net(f"I2C{i}_SCL") for i in range(6)]
        self.u = self.add(_mk("PCA9548A", PCA9548A))
        self.c = self.add(_mk("C_MUX_100N", C_0603("C_MUX_100N", "100nF")))
        self.u[24] += self.v3v3
        self.u[12] += self.gnd
        self.u[23] += self.sda
        self.u[22] += self.scl
        self.u[3] += self.v3v3  # ~RESET
        self.u[1] += self.gnd  # A0
        self.u[2] += self.gnd
        self.u[21] += self.gnd
        # SD0/SC0 … SD5/SC5 (ch 6–7 left NC)
        sd_sc = ((4, 5), (6, 7), (8, 9), (10, 11), (13, 14), (15, 16))
        for i, (sd, sc) in enumerate(sd_sc):
            self.u[sd] += self.ch_sda[i]
            self.u[sc] += self.ch_scl[i]
        self.c[1] += self.v3v3
        self.c[2] += self.gnd
        self.u.nc_unused_pins()
        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)


class I2cPullups(Module):
    def __init__(self, name: str, sda: str, scl: str) -> None:
        super().__init__(name)
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.sda, self.scl = Net(sda), Net(scl)
        tag = name.replace("I2cPullups", "PU")
        self.rs = self.add(_mk(f"R_{tag}_SDA", R_0805(f"R_{tag}_SDA", "4.7k")))
        self.rc = self.add(_mk(f"R_{tag}_SCL", R_0805(f"R_{tag}_SCL", "4.7k")))
        self.rs[1] += self.sda
        self.rs[2] += self.v3v3
        self.rc[1] += self.scl
        self.rc[2] += self.v3v3
        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)


class TxsEncoder(Module):
    def __init__(self) -> None:
        super().__init__("TxsEncoder")
        self.v3v3, self.v5, self.gnd = Net("3V3"), Net("VBUS_5V"), Net("GND")
        self.a = [Net(f"ENC_A{i}") for i in range(1, 5)]
        self.b = [Net(f"ENC_B{i}") for i in range(1, 5)]
        self.u = self.add(_mk("TXS0108", TXS0108E))
        self.ca = self.add(_mk("C_TXS_A_100N", C_0603("C_TXS_A_100N", "100nF")))
        self.cb = self.add(_mk("C_TXS_B_100N", C_0603("C_TXS_B_100N", "100nF")))
        self.h = self.add(_mk("HDR_ENC", HEADER_1x08))
        self.u[2] += self.v3v3
        self.u[19] += self.v5
        self.u[11] += self.gnd
        self.u[10] += self.v3v3  # OE
        a_pads = (1, 3, 4, 5)
        b_pads = (20, 18, 17, 16)
        for net, pad in zip(self.a, a_pads):
            self.u[pad] += net
        for net, pad in zip(self.b, b_pads):
            self.u[pad] += net
        self.h[1] += self.b[0]
        self.h[2] += self.b[1]
        self.h[3] += self.b[2]
        self.h[4] += self.b[3]
        self.h[5] += self.v5
        self.h[6] += self.gnd
        self.h[7] += self.gnd
        self.h[8] += self.gnd
        self.ca[1] += self.v3v3
        self.ca[2] += self.gnd
        self.cb[1] += self.v5
        self.cb[2] += self.gnd
        self.u.nc_unused_pins()
        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)
        self.pwr_5 = self.declare_interface("pwr_5v", self.v5, self.gnd)


class MotorFet(Module):
    def __init__(self) -> None:
        super().__init__("MotorFet")
        self.gnd = Net("GND")
        self.v5 = Net("VBUS_5V")
        self.gate = Net("MOT_FET_G")
        self.drain = Net("MOT_DRAIN")
        self.q = self.add(_mk("Q_MOT", Q_2N7002))
        self.rg = self.add(_mk("R_FET_G_100", R_0805("R_FET_G_100", "100")))
        self.h = self.add(_mk("HDR_MOT", HEADER_1x04))
        self.q[1] += self.gate
        self.q[2] += self.gnd
        self.q[3] += self.drain
        self.rg[1] += self.gate
        self.rg[2] += self.gnd
        self.h[1] += self.drain
        self.h[2] += self.gnd
        self.h[3] += self.v5
        self.h[4] += self.gnd


# ---------------------------------------------------------------------------
# Field buses / analog island / sensors
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
        self.phy[8] += self.gnd
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
        self.phy[2] += self.de
        self.phy[3] += self.de
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


class OptoInput(Module):
    def __init__(self, name: str, net: str, tag: str) -> None:
        super().__init__(name)
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.out = Net(net)
        self.field_p, self.field_n = Net(f"DI{tag}_FIELD_P"), Net(f"DI{tag}_FIELD_N")
        self.u = self.add(_mk(f"OPTO_{tag}", OPTO_SOIC4))
        self.rled = self.add(_mk(f"R_OPTO_{tag}_LED", R_0805(f"R_OPTO_{tag}_LED", "1k")))
        self.rpu = self.add(_mk(f"R_OPTO_{tag}_PU", R_0805(f"R_OPTO_{tag}_PU", "10k")))
        self.rled[1] += self.field_p
        self.rled[2] += self.u[1]
        self.u[2] += self.field_n
        self.u[3] += self.gnd
        self.u[4] += self.out
        self.rpu[1] += self.v3v3
        self.rpu[2] += self.out
        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)


class FieldDiHeader(Module):
    def __init__(self) -> None:
        super().__init__("FieldDiHeader")
        self.h = self.add(_mk("HDR_DI", HEADER_1x06))
        self.h[1] += Net("DI0_FIELD_P")
        self.h[2] += Net("DI0_FIELD_N")
        self.h[3] += Net("DI1_FIELD_P")
        self.h[4] += Net("DI1_FIELD_N")
        self.h[5] += Net("GND")
        self.h[6] += Net("GND")


class BaroChip(Module):
    def __init__(self) -> None:
        super().__init__("BaroChip")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.sda, self.scl = Net("I2C0_SDA"), Net("I2C0_SCL")
        self.m = self.add(_mk("BMP280", BMP280))
        self.m[8] += self.v3v3
        self.m[6] += self.v3v3
        self.m[1] += self.gnd
        self.m[7] += self.gnd
        self.m[3] += self.sda
        self.m[4] += self.scl
        self.m.nc_unused_pins()
        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)


class ImuChip(Module):
    def __init__(self) -> None:
        super().__init__("ImuChip")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.sda, self.scl = Net("I2C1_SDA"), Net("I2C1_SCL")
        self.m = self.add(_mk("MPU6050", MPU6050))
        self.m[13] += self.v3v3
        self.m[8] += self.v3v3
        self.m[18] += self.gnd
        self.m[24] += self.sda
        self.m[23] += self.scl
        self.m[9] += self.gnd
        self.m.nc_unused_pins()
        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)


class EepromChip(Module):
    def __init__(self) -> None:
        super().__init__("EepromChip")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.sda, self.scl = Net("I2C2_SDA"), Net("I2C2_SCL")
        self.m = self.add(_mk("EEPROM", EEPROM_24LC256))
        self.m[8] += self.v3v3
        self.m[4] += self.gnd
        self.m[5] += self.sda
        self.m[6] += self.scl
        self.m[1] += self.gnd
        self.m[2] += self.gnd
        self.m[3] += self.gnd
        self.m[7] += self.gnd
        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)


class DacChip(Module):
    def __init__(self) -> None:
        super().__init__("DacChip")
        self.v3v3, self.agnd = Net("3V3"), Net("AGND")
        self.sda, self.scl = Net("I2C3_SDA"), Net("I2C3_SCL")
        self.vout = Net("DAC_VOUT")
        self.m = self.add(_mk("MCP4725", MCP4725))
        self.h = self.add(_mk("HDR_DAC", HEADER_1x04))
        self.m[3] += self.v3v3
        self.m[2] += self.agnd
        self.m[4] += self.sda
        self.m[5] += self.scl
        self.m[6] += self.agnd
        self.m[1] += self.vout
        self.h[1] += self.vout
        self.h[2] += self.agnd
        self.h[3] += self.v3v3
        self.h[4] += self.agnd
        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.agnd)


class RtcChip(Module):
    def __init__(self) -> None:
        super().__init__("RtcChip")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.sda, self.scl = Net("I2C4_SDA"), Net("I2C4_SCL")
        self.m = self.add(_mk("DS3231M", DS3231M))
        self.m[2] += self.v3v3
        self.m[14] += self.v3v3
        self.m[15] += self.sda
        self.m[16] += self.scl
        for p in (5, 6, 7, 8, 9, 10, 11, 12, 13):
            self.m[p] += self.gnd
        self.m.nc_unused_pins()
        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)


class AdcChip(Module):
    def __init__(self) -> None:
        super().__init__("AdcChip")
        self.v3v3, self.agnd = Net("3V3"), Net("AGND")
        self.sda, self.scl = Net("I2C5_SDA"), Net("I2C5_SCL")
        self.ain = [Net(f"AIN{i}") for i in range(4)]
        self.m = self.add(_mk("ADS1115", ADS1115))
        self.h = self.add(_mk("HDR_AIN", HEADER_1x08))
        self.m[10] += self.v3v3
        self.m[3] += self.agnd
        self.m[8] += self.sda
        self.m[9] += self.scl
        self.m[1] += self.agnd
        for i, p in enumerate((4, 5, 6, 7)):
            self.m[p] += self.ain[i]
        self.h[1] += self.ain[0]
        self.h[2] += self.ain[1]
        self.h[3] += self.ain[2]
        self.h[4] += self.ain[3]
        self.h[5] += self.agnd
        self.h[6] += self.agnd
        self.h[7] += self.v3v3
        self.h[8] += self.agnd
        self.m.nc_unused_pins()
        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.agnd)


class StatusLeds(Module):
    def __init__(self) -> None:
        super().__init__("StatusLeds")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        for tag, netn in (("PWR", "3V3"), ("ESP", "ESP_EN"), ("STM", "STM_NRST")):
            led = self.add(_mk(f"LED_{tag}", LED_0805(f"LED_{tag}")))
            r = self.add(_mk(f"R_LED_{tag}", R_0805(f"R_LED_{tag}", "1k")))
            r[1] += Net(netn) if netn != "3V3" else self.v3v3
            r[2] += Net(f"LED_{tag}_A")
            led[2] += Net(f"LED_{tag}_A")
            led[1] += self.gnd
        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)


class DebugHeader(Module):
    def __init__(self) -> None:
        super().__init__("DebugHeader")
        self.v3v3, self.gnd = Net("3V3"), Net("GND")
        self.h = self.add(_mk("HDR_DBG", HEADER_1x08))
        self.h[1] += self.v3v3
        self.h[2] += self.gnd
        self.h[3] += Net("USB_UART_TX")
        self.h[4] += Net("USB_UART_RX")
        self.h[5] += Net("I2C_SDA")
        self.h[6] += Net("I2C_SCL")
        self.h[7] += Net("SPI_SCK")
        self.h[8] += self.gnd
        self.pwr = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)


# ---------------------------------------------------------------------------
# Board assembly
# ---------------------------------------------------------------------------


def build_board() -> Board:
    board = Board(size_mm=None, layers=6, compile_goal="fabrication", strict=False)

    usb = UsbJack()
    cc = UsbCcStraps()
    vin24 = Industrial24VIn()
    pdn = PdnFilter24()
    buck5 = Ldo5VFrom24()
    ldo = Ldo3V3()
    ldo18 = Ldo1V8()
    ldoc = LdoCaps()
    agnd = AgndTie()

    esp = Esp32S3Module()
    espc = EspLocalCaps()
    c3 = Esp32C3Safety()
    c3c = C3LocalCaps()
    stm = Lqfp48Core()
    stmc = Stm32LocalCaps()
    xtal = StmCrystal()
    ch340 = Ch340UsbUart()
    flash = SpiFlash()

    sh = ShiftDaisy()
    mux = I2cMux()
    pu = I2cPullups("I2cPullupsTrunk", "I2C_SDA", "I2C_SCL")
    pu0 = I2cPullups("I2cPullups0", "I2C0_SDA", "I2C0_SCL")
    pu1 = I2cPullups("I2cPullups1", "I2C1_SDA", "I2C1_SCL")
    pu2 = I2cPullups("I2cPullups2", "I2C2_SDA", "I2C2_SCL")
    pu3 = I2cPullups("I2cPullups3", "I2C3_SDA", "I2C3_SCL")
    pu4 = I2cPullups("I2cPullups4", "I2C4_SDA", "I2C4_SCL")
    pu5 = I2cPullups("I2cPullups5", "I2C5_SDA", "I2C5_SCL")
    txs = TxsEncoder()
    fet = MotorFet()

    can = CanPhy()
    cant = CanTerm()
    canh = CanHeader()
    rs = Rs485Phy()
    rst = Rs485Term()
    rsh = Rs485Header()
    o0 = OptoInput("OptoInput0", "OPTO_DI0", "0")
    o1 = OptoInput("OptoInput1", "OPTO_DI1", "1")
    dih = FieldDiHeader()
    baro = BaroChip()
    imu = ImuChip()
    ee = EepromChip()
    dac = DacChip()
    rtc = RtcChip()
    adc = AdcChip()
    leds = StatusLeds()
    dbg = DebugHeader()

    modules = (
        usb, cc, vin24, pdn, buck5, ldo, ldo18, ldoc, agnd,
        esp, espc, c3, c3c, stm, stmc, xtal, ch340, flash,
        sh, mux, pu, pu0, pu1, pu2, pu3, pu4, pu5, txs, fet,
        can, cant, canh, rs, rst, rsh, o0, o1, dih,
        baro, imu, ee, dac, rtc, adc, leds, dbg,
    )
    for m in modules:
        board.add_module(m)

    board.set_schematic_sheet(
        "POWER", usb, cc, vin24, pdn, buck5, ldo, ldo18, ldoc, agnd,
    )
    board.set_schematic_sheet(
        "COMPUTE", esp, espc, c3, c3c, stm, stmc, xtal, ch340, flash, leds, dbg,
    )
    board.set_schematic_sheet("IOEXP", sh, mux, pu, pu0, pu1, pu2, pu3, pu4, pu5, txs, fet)
    board.set_schematic_sheet(
        "FIELD",
        can, cant, canh, rs, rst, rsh, o0, o1, dih,
        baro, imu, ee, dac, rtc, adc,
    )

    usb.usb["A5"] += cc.cc1
    usb.usb["B5"] += cc.cc2

    board.connect(vin24.pwr, pdn.pwr_in)
    board.connect(pdn.pwr_out, buck5.pwr_in)
    board.connect(usb.pwr, cc.pwr)
    board.connect(usb.pwr, buck5.pwr_out)
    board.connect(usb.pwr, ldo.pwr_in)
    board.connect(usb.pwr, ldoc.pwr_5)
    board.connect(usb.pwr, ch340.pwr)
    board.connect(usb.pwr, txs.pwr_5)
    board.connect(ldo.pwr_out, ldoc.pwr_3)
    board.connect(ldo.pwr_out, ldo18.pwr_in)
    board.connect(ldo18.pwr_out, ldoc.pwr_18)

    for m in (
        esp, espc, c3, c3c, stm, stmc, flash, sh, mux,
        pu, pu0, pu1, pu2, pu3, pu4, pu5, txs,
        can, rs, rst, o0, o1, baro, imu, ee, rtc, leds, dbg,
    ):
        board.connect(ldo.pwr_out, m.pwr)
    # DAC / ADC sit on AGND — 3V3 merges by net name; do not zip AGND into GND.

    board.declare_power_rail("VBUS_5V", usb.vbus)
    board.declare_power_rail("VIN_24V", vin24.v24)
    board.declare_power_rail("3V3", ldo.v3v3)
    board.declare_power_rail("1V8", ldo18.v1v8)
    board.declare_power_rail("GND", usb.gnd)
    board.declare_power_rail("AGND", agnd.agnd)
    board.declare_rail_conversion("VIN_24V", "VBUS_5V", efficiency=0.90)
    board.declare_rail_conversion("VBUS_5V", "3V3", efficiency=0.85)
    board.declare_rail_conversion("3V3", "1V8", efficiency=0.85)

    board.declare_net_role(agnd.agnd, "analog_ground")
    board.declare_net_role(usb.gnd, "digital_ground")
    board.declare_net_merge_hint(agnd.agnd, usb.gnd, via="star_point")

    board.route_differential_pair(usb.dp, usb.dm, target_impedance_ohms=90.0)
    board.declare_length_match_intent("usb2_fs_dp_dm", usb.dp, usb.dm, tolerance_mm=0.5)
    board.declare_stackup_reference(
        Path(__file__).resolve().parents[1] / "docs" / "stackup_template.yaml",
        role="si_documentation",
        documentation_note="6-layer AMR brick; YAML is the 4-layer SI template (edit for fab).",
    )

    board.constrain_distance_min(usb, esp, min_distance_mm=5.0)
    board.constrain_distance_min(esp, stm, min_distance_mm=4.0)
    board.constrain_distance_min(esp, c3, min_distance_mm=6.0)
    board.constrain_distance_min(can, rs, min_distance_mm=4.0)
    board.constrain_distance_min(adc, stm, min_distance_mm=8.0)

    espc.cluster_with(esp)
    c3c.cluster_with(c3)
    stmc.cluster_with(stm)
    xtal.cluster_with(stm)
    ldoc.cluster_with(ldo)
    ldo18.cluster_with(ldo)
    cc.cluster_with(usb)
    ch340.cluster_with(usb)
    flash.cluster_with(esp)
    cant.cluster_with(can)
    rst.cluster_with(rs)
    pdn.cluster_with(vin24)
    buck5.cluster_with(pdn)
    pu.cluster_with(mux)
    pu0.cluster_with(baro)
    pu1.cluster_with(imu)
    pu2.cluster_with(ee)
    pu3.cluster_with(dac)
    pu4.cluster_with(rtc)
    pu5.cluster_with(adc)
    agnd.cluster_with(adc)
    fet.cluster_with(stm)
    leds.cluster_with(esp)
    dbg.cluster_with(esp)

    board.declare_copper_pour_intent(usb.gnd, layer="F.Cu", purpose="ground")
    board.declare_copper_pour_intent(usb.gnd, layer="B.Cu", purpose="ground")
    board.declare_copper_pour_intent(usb.gnd, layer="In1.Cu", purpose="ground_plane")
    board.declare_copper_pour_intent(ldo.v3v3, layer="In2.Cu", purpose="power_plane")
    board.declare_copper_pour_intent(usb.gnd, layer="In3.Cu", purpose="ground_plane")
    board.declare_copper_pour_intent(ldo18.v1v8, layer="In4.Cu", purpose="power_plane")

    board.set_net_current(usb.vbus, 1.5, note="USB-C + local 5V rail")
    board.set_net_current(ldo.v3v3, 1.0, note="shared 3V3 digital")
    board.set_net_current(ldo18.v1v8, 0.2, note="1.8V analog/helper")
    board.set_net_current(vin24.v24, 0.8, note="industrial 24V input")
    board.set_net_current(usb.gnd, 2.0, note="return")

    return board


board = build_board()

if __name__ == "__main__":
    n = sum(len(m.components) for m in board._get_all_modules())
    nmod = len(board._get_all_modules())
    print(f"AMR / AGV compute brick: {n} components across {nmod} modules (4 schematic sheets, 6 layers)")
    print("Stresses: Bus, USB diff pair, AGND net-tie, 6-layer pours, I2C mux channels, triple MCU")
