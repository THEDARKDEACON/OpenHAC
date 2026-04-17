"""
flight_controller_jlc_only.py - 100% JLCPCB-Sourced Components Only

This flight controller design uses ONLY real components from JLCPCB/LCSC database.
No synthetic parts, no manual footprint assignments - all data comes from vendor DB.

Design: STM32F4-based flight controller with IMU, Baro, Mag, CAN, USB-C
All components sourced from JLCPCB with real SKUs (Cxxxxx numbers).

To sync components before compiling:
    python -m openhac.database.sync_jlc

Then compile:
    python -m openhac compile flight_controller_jlc_only.py --name fc_jlc
"""

from __future__ import annotations

from openhac.core.net import Net
from openhac.core import Board
from openhac.core.base import Module, Component


class PowerModule(Module):
    """Power management using only JLCPCB-sourced components."""
    
    def __init__(self):
        super().__init__("PowerModule")
        
        self.vbat = Net("VBAT")
        self.gnd = Net("GND")
        self.v5 = Net("5V")
        self.v3v3 = Net("3V3")
        
        # All components from JLCPCB database only
        # TPS63001 buck-boost converter - C132150
        self.buck = self.add(Component("BUCK_TPS63001DRCR"))

        # 2.2uH inductor - C167240
        self.l_buck = self.add(Component("INDUCTOR_2R2_2520"))

        # Input caps (using 0805 instead of 1206 as seeded)
        self.cin_10u = self.add(Component("C_10UF_0805"))  # C440198
        self.cin_100n = self.add(Component("C_100NF_0603"))  # C14663

        # 5V output caps
        self.cout5v_22u = self.add(Component("C_22UF_0805"))  # C59461
        self.cout5v_100n = self.add(Component("C_100NF_0603"))  # C14663

        # LDL1117 LDO 3.3V - C130026
        self.ldo = self.add(Component("LDO_LDL1117S33R"))

        # LDO caps
        self.cldo_in = self.add(Component("C_10UF_0805"))  # C440198
        self.cldo_out_10u = self.add(Component("C_10UF_0805"))  # C440198
        self.cldo_out_100n = self.add(Component("C_100NF_0603"))  # C14663

        # Feedback resistors (need to add to seed for exact values)
        self.r_fb1 = self.add(Component("R_100K_0603"))  # C25804 - exact 100k for feedback
        self.r_fb2 = self.add(Component("R_32K4_0603"))  # C25818 - exact 32.4k for 3.3V FB
        
        # Power LED green - C125093
        self.led_pwr = self.add(Component("LED_GREEN_0603"))
        self.r_led = self.add(Component("R_1K_0603"))  # C21190 - LED current limit
        
        # Wiring
        vbat_fused = Net("VBAT_FUSED")
        
        self.cin_10u['1'] += vbat_fused
        self.cin_10u['2'] += self.gnd
        self.cin_100n['1'] += vbat_fused
        self.cin_100n['2'] += self.gnd
        
        self.buck['VIN'] += vbat_fused
        self.buck['GND'] += self.gnd
        self.buck['SW'] += self.l_buck['1']
        self.l_buck['2'] += self.v5
        self.buck['FB'] += Net("FB_5V")
        
        self.r_fb1['1'] += self.v5
        self.r_fb1['2'] += Net("FB_5V")
        self.r_fb2['1'] += Net("FB_5V")
        self.r_fb2['2'] += self.gnd
        
        self.cout5v_22u['1'] += self.v5
        self.cout5v_22u['2'] += self.gnd
        self.cout5v_100n['1'] += self.v5
        self.cout5v_100n['2'] += self.gnd
        
        self.cldo_in['1'] += self.v5
        self.cldo_in['2'] += self.gnd
        self.ldo['IN'] += self.v5
        self.ldo['GND'] += self.gnd
        self.ldo['OUT'] += self.v3v3
        
        self.cldo_out_10u['1'] += self.v3v3
        self.cldo_out_10u['2'] += self.gnd
        self.cldo_out_100n['1'] += self.v3v3
        self.cldo_out_100n['2'] += self.gnd
        
        self.r_led['1'] += self.v5
        self.r_led['2'] += Net("LED_PWR_NODE")
        self.led_pwr['A'] += Net("LED_PWR_NODE")
        self.led_pwr['K'] += self.gnd
        
        self.source_current_max_ma = {"5V": 2000, "3V3": 800}
        
        self.pwr_5v = self.declare_interface("pwr_5v", self.v5, self.gnd)
        self.pwr_3v3 = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)


