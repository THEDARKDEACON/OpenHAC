"""
rp2040_sensor_node.py — Raspberry Pi RP2040 Multi-Sensor IoT Edge Node.

Demonstrates:
  1. OpenHaC v2 Module Hierarchy & Typed Interface Protocols
  2. Zero-Touch JIT CAD downloads (RP2040, Winbond Flash, USB-C, AMS1117, BMP280)
  3. Authentic Manufacturer Pinout replication (pins addressed by real datasheet names)
  4. Hierarchical KiCad 9 Multi-Sheet Schematics (Root sheet + Subsystem sheets)
"""

from __future__ import annotations

import sys
from pathlib import Path

_EX = Path(__file__).resolve().parent
if str(_EX) not in sys.path:
    sys.path.insert(0, str(_EX))

from openhac.core.base import Component, Module
from openhac.core.board import Board
from openhac.core.circuit import reset_default_circuit
from openhac.core.net import Net


class PowerSupplyModule(Module):
    """Subsystem 1: USB-C power delivery, filtering, and 3.3V LDO regulation."""

    def __init__(self) -> None:
        super().__init__("PowerSupply")
        self.vbus = Net("VBUS_5V")
        self.v3v3 = Net("3V3")
        self.gnd = Net("GND")
        self.usb_dp = Net("USB_D_P")
        self.usb_dm = Net("USB_D_N")

        # Zero-touch JIT components
        self.usb = self.add(Component("C165948", refdes="J1"))    # USB-C 16-pin Receptacle
        self.ldo = self.add(Component("C6186", refdes="U1"))      # AMS1117-3.3 Linear Regulator
        self.c_in = self.add(Component("C15849", refdes="C1"))    # 10uF 0805 input filter
        self.c_out = self.add(Component("C15849", refdes="C2"))   # 10uF 0805 output filter

        # Connect USB-C power & shield
        self.usb["A4B9"] += self.vbus
        self.usb["B4A9"] += self.vbus
        self.usb["A1B12"] += self.gnd
        self.usb["B1A12"] += self.gnd
        for p in ("1", "2", "3", "4"):
            self.usb[p] += self.gnd

        # Connect USB differential data
        self.usb["DP1"] += self.usb_dp
        self.usb["DP2"] += self.usb_dp
        self.usb["DN1"] += self.usb_dm
        self.usb["DN2"] += self.usb_dm

        # Connect LDO Regulator
        self.ldo["VIN"] += self.vbus
        self.ldo["VOUT"] += self.v3v3
        self.ldo["4"] += self.v3v3
        self.ldo["1"] += self.gnd

        # Filtering caps
        self.c_in["1"] += self.vbus
        self.c_in["2"] += self.gnd
        self.c_out["1"] += self.v3v3
        self.c_out["2"] += self.gnd

        # Export subsystem interfaces
        self.pwr_out = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)
        self.usb_if = self.declare_interface("usb_data", self.usb_dp, self.usb_dm)

        self.nc_unused_pins()


class RP2040ComputeModule(Module):
    """Subsystem 2: RP2040 MCU Core, 16MB QSPI NOR Flash, and Core Power."""

    def __init__(self) -> None:
        super().__init__("RP2040Compute")
        self.v3v3 = Net("3V3")
        self.gnd = Net("GND")
        self.v1v1 = Net("1V1_CORE")
        self.usb_dp = Net("USB_D_P")
        self.usb_dm = Net("USB_D_N")
        self.sda = Net("I2C_SDA")
        self.scl = Net("I2C_SCL")
        self.led = Net("STATUS_LED")

        # Zero-touch JIT components with authentic manufacturer pinouts
        self.mcu = self.add(Component("C2040", refdes="U2"))      # Raspberry Pi RP2040 Dual Cortex-M0+
        self.flash = self.add(Component("C97521", refdes="U3"))   # Winbond W25Q128JV 16MB SPI Flash

        # Connect Power & Internal 1.1V Core Regulator
        self.mcu["VREG_IN"] += self.v3v3
        self.mcu["VREG_VOUT"] += self.v1v1
        for p in (23, 50):  # DVDD digital core power
            self.mcu[p] += self.v1v1
        for p in (1, 10, 22, 33, 42, 49):  # IOVDD I/O pad supply
            self.mcu[p] += self.v3v3
        self.mcu["ADC_AVDD"] += self.v3v3
        self.mcu["USB_VDD"] += self.v3v3
        self.mcu[57] += self.gnd  # Exposed Thermal Pad

        # Connect High-Speed QSPI Flash Memory
        self.flash["VCC"] += self.v3v3
        self.flash["GND"] += self.gnd
        self.mcu["QSPI_SS"] += self.flash["CS#"]
        self.mcu["QSPI_SCLK"] += self.flash["CLK"]
        self.mcu["QSPI_SD0"] += self.flash["DI"]
        self.mcu["QSPI_SD1"] += self.flash["DO"]
        self.mcu["QSPI_SD2"] += self.flash["IO2"]
        self.mcu["QSPI_SD3"] += self.flash["IO3"]

        # Native Full-Speed USB Controller
        self.mcu["USB_DP"] += self.usb_dp
        self.mcu["USB_DM"] += self.usb_dm

        # Peripherals: I2C Master & User Status LED
        self.mcu["GPIO4"] += self.sda
        self.mcu["GPIO5"] += self.scl
        self.mcu["GPIO25"] += self.led

        # Export subsystem interfaces
        self.pwr_in = self.declare_interface("pwr_in", self.v3v3, self.gnd)
        self.usb_in = self.declare_interface("usb_in", self.usb_dp, self.usb_dm)
        self.i2c = self.declare_interface("i2c", self.sda, self.scl)
        self.led_out = self.declare_interface("led_out", self.led)

        self.nc_unused_pins()