class MCUModule(Module):
    """STM32F405 MCU module - all parts from JLCPCB."""
    
    def __init__(self):
        super().__init__("MCUModule")
        
        self.v3v3 = Net("3V3")
        self.gnd = Net("GND")
        
        # STM32F405RGT6 - Main MCU - C7862
        self.mcu = self.add(Component("MCU_STM32F405RGT6"))
        
        # 8MHz Crystal for HSE - C15629
        self.xtal_8m = self.add(Component("XTAL_8MHZ_3225"))

        # Load caps 18pF - C107274
        self.c_xtal1 = self.add(Component("C_18PF_0402"))
        self.c_xtal2 = self.add(Component("C_18PF_0402"))

        # 32.768kHz RTC crystal - C70501
        self.xtal_32k = self.add(Component("XTAL_32K768_3215"))

        # Load caps 12pF - C107270
        self.c_32k1 = self.add(Component("C_12PF_0402"))
        self.c_32k2 = self.add(Component("C_12PF_0402"))
        
        # Decoupling caps 100nF - C1525
        for i in range(4):
            cap = self.add(Component("C_100NF_0402"))  # C1525
            cap['1'] += self.v3v3
            cap['2'] += self.gnd

        # Bulk cap 4.7uF - C84718
        self.c_bulk = self.add(Component("C_4U7_0603"))  # C84718
        self.c_bulk['1'] += self.v3v3
        self.c_bulk['2'] += self.gnd
        
        # Reset button - C2884834
        self.btn_reset = self.add(Component("SW_TACT_3X6MM"))

        # Reset 10k pullup - C60491
        self.r_reset = self.add(Component("R_10K_0402"))
        
        # Reset cap - C60474
        self.c_reset = self.add(Component("C_100NF_0402"))  # C1525
        
        # Boot0 pulldown - C60491
        self.r_boot0 = self.add(Component("R_10K_0402"))
        
        # USB-C connector - C165948
        self.usb_c = self.add(Component("USB_C_16PIN"))
        
        # USB CC resistors 5.1k - C25905
        self.r_cc1 = self.add(Component("R_5K1_0402"))
        self.r_cc2 = self.add(Component("R_5K1_0402"))
        
        # USB data series resistors 27R - C60458
        self.r_dp = self.add(Component("R_27R_0402"))
        self.r_dm = self.add(Component("R_27R_0402"))
        
        # USB ESD protection - C7518
        self.esd_usb = self.add(Component("ESD_USBLC6_2SC6"))
        
        # SWD header - C249742
        self.swd = self.add(Component("CONN_SWD_2X5_127MM"))
        
        # Status LED blue - C125088
        self.led_status = self.add(Component("LED_BLUE_0603"))
        self.r_status = self.add(Component("R_1K_0603"))  # C21190
        
        # Buses
        self.spi1_sck = Net("SPI1_SCK")
        self.spi1_miso = Net("SPI1_MISO")
        self.spi1_mosi = Net("SPI1_MOSI")
        self.spi1_cs_imu = Net("SPI1_CS_IMU")
        self.spi1_cs_flash = Net("SPI1_CS_FLASH")
        
        self.i2c1_scl = Net("I2C1_SCL")
        self.i2c1_sda = Net("I2C1_SDA")
        
        self.i2c2_scl = Net("I2C2_SCL")
        self.i2c2_sda = Net("I2C2_SDA")
        
        self.uart1_tx = Net("UART1_TX")
        self.uart1_rx = Net("UART1_RX")
        
        self.can_tx = Net("CAN_TX")
        self.can_rx = Net("CAN_RX")
        
        self.pwm1 = Net("PWM1")
        self.pwm2 = Net("PWM2")
        self.pwm3 = Net("PWM3")
        self.pwm4 = Net("PWM4")
        
        # USB data
        self.usb_dp = Net("USB_DP")
        self.usb_dm = Net("USB_DM")
        self.vbus_net = Net("VBUS")
        
        # MCU power
        self.mcu['VDD'] += self.v3v3
        self.mcu['VSS'] += self.gnd
        
        # Clock
        xtal8_in = Net("XTAL8_IN")
        xtal8_out = Net("XTAL8_OUT")
        self.mcu['PH0_OSC_IN'] += xtal8_in
        self.mcu['PH1_OSC_OUT'] += xtal8_out
        self.c_xtal1['1'] += xtal8_in
        self.c_xtal1['2'] += self.gnd
        self.c_xtal2['1'] += xtal8_out
        self.c_xtal2['2'] += self.gnd
        xtal8_in += self.xtal_8m['1']
        xtal8_out += self.xtal_8m['3']
        
        # 32kHz
        xtal32_in = Net("XTAL32_IN")
        xtal32_out = Net("XTAL32_OUT")
        self.mcu['PC14_OSC32_IN'] += xtal32_in
        self.mcu['PC15_OSC32_OUT'] += xtal32_out
        self.c_32k1['1'] += xtal32_in
        self.c_32k1['2'] += self.gnd
        self.c_32k2['1'] += xtal32_out
        self.c_32k2['2'] += self.gnd
        xtal32_in += self.xtal_32k['1']
        xtal32_out += self.xtal_32k['2']
        
        # Reset
        self.mcu['NRST'] += Net("NRST")
        self.r_reset['1'] += self.v3v3
        self.r_reset['2'] += Net("NRST")
        self.c_reset['1'] += Net("NRST")
        self.c_reset['2'] += self.gnd
        self.btn_reset['1'] += Net("NRST")
        self.btn_reset['2'] += self.gnd
        
        # Boot0
        self.mcu['BOOT0'] += Net("BOOT0")
        self.r_boot0['1'] += Net("BOOT0")
        self.r_boot0['2'] += self.gnd
        
        # SWD
        self.mcu['PA13_SWDIO'] += Net("SWDIO")
        self.mcu['PA14_SWCLK'] += Net("SWCLK")
        self.swd['1'] += self.v3v3
        self.swd['2'] += Net("SWDIO")
        self.swd['3'] += self.gnd
        self.swd['4'] += Net("SWCLK")
        self.swd['5'] += Net("NRST")
        
        # USB
        self.mcu['PA12_USB_DP'] += self.usb_dp
        self.mcu['PA11_USB_DM'] += self.usb_dm
        
        # USB connector
        self.usb_c['GND'] += self.gnd
        self.usb_c['VBUS'] += self.vbus_net
        self.usb_c['CC1'] += self.r_cc1['1']
        self.r_cc1['2'] += self.gnd
        self.usb_c['CC2'] += self.r_cc2['1']
        self.r_cc2['2'] += self.gnd
        self.usb_c['DP'] += self.r_dp['1']
        self.r_dp['2'] += self.esd_usb['1']
        self.esd_usb['2'] += self.usb_dp
        self.usb_c['DM'] += self.r_dm['1']
        self.r_dm['2'] += self.esd_usb['3']
        self.esd_usb['4'] += self.usb_dm
        self.esd_usb['GND'] += self.gnd
        
        # SPI1
        self.mcu['PA5_SPI1_SCK'] += self.spi1_sck
        self.mcu['PA6_SPI1_MISO'] += self.spi1_miso
        self.mcu['PA7_SPI1_MOSI'] += self.spi1_mosi
        # Chip selects
        self.mcu['PA4_SPI1_NSS'] += self.spi1_cs_imu
        self.mcu['PB2_SPI1_NSS'] += self.spi1_cs_flash
        
        # I2C1
        self.mcu['PB6_I2C1_SCL'] += self.i2c1_scl
        self.mcu['PB7_I2C1_SDA'] += self.i2c1_sda
        
        # UART1
        self.mcu['PA9_USART1_TX'] += self.uart1_tx
        self.mcu['PA10_USART1_RX'] += self.uart1_rx
        
        # CAN
        self.mcu['PB8_CAN1_RX'] += self.can_rx
        self.mcu['PB9_CAN1_TX'] += self.can_tx
        
        # PWM
        self.mcu['PA6_TIM3_CH1'] += self.pwm1
        self.mcu['PA7_TIM3_CH2'] += self.pwm2
        self.mcu['PB0_TIM3_CH3'] += self.pwm3
        self.mcu['PB1_TIM3_CH4'] += self.pwm4
        
        # Status LED
        self.mcu['PC13'] += Net("LED_STATUS")
        self.r_status['1'] += self.v3v3
        self.r_status['2'] += Net("LED_STATUS_NODE")
        self.led_status['A'] += Net("LED_STATUS_NODE")
        self.led_status['K'] += Net("LED_STATUS")
        
        self.max_current_draw_ma = {"3V3": 250}
        
        self.pwr_3v3 = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)
        self.spi1 = self.declare_interface("spi1", self.spi1_sck, self.spi1_miso, self.spi1_mosi, self.gnd)
        self.i2c1 = self.declare_interface("i2c1", self.i2c1_sda, self.i2c1_scl, self.gnd)
        self.uart1 = self.declare_interface("uart1", self.uart1_tx, self.uart1_rx, self.gnd, required=False)
        self.can = self.declare_interface("can", self.can_tx, self.can_rx, self.gnd)
        self.spi_cs_imu = self.declare_interface("spi_cs_imu", self.spi1_cs_imu)
        self.spi_cs_flash = self.declare_interface("spi_cs_flash", self.spi1_cs_flash)
        self.vbus = self.declare_interface("vbus", self.vbus_net, self.gnd)


class IMUModule(Module):
    """ICM-42688-P IMU from JLCPCB."""
    
    def __init__(self):
        super().__init__("IMUModule")
        
        self.v3v3 = Net("3V3")
        self.gnd = Net("GND")
        
        # ICM-42688-P - C2191168
        self.imu = self.add(Component("IMU_ICM42688P"))
        
        # Decoupling 100nF - C1525
        self.c_vdd = self.add(Component("C_100NF_0402"))
        self.c_vddio = self.add(Component("C_100NF_0402"))
        
        # Wiring
        self.imu['VDDIO'] += self.v3v3
        self.imu['VDD'] += self.v3v3
        self.imu['GND'] += self.gnd
        
        self.c_vdd['1'] += self.v3v3
        self.c_vdd['2'] += self.gnd
        self.c_vddio['1'] += self.v3v3
        self.c_vddio['2'] += self.gnd
        
        # SPI
        self.sck = Net("SPI1_SCK_IMU")
        self.miso = Net("SPI1_MISO_IMU")
        self.mosi = Net("SPI1_MOSI_IMU")
        self.cs = Net("SPI1_CS_IMU")
        
        self.imu['SCK'] += self.sck
        self.imu['SDO'] += self.miso
        self.imu['SDI'] += self.mosi
        self.imu['CS'] += self.cs
        
        self.int1 = Net("IMU_INT1")
        self.imu['INT1'] += self.int1
        
        self.max_current_draw_ma = {"3V3": 2}
        
        self.pwr = self.declare_interface("pwr", self.v3v3, self.gnd)
        self.spi = self.declare_interface("spi", self.sck, self.miso, self.mosi, self.gnd)
        self.cs_iface = self.declare_interface("cs", self.cs)