class SensorFrontendModule(Module):
    """Subsystem 3: Precision Environmental Sensor & Indicator LED."""

    def __init__(self) -> None:
        super().__init__("SensorFrontend")
        self.v3v3 = Net("3V3")
        self.gnd = Net("GND")
        self.sda = Net("I2C_SDA")
        self.scl = Net("I2C_SCL")
        self.led = Net("STATUS_LED")

        # Zero-touch JIT components
        self.bmp = self.add(Component("C92489", refdes="U4"))     # Bosch BMP280 Pressure/Temp Sensor
        self.led_dev = self.add(Component("C2286", refdes="D1")) # 0805 User LED
        self.r_led = self.add(Component("C21190", refdes="R1"))   # Current-limiting resistor

        # BMP280 Digital Sensor Connections
        self.bmp["VDD"] += self.v3v3
        self.bmp["VDDIO"] += self.v3v3
        self.bmp["GND"] += self.gnd
        self.bmp["7"] += self.gnd
        self.bmp["CSB"] += self.v3v3  # Pull CSB high to activate I2C mode
        self.bmp["SDO"] += self.gnd   # Pull SDO low for 0x76 I2C address
        self.bmp["SDI"] += self.sda   # I2C Serial Data
        self.bmp["SCK"] += self.scl   # I2C Serial Clock

        # Status Indicator LED
        self.r_led["1"] += self.led
        self.r_led["2"] += self.led_dev["A"]
        self.led_dev["K"] += self.gnd

        # Export subsystem interfaces
        self.pwr_in = self.declare_interface("pwr_in", self.v3v3, self.gnd)
        self.i2c_in = self.declare_interface("i2c_in", self.sda, self.scl)
        self.led_in = self.declare_interface("led_in", self.led)

        self.nc_unused_pins()


def build_board() -> Board:
    """Instantiate and interconnect the complete IoT Edge Node board."""
    reset_default_circuit()

    board = Board(
        size_mm=(65.0, 45.0),
        layers=2,
        compile_goal="handoff",
        declared_supply_voltages_v={"VBUS_5V": 5.0, "3V3": 3.3, "1V1_CORE": 1.1},
    )

    # 1. Instantiate modules
    pwr = PowerSupplyModule()
    mcu = RP2040ComputeModule()
    sensor = SensorFrontendModule()

    board.add_module(pwr)
    board.add_module(mcu)
    board.add_module(sensor)

    # 2. Interconnect subsystems via high-level interfaces
    board.connect(pwr.pwr_out, mcu.pwr_in)
    board.connect(pwr.pwr_out, sensor.pwr_in)
    board.connect(pwr.usb_if, mcu.usb_in)
    board.connect(mcu.i2c, sensor.i2c_in)
    board.connect(mcu.led_out, sensor.led_in)

    # 3. Supply and routing intents
    board.declare_power_rail("VBUS_5V", pwr.vbus)
    board.declare_power_rail("3V3", pwr.v3v3)
    board.declare_power_rail("GND", pwr.gnd)
    board.declare_rail_conversion("VBUS_5V", "3V3", efficiency=0.85)

    board.declare_copper_pour_intent(pwr.gnd, layer="F.Cu", purpose="ground")
    board.declare_copper_pour_intent(pwr.gnd, layer="B.Cu", purpose="ground")

    return board


board = build_board()

if __name__ == "__main__":
    from openhac.compiler.compile_pipeline import compile_board
    compile_board(board, project_name="rp2040_sensor_node", output_dir=Path("./build/rp2040_node"))