class BaroModule(Module):
    """BMP388 barometer from JLCPCB."""
    
    def __init__(self):
        super().__init__("BaroModule")
        
        self.v3v3 = Net("3V3")
        self.gnd = Net("GND")
        
        # BMP388 - C83294
        self.baro = self.add(Component("BARO_BMP388"))
        
        # Decoupling - C1525
        self.c_vdd = self.add(Component("C_100NF_0402"))
        
        self.baro['VDDIO'] += self.v3v3
        self.baro['VDD'] += self.v3v3
        self.baro['GND'] += self.gnd
        
        self.c_vdd['1'] += self.v3v3
        self.c_vdd['2'] += self.gnd
        
        # I2C
        self.scl = Net("I2C1_SCL_BARO")
        self.sda = Net("I2C1_SDA_BARO")
        
        self.baro['SCK'] += self.scl
        self.baro['SDI'] += self.sda
        self.baro['SDO'] += self.gnd  # Address 0x76
        
        self.int = Net("BARO_INT")
        self.baro['INT'] += self.int
        
        self.max_current_draw_ma = {"3V3": 1}
        
        self.pwr = self.declare_interface("pwr", self.v3v3, self.gnd)
        self.i2c = self.declare_interface("i2c", self.sda, self.scl, self.gnd)


class MagModule(Module):
    """QMC5883L magnetometer from JLCPCB."""
    
    def __init__(self):
        super().__init__("MagModule")
        
        self.v3v3 = Net("3V3")
        self.gnd = Net("GND")
        
        # QMC5883L - C976032
        self.mag = self.add(Component("MAG_QMC5883L"))
        
        # Decoupling - C1525
        self.c_vdd = self.add(Component("C_100NF_0402"))
        
        self.mag['VDD'] += self.v3v3
        self.mag['GND'] += self.gnd
        
        self.c_vdd['1'] += self.v3v3
        self.c_vdd['2'] += self.gnd
        
        # I2C
        self.scl = Net("I2C1_SCL_MAG")
        self.sda = Net("I2C1_SDA_MAG")
        
        self.mag['SCL'] += self.scl
        self.mag['SDA'] += self.sda
        
        self.max_current_draw_ma = {"3V3": 1}
        
        self.pwr = self.declare_interface("pwr", self.v3v3, self.gnd)
        self.i2c = self.declare_interface("i2c", self.sda, self.scl, self.gnd)


class FlashModule(Module):
    """W25Q128JV flash from JLCPCB."""
    
    def __init__(self):
        super().__init__("FlashModule")
        
        self.v3v3 = Net("3V3")
        self.gnd = Net("GND")
        
        # W25Q128JV - C97521
        self.flash = self.add(Component("FLASH_W25Q128JV"))
        
        # Decoupling - C1525
        self.c_vdd = self.add(Component("C_100NF_0402"))
        
        self.flash['VCC'] += self.v3v3
        self.flash['GND'] += self.gnd
        
        self.c_vdd['1'] += self.v3v3
        self.c_vdd['2'] += self.gnd
        
        # SPI
        self.sck = Net("SPI1_SCK_FLASH")
        self.miso = Net("SPI1_MISO_FLASH")
        self.mosi = Net("SPI1_MOSI_FLASH")
        self.cs = Net("SPI1_CS_FLASH")
        
        self.flash['CLK'] += self.sck
        self.flash['DO'] += self.miso
        self.flash['DI'] += self.mosi
        self.flash['CS'] += self.cs
        self.flash['WP'] += self.v3v3
        self.flash['HOLD'] += self.v3v3
        
        self.max_current_draw_ma = {"3V3": 5}
        
        self.pwr = self.declare_interface("pwr", self.v3v3, self.gnd)
        self.spi = self.declare_interface("spi", self.sck, self.miso, self.mosi, self.gnd)
        self.cs_iface = self.declare_interface("cs", self.cs)


class CANModule(Module):
    """TJA1051 CAN transceiver from JLCPCB."""
    
    def __init__(self):
        super().__init__("CANModule")
        
        self.v3v3 = Net("3V3")
        self.gnd = Net("GND")
        
        # TJA1051T/3 - C132146
        self.can = self.add(Component("CAN_TJA1051"))
        
        # Decoupling - C14663
        self.c_vdd = self.add(Component("C_100NF_0603"))
        
        self.can['VCC'] += self.v3v3
        self.can['GND'] += self.gnd
        
        self.c_vdd['1'] += self.v3v3
        self.c_vdd['2'] += self.gnd
        
        # Controller interface
        self.tx = Net("CAN_TX")
        self.rx = Net("CAN_RX")
        
        self.can['TXD'] += self.tx
        self.can['RXD'] += self.rx
        
        # Bus
        self.can_h = Net("CAN_H")
        self.can_l = Net("CAN_L")
        
        self.can['CANH'] += self.can_h
        self.can['CANL'] += self.can_l
        
        self.can['STB'] += self.gnd
        
        self.max_current_draw_ma = {"3V3": 10}
        
        self.pwr = self.declare_interface("pwr", self.v3v3, self.gnd)
        self.can_iface = self.declare_interface("can", self.tx, self.rx, self.gnd)


# ============ Board Assembly ============

def build_board() -> Board:
    board = Board(
        size_mm=(50, 50),
        layers=4,
        strict=False,
        declared_supply_voltages_v={"VBAT": 16.8, "5V": 5.0, "3V3": 3.3},
    )

    # Create modules
    power = PowerModule()
    mcu = MCUModule()
    imu = IMUModule()
    baro = BaroModule()
    mag = MagModule()
    flash = FlashModule()
    can = CANModule()

    # Add to board
    board.add_module(power)
    board.add_module(mcu)
    board.add_module(imu)
    board.add_module(baro)
    board.add_module(mag)
    board.add_module(flash)
    board.add_module(can)

    # Connect power
    board.connect(power.pwr_5v, mcu.vbus)
    board.connect(power.pwr_3v3, mcu.pwr_3v3)
    board.connect(power.pwr_3v3, imu.pwr)
    board.connect(power.pwr_3v3, baro.pwr)
    board.connect(power.pwr_3v3, mag.pwr)
    board.connect(power.pwr_3v3, flash.pwr)
    board.connect(power.pwr_3v3, can.pwr)

    # Connect buses
    board.connect(mcu.spi1, imu.spi)
    board.connect(mcu.spi1, flash.spi)
    board.connect(mcu.spi_cs_imu, imu.cs_iface)
    board.connect(mcu.spi_cs_flash, flash.cs_iface)
    board.connect(mcu.i2c1, baro.i2c)
    board.connect(mcu.i2c1, mag.i2c)
    board.connect(mcu.can, can.can_iface)

    # Power rails
    board.declare_power_rail("VBAT", Net("VBAT"))
    board.declare_power_rail("5V", Net("5V"))
    board.declare_power_rail("3V3", Net("3V3"))
    board.declare_power_rail("GND", Net("GND"))
    board.declare_rail_conversion("VBAT", "5V", efficiency=0.92)
    board.declare_rail_conversion("5V", "3V3", efficiency=0.85)

    # Layout constraints
    board.constrain_edge(power, edge="TOP")
    board.constrain_distance_min(power, mcu, min_distance_mm=15)
    board.constrain_exact_center(imu)
    board.constrain_distance_max(imu, mcu, 20)
    board.constrain_distance_min(baro, power, min_distance_mm=10)
    board.constrain_distance_max(flash, mcu, 15)
    board.constrain_edge(can, edge="RIGHT")

    # Keepouts and pours
    board.declare_keepout_rect(
        22,
        22,
        6,
        6,
        layers=("F.Cu", "B.Cu"),
        purpose="placement",
        note="IMU keepout",
    )
    board.declare_copper_pour_intent(Net("GND"), layer="F.Cu", purpose="ground")
    board.declare_copper_pour_intent(Net("GND"), layer="B.Cu", purpose="ground")

    # Mounting holes
    for x, y in [(3, 3), (47, 3), (3, 47), (47, 47)]:
        board.declare_mounting_hole(x, y, 3.2, note=f"M3 at ({x},{y})")

    return board


def main():
    board = build_board()
    board.compile(
        project_name="fc_jlc_only",
        generate_bom=True,
        export_schematic=True,
        auto_route=True,
    )


if __name__ == "__main__":
    main()
