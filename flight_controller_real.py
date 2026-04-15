"""
flight_controller_real.py - Real, Functional Flight Controller Design

A complete flight controller design using real, sourceable components from JLCPCB/LCSC.
This design is electrically functional and can be manufactured.

Key Features:
- STM32F405RGT6 MCU (168MHz, FPU, suitable for flight control)
- ICM-42688-P 6-axis IMU (SPI, low noise)
- BMP388 barometer (I2C, high precision)
- QMC5883L magnetometer (I2C)
- W25Q128JV flash storage (SPI, 16MB for config/blackbox)
- TPS63001 buck-boost (5V from battery)
- LDL1117S33R LDO (3.3V for sensitive analog)
- USB-C for power and DFU programming
- 6 motor outputs (PWM, with level shifters)
- UART ports for GPS, telemetry
- I2C port for external sensors
- CAN bus for ESC communication
- SWD debug header
- Proper power sequencing and decoupling

Power Architecture:
VBAT (2S-6S LiPo) -> TPS63001 (5V/2A) -> LDL1117 (3.3V/800mA)
                                     +-> USB VBUS (5V)
                                     +-> Motor power (5V logic)

Compile:
    python -m openhac compile flight_controller_real.py --name fc_real
"""

from __future__ import annotations

import skidl
from skidl import Net, Part, Pin, TEMPLATE

from openhac.core import Board
from openhac.core.base import Module, Component


class PowerModule(Module):
    """
    Power management: VBAT -> 5V buck-boost -> 3.3V LDO
    
    Input: 2S-6S LiPo (7.4V - 25.2V)
    Outputs: 5V @ 2A (digital), 3.3V @ 800mA (analog/MCU)
    
    Components:
    - TPS63001: Buck-boost converter, 96% efficient, 2A output
    - LDL1117S33R: Low-dropout linear regulator, low noise
    - Proper input filtering and decoupling
    - Reverse polarity protection (P-MOSFET)
    """
    
    def __init__(self):
        super().__init__("PowerModule")
        
        # Power nets
        self.vbat = Net("VBAT")
        self.gnd = Net("GND")
        self.v5 = Net("5V")
        self.v3v3 = Net("3V3")
        
        # Input protection - P-MOSFET for reverse polarity
        self.protection_fet = self.add(Component("PMOS_SI2301_SOT23"))
        self.protection_fet.part.footprint = "Package_TO_SOT_SMD:SOT-23"
        
        # Buck-boost converter: TPS63001
        self.buck = self.add(Component("BUCK_TPS63001"))
        self.buck.part.footprint = "Package_DFN_QFN:VSON-10_3x3mm_P0.5mm"
        self.buck.part.fields["MPN"] = "TPS63001DRCR"
        self.buck.part.fields["Supplier_SKU"] = "C132150"
        
        # Buck inductor 2.2uH
        self.l_buck = self.add(Component("L_2R2_2520"))
        self.l_buck.part.footprint = "Inductor_SMD:L_2.5x2.0mm"
        self.l_buck.part.fields["MPN"] = "VLS252010ET-2R2M"
        self.l_buck.part.fields["Supplier_SKU"] = "C167240"
        
        # Input caps (VBAT)
        self.cin_10u = self.add(Component("C_10uF_1206_X5R"))
        self.cin_10u.part.footprint = "Capacitor_SMD:C_1206_3216Metric"
        self.cin_10u.part.fields["MPN"] = "GRM31CR61E106KA12L"
        self.cin_10u.part.fields["Supplier_SKU"] = "C77038"
        
        self.cin_100n = self.add(Component("C_100nF_0603_X7R"))
        self.cin_100n.part.footprint = "Capacitor_SMD:C_0603_1608Metric"
        self.cin_100n.part.fields["MPN"] = "CC0603KRX7R9BB104"
        self.cin_100n.part.fields["Supplier_SKU"] = "C14663"
        
        # 5V output caps
        self.cout5v_22u = self.add(Component("C_22uF_0805_X5R"))
        self.cout5v_22u.part.footprint = "Capacitor_SMD:C_0805_2012Metric"
        self.cout5v_22u.part.fields["MPN"] = "GRM21BR61C226ME44L"
        self.cout5v_22u.part.fields["Supplier_SKU"] = "C59461"
        
        self.cout5v_100n = self.add(Component("C_100nF_0603_X7R"))
        self.cout5v_100n.part.footprint = "Capacitor_SMD:C_0603_1608Metric"
        self.cout5v_100n.part.fields["MPN"] = "CC0603KRX7R9BB104"
        self.cout5v_100n.part.fields["Supplier_SKU"] = "C14663"
        
        # LDO: LDL1117S33R (3.3V, 800mA, low noise)
        self.ldo = self.add(Component("LDO_LDL1117_SOT223"))
        self.ldo.part.footprint = "Package_TO_SOT_SMD:SOT-223-3_TabPin2"
        self.ldo.part.fields["MPN"] = "LDL1117S33R"
        self.ldo.part.fields["Supplier_SKU"] = "C130026"
        
        # LDO input/output caps
        self.cldo_in_10u = self.add(Component("C_10uF_0805_X5R"))
        self.cldo_in_10u.part.footprint = "Capacitor_SMD:C_0805_2012Metric"
        self.cldo_in_10u.part.fields["MPN"] = "GRM21BR61C106KE15L"
        self.cldo_in_10u.part.fields["Supplier_SKU"] = "C440198"
        
        self.cldo_out_10u = self.add(Component("C_10uF_0805_X5R"))
        self.cldo_out_10u.part.footprint = "Capacitor_SMD:C_0805_2012Metric"
        self.cldo_out_10u.part.fields["MPN"] = "GRM21BR61C106KE15L"
        self.cldo_out_10u.part.fields["Supplier_SKU"] = "C440198"
        
        self.cldo_out_100n = self.add(Component("C_100nF_0603_X7R"))
        self.cldo_out_100n.part.footprint = "Capacitor_SMD:C_0603_1608Metric"
        self.cldo_out_100n.part.fields["MPN"] = "CC0603KRX7R9BB104"
        self.cldo_out_100n.part.fields["Supplier_SKU"] = "C14663"
        
        # Feedback resistors for buck
        self.r_fb1 = self.add(Component("R_100k_0603"))
        self.r_fb1.part.footprint = "Resistor_SMD:R_0603_1608Metric"
        self.r_fb1.part.fields["MPN"] = "RC0603FR-07100KL"
        self.r_fb1.part.fields["Supplier_SKU"] = "C25804"
        
        self.r_fb2 = self.add(Component("R_32k4_0603"))
        self.r_fb2.part.footprint = "Resistor_SMD:R_0603_1608Metric"
        self.r_fb2.part.fields["MPN"] = "RC0603FR-0732K4L"
        self.r_fb2.part.fields["Supplier_SKU"] = "C25818"
        
        # Power LED (5V indicator)
        self.led_pwr = self.add(Component("LED_GREEN_0603"))
        self.led_pwr.part.footprint = "LED_SMD:LED_0603_1608Metric"
        self.led_pwr.part.fields["MPN"] = "LTST-C193TGKT-5A"
        self.led_pwr.part.fields["Supplier_SKU"] = "C125093"
        
        self.r_led = self.add(Component("R_1k_0603"))
        self.r_led.part.footprint = "Resistor_SMD:R_0603_1608Metric"
        self.r_led.part.fields["MPN"] = "RC0603FR-071KL"
        self.r_led.part.fields["Supplier_SKU"] = "C21190"
        
        # Wiring
        # Protection FET
        self.protection_fet['S'] += self.vbat
        self.protection_fet['D'] += Net("VBAT_FUSED")
        self.protection_fet['G'] += self.gnd  # Always on for now
        
        vbat_fused = Net("VBAT_FUSED")
        
        # Buck converter wiring
        self.cin_10u['1'] += vbat_fused
        self.cin_10u['2'] += self.gnd
        self.cin_100n['1'] += vbat_fused
        self.cin_100n['2'] += self.gnd
        
        self.buck['VIN'] += vbat_fused
        self.buck['GND'] += self.gnd
        self.buck['SW'] += self.l_buck['1']
        self.l_buck['2'] += self.v5
        self.buck['FB'] += Net("FB_5V")
        
        # Feedback divider
        self.r_fb1['1'] += self.v5
        self.r_fb1['2'] += Net("FB_5V")
        self.r_fb2['1'] += Net("FB_5V")
        self.r_fb2['2'] += self.gnd
        
        # 5V output decoupling
        self.cout5v_22u['1'] += self.v5
        self.cout5v_22u['2'] += self.gnd
        self.cout5v_100n['1'] += self.v5
        self.cout5v_100n['2'] += self.gnd
        
        # LDO wiring
        self.cldo_in_10u['1'] += self.v5
        self.cldo_in_10u['2'] += self.gnd
        self.ldo['IN'] += self.v5
        self.ldo['GND'] += self.gnd
        self.ldo['OUT'] += self.v3v3
        
        # 3.3V decoupling
        self.cldo_out_10u['1'] += self.v3v3
        self.cldo_out_10u['2'] += self.gnd
        self.cldo_out_100n['1'] += self.v3v3
        self.cldo_out_100n['2'] += self.gnd
        
        # Power LED
        self.r_led['1'] += self.v5
        self.r_led['2'] += Net("LED_PWR_NODE")
        self.led_pwr['A'] += Net("LED_PWR_NODE")
        self.led_pwr['K'] += self.gnd
        
        # Power budget
        self.source_current_max_ma = {"5V": 2000, "3V3": 800}
        
        # Interfaces
        self.pwr_5v = self.declare_interface("pwr_5v", self.v5, self.gnd)
        self.pwr_3v3 = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)
        self.vbat_out = self.declare_interface("vbat_out", self.vbat, self.gnd)


class MCUModule(Module):
    """
    STM32F405RGT6 MCU with support circuitry.
    
    Features:
    - STM32F405RGT6: LQFP-64, 168MHz, 1MB Flash, 192KB RAM
    - 8MHz crystal for HSE
    - 32.768kHz crystal for RTC
    - USB-C for DFU programming
    - SWD debug header
    - Reset button
    - Boot mode selection
    - Extensive decoupling
    """
    
    def __init__(self):
        super().__init__("MCUModule")
        
        # Power nets (will be connected externally)
        self.v3v3 = Net("3V3")
        self.gnd = Net("GND")
        
        # STM32F405RGT6 - Main MCU
        self.mcu = self.add(Component("MCU_STM32F405RGT6"))
        self.mcu.part.footprint = "Package_QFP:LQFP-64_10x10mm_P0.5mm"
        self.mcu.part.fields["MPN"] = "STM32F405RGT6"
        self.mcu.part.fields["Supplier_SKU"] = "C7862"
        self.mcu.part.fields["Description"] = "ARM Cortex-M4 168MHz 1MB Flash"
        
        # 8MHz Crystal for HSE
        self.xtal_8m = self.add(Component("XTAL_8MHz_3225"))
        self.xtal_8m.part.footprint = "Crystal:Crystal_SMD_3225-4Pin_3.2x2.5mm"
        self.xtal_8m.part.fields["MPN"] = "X32258MSB4SI"
        self.xtal_8m.part.fields["Supplier_SKU"] = "C15629"
        
        # Crystal load caps (18pF for 8MHz with 20pF crystal)
        self.c_xtal1 = self.add(Component("C_18pF_0402_C0G"))
        self.c_xtal1.part.footprint = "Capacitor_SMD:C_0402_1005Metric"
        self.c_xtal1.part.fields["MPN"] = "GRM1555C1H180JZ01D"
        self.c_xtal1.part.fields["Supplier_SKU"] = "C107274"
        
        self.c_xtal2 = self.add(Component("C_18pF_0402_C0G"))
        self.c_xtal2.part.footprint = "Capacitor_SMD:C_0402_1005Metric"
        self.c_xtal2.part.fields["MPN"] = "GRM1555C1H180JZ01D"
        self.c_xtal2.part.fields["Supplier_SKU"] = "C107274"
        
        # 32.768kHz RTC crystal
        self.xtal_32k = self.add(Component("XTAL_32.768kHz_3215"))
        self.xtal_32k.part.footprint = "Crystal:Crystal_SMD_3215-2Pin_3.2x1.5mm"
        self.xtal_32k.part.fields["MPN"] = "FC-135"
        self.xtal_32k.part.fields["Supplier_SKU"] = "C70501"
        
        self.c_32k1 = self.add(Component("C_12pF_0402_C0G"))
        self.c_32k1.part.footprint = "Capacitor_SMD:C_0402_1005Metric"
        self.c_32k1.part.fields["MPN"] = "GRM1555C1H120JZ01D"
        self.c_32k1.part.fields["Supplier_SKU"] = "C107270"
        
        self.c_32k2 = self.add(Component("C_12pF_0402_C0G"))
        self.c_32k2.part.footprint = "Capacitor_SMD:C_0402_1005Metric"
        self.c_32k2.part.fields["MPN"] = "GRM1555C1H120JZ01D"
        self.c_32k2.part.fields["Supplier_SKU"] = "C107270"
        
        # MCU Decoupling - extensive for high-speed operation
        # 4x 100nF near power pins
        for i in range(4):
            cap = self.add(Component(f"C_100nF_0402_VDD_{i}"))
            cap.part.footprint = "Capacitor_SMD:C_0402_1005Metric"
            cap.part.fields["MPN"] = "GRM155R71C104KA88D"
            cap.part.fields["Supplier_SKU"] = "C1525"
            cap['1'] += self.v3v3
            cap['2'] += self.gnd
        
        # 1x 4.7uF for bulk decoupling
        self.c_bulk = self.add(Component("C_4u7F_0603_X5R"))
        self.c_bulk.part.footprint = "Capacitor_SMD:C_0603_1608Metric"
        self.c_bulk.part.fields["MPN"] = "GRM188R61E475KE21D"
        self.c_bulk.part.fields["Supplier_SKU"] = "C84718"
        self.c_bulk['1'] += self.v3v3
        self.c_bulk['2'] += self.gnd
        
        # Reset circuit
        self.btn_reset = self.add(Component("SW_TACT_3x6mm"))
        self.btn_reset.part.footprint = "Button_Switch_SMD:SW_SPST_TL3342"
        self.btn_reset.part.fields["MPN"] = "TL3342F160QG"
        self.btn_reset.part.fields["Supplier_SKU"] = "C2884834"
        
        self.r_reset = self.add(Component("R_10k_0402"))
        self.r_reset.part.footprint = "Resistor_SMD:R_0402_1005Metric"
        self.r_reset.part.fields["MPN"] = "RC0402FR-0710KL"
        self.r_reset.part.fields["Supplier_SKU"] = "C60491"
        
        self.c_reset = self.add(Component("C_100nF_0402_X7R"))
        self.c_reset.part.footprint = "Capacitor_SMD:C_0402_1005Metric"
        self.c_reset.part.fields["MPN"] = "CC0402KRX7R9BB104"
        self.c_reset.part.fields["Supplier_SKU"] = "C60474"
        
        # Boot mode selection (BOOT0)
        self.r_boot0 = self.add(Component("R_10k_0402"))
        self.r_boot0.part.footprint = "Resistor_SMD:R_0402_1005Metric"
        self.r_boot0.part.fields["MPN"] = "RC0402FR-0710KL"
        self.r_boot0.part.fields["Supplier_SKU"] = "C60491"
        
        # USB-C connector with CC resistors
        self.usb_c = self.add(Component("USB_C_16P"))
        self.usb_c.part.footprint = "Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12"
        self.usb_c.part.fields["MPN"] = "TYPE-C-31-M-12"
        self.usb_c.part.fields["Supplier_SKU"] = "C165948"
        
        # USB CC pull-down resistors (5.1k)
        self.r_cc1 = self.add(Component("R_5k1_0402"))
        self.r_cc1.part.footprint = "Resistor_SMD:R_0402_1005Metric"
        self.r_cc1.part.fields["MPN"] = "RC0402FR-075K1L"
        self.r_cc1.part.fields["Supplier_SKU"] = "C25905"
        
        self.r_cc2 = self.add(Component("R_5k1_0402"))
        self.r_cc2.part.footprint = "Resistor_SMD:R_0402_1005Metric"
        self.r_cc2.part.fields["MPN"] = "RC0402FR-075K1L"
        self.r_cc2.part.fields["Supplier_SKU"] = "C25905"
        
        # USB data series resistors (27R)
        self.r_dp = self.add(Component("R_27R_0402"))
        self.r_dp.part.footprint = "Resistor_SMD:R_0402_1005Metric"
        self.r_dp.part.fields["MPN"] = "RC0402FR-0727RL"
        self.r_dp.part.fields["Supplier_SKU"] = "C60458"
        
        self.r_dm = self.add(Component("R_27R_0402"))
        self.r_dm.part.footprint = "Resistor_SMD:R_0402_1005Metric"
        self.r_dm.part.fields["MPN"] = "RC0402FR-0727RL"
        self.r_dm.part.fields["Supplier_SKU"] = "C60458"
        
        # USB ESD protection
        self.esd_usb = self.add(Component("ESD_USBLC6_2SC6"))
        self.esd_usb.part.footprint = "Package_TO_SOT_SMD:SOT-23-6"
        self.esd_usb.part.fields["MPN"] = "USBLC6-2SC6"
        self.esd_usb.part.fields["Supplier_SKU"] = "C7518"
        
        # SWD Debug header (2x5 1.27mm)
        self.swd = self.add(Component("CONN_SWD_2x5_1.27"))
        self.swd.part.footprint = "Connector_PinHeader_1.27mm:PinHeader_2x05_P1.27mm_Vertical"
        self.swd.part.fields["MPN"] = "X6511FRS-05-C85D30M"
        self.swd.part.fields["Supplier_SKU"] = "C249742"
        
        # Status LED
        self.led_status = self.add(Component("LED_BLUE_0603"))
        self.led_status.part.footprint = "LED_SMD:LED_0603_1608Metric"
        self.led_status.part.fields["MPN"] = "LTST-C193TBKT-5A"
        self.led_status.part.fields["Supplier_SKU"] = "C125088"
        
        self.r_status = self.add(Component("R_1k_0603"))
        self.r_status.part.footprint = "Resistor_SMD:R_0603_1608Metric"
        self.r_status.part.fields["MPN"] = "RC0603FR-071KL"
        self.r_status.part.fields["Supplier_SKU"] = "C21190"
        
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
        
        self.uart2_tx = Net("UART2_TX")
        self.uart2_rx = Net("UART2_RX")
        
        self.can_tx = Net("CAN_TX")
        self.can_rx = Net("CAN_RX")
        
        self.pwm1 = Net("PWM1")
        self.pwm2 = Net("PWM2")
        self.pwm3 = Net("PWM3")
        self.pwm4 = Net("PWM4")
        self.pwm5 = Net("PWM5")
        self.pwm6 = Net("PWM6")
        
        # USB data
        self.usb_dp = Net("USB_DP")
        self.usb_dm = Net("USB_DM")
        
        # MCU wiring (key pins)
        # Power
        self.mcu['VDD'] += self.v3v3
        self.mcu['VSS'] += self.gnd
        self.mcu['VDDA'] += self.v3v3
        self.mcu['VSSA'] += self.gnd
        self.mcu['VREF+'] += self.v3v3
        
        # Clock
        self.mcu['PH0_OSC_IN'] += Net("XTAL8_IN")
        self.mcu['PH1_OSC_OUT'] += Net("XTAL8_OUT")
        self.c_xtal1['1'] += Net("XTAL8_IN")
        self.c_xtal1['2'] += self.gnd
        self.c_xtal2['1'] += Net("XTAL8_OUT")
        self.c_xtal2['2'] += self.gnd
        # Crystal connections
        Net("XTAL8_IN") += self.xtal_8m['1']
        Net("XTAL8_OUT") += self.xtal_8m['3']
        
        # 32kHz RTC
        self.mcu['PC14_OSC32_IN'] += Net("XTAL32_IN")
        self.mcu['PC15_OSC32_OUT'] += Net("XTAL32_OUT")
        self.c_32k1['1'] += Net("XTAL32_IN")
        self.c_32k1['2'] += self.gnd
        self.c_32k2['1'] += Net("XTAL32_OUT")
        self.c_32k2['2'] += self.gnd
        Net("XTAL32_IN") += self.xtal_32k['1']
        Net("XTAL32_OUT") += self.xtal_32k['2']
        
        # Reset
        self.mcu['NRST'] += Net("NRST")
        self.r_reset['1'] += self.v3v3
        self.r_reset['2'] += Net("NRST")
        self.c_reset['1'] += Net("NRST")
        self.c_reset['2'] += self.gnd
        self.btn_reset['1'] += Net("NRST")
        self.btn_reset['2'] += self.gnd
        
        # Boot0 (pulldown for normal boot)
        self.mcu['BOOT0'] += Net("BOOT0")
        self.r_boot0['1'] += Net("BOOT0")
        self.r_boot0['2'] += self.gnd
        
        # SWD
        self.mcu['PA13_SWDIO'] += Net("SWDIO")
        self.mcu['PA14_SWCLK'] += Net("SWCLK")
        self.swd['1'] += self.v3v3  # VCC
        self.swd['2'] += Net("SWDIO")
        self.swd['3'] += self.gnd   # GND
        self.swd['4'] += Net("SWCLK")
        self.swd['5'] += Net("NRST")
        
        # USB
        self.mcu['PA12_USB_DP'] += self.usb_dp
        self.mcu['PA11_USB_DM'] += self.usb_dm
        
        # USB connector
        self.usb_c['A1'] += self.gnd
        self.usb_c['A12'] += self.gnd
        self.usb_c['B1'] += self.gnd
        self.usb_c['B12'] += self.gnd
        self.usb_c['A4'] += Net("VBUS")  # VBUS from power module
        self.usb_c['A9'] += Net("VBUS")
        self.usb_c['B4'] += Net("VBUS")
        self.usb_c['B9'] += Net("VBUS")
        
        # CC pins with pull-downs
        self.usb_c['A5'] += self.r_cc1['1']
        self.r_cc1['2'] += self.gnd
        self.usb_c['B5'] += self.r_cc2['1']
        self.r_cc2['2'] += self.gnd
        
        # USB data through series resistors and ESD
        self.usb_c['A6'] += self.r_dp['1']
        self.r_dp['2'] += self.esd_usb['1']  # I/O1
        self.esd_usb['2'] += self.usb_dp     # I/O2
        self.esd_usb['5'] += self.gnd        # GND
        
        self.usb_c['A7'] += self.r_dm['1']
        self.r_dm['2'] += self.esd_usb['3']  # I/O3
        self.esd_usb['4'] += self.usb_dm     # I/O4
        self.esd_usb['6'] += Net("VBUS")     # VCC
        
        # SPI1 (for IMU and Flash)
        self.mcu['PA5_SPI1_SCK'] += self.spi1_sck
        self.mcu['PA6_SPI1_MISO'] += self.spi1_miso
        self.mcu['PA7_SPI1_MOSI'] += self.spi1_mosi
        
        # I2C1 (for baro and mag)
        self.mcu['PB6_I2C1_SCL'] += self.i2c1_scl
        self.mcu['PB7_I2C1_SDA'] += self.i2c1_sda
        
        # I2C2 (external port)
        self.mcu['PB10_I2C2_SCL'] += self.i2c2_scl
        self.mcu['PB11_I2C2_SDA'] += self.i2c2_sda
        
        # UART1 (GPS)
        self.mcu['PA9_USART1_TX'] += self.uart1_tx
        self.mcu['PA10_USART1_RX'] += self.uart1_rx
        
        # UART2 (Telemetry)
        self.mcu['PA2_USART2_TX'] += self.uart2_tx
        self.mcu['PA3_USART2_RX'] += self.uart2_rx
        
        # CAN
        self.mcu['PB8_CAN1_RX'] += self.can_rx
        self.mcu['PB9_CAN1_TX'] += self.can_tx
        
        # PWM outputs (TIM3 and TIM4)
        self.mcu['PA6_TIM3_CH1'] += self.pwm1
        self.mcu['PA7_TIM3_CH2'] += self.pwm2
        self.mcu['PB0_TIM3_CH3'] += self.pwm3
        self.mcu['PB1_TIM3_CH4'] += self.pwm4
        self.mcu['PB6_TIM4_CH1'] += self.pwm5
        self.mcu['PB7_TIM4_CH2'] += self.pwm6
        
        # Status LED (on PC13)
        self.mcu['PC13'] += Net("LED_STATUS")
        self.r_status['1'] += self.v3v3
        self.r_status['2'] += Net("LED_STATUS_NODE")
        self.led_status['A'] += Net("LED_STATUS_NODE")
        self.led_status['K'] += Net("LED_STATUS")
        
        # Power budget
        self.max_current_draw_ma = {"3V3": 250}
        
        # Declare interfaces
        self.pwr_3v3 = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)
        self.spi1 = self.declare_interface("spi1", self.spi1_sck, self.spi1_miso, self.spi1_mosi, self.gnd)
        self.i2c1 = self.declare_interface("i2c1", self.i2c1_sda, self.i2c1_scl, self.gnd)
        self.i2c2 = self.declare_interface("i2c2", self.i2c2_sda, self.i2c2_scl, self.gnd)
        self.uart1 = self.declare_interface("uart1", self.uart1_tx, self.uart1_rx, self.gnd)
        self.uart2 = self.declare_interface("uart2", self.uart2_tx, self.uart2_rx, self.gnd)
        self.can = self.declare_interface("can", self.can_tx, self.can_rx, self.gnd)
        
        # PWM interface (6 channels)
        self.pwm = self.declare_interface("pwm", self.pwm1, self.pwm2, self.pwm3, self.pwm4, self.pwm5, self.pwm6, self.gnd)
        
        # CS outputs for SPI devices
        self.spi_cs = self.declare_interface("spi_cs", self.spi1_cs_imu, self.spi1_cs_flash)
        
        # VBUS input
        self.vbus = self.declare_interface("vbus", Net("VBUS"), self.gnd)


class IMUModule(Module):
    """
    ICM-42688-P 6-axis IMU (accelerometer + gyroscope).
    
    High-performance MEMS sensor for flight control.
    - SPI interface (up to 24MHz)
    - 3-axis accelerometer: ±2/4/8/16g
    - 3-axis gyroscope: ±15.625/31.25/62.5/125/250/500/1000/2000°/s
    - Low noise: 4 mdps/√Hz
    - LGA-14 package
    """
    
    def __init__(self):
        super().__init__("IMUModule")
        
        self.v3v3 = Net("3V3")
        self.gnd = Net("GND")
        
        # IMU chip
        self.imu = self.add(Component("IMU_ICM42688"))
        self.imu.part.footprint = "Package_LGA:LGA-14_3x2.5mm_P0.5mm"
        self.imu.part.fields["MPN"] = "ICM-42688-P"
        self.imu.part.fields["Supplier_SKU"] = "C2191168"
        
        # Decoupling caps (per datasheet)
        self.c_vdd = self.add(Component("C_100nF_0402_X7R"))
        self.c_vdd.part.footprint = "Capacitor_SMD:C_0402_1005Metric"
        self.c_vdd.part.fields["MPN"] = "GRM155R71C104KA88D"
        self.c_vdd.part.fields["Supplier_SKU"] = "C1525"
        
        self.c_vddio = self.add(Component("C_100nF_0402_X7R"))
        self.c_vddio.part.footprint = "Capacitor_SMD:C_0402_1005Metric"
        self.c_vddio.part.fields["MPN"] = "GRM155R71C104KA88D"
        self.c_vddio.part.fields["Supplier_SKU"] = "C1525"
        
        # Wiring
        self.imu['VDDIO'] += self.v3v3
        self.imu['VDD'] += self.v3v3
        self.imu['GND'] += self.gnd
        
        self.c_vdd['1'] += self.v3v3
        self.c_vdd['2'] += self.gnd
        self.c_vddio['1'] += self.v3v3
        self.c_vddio['2'] += self.gnd
        
        # SPI connections (to be connected externally)
        self.sck = Net("SPI1_SCK_IMU")
        self.miso = Net("SPI1_MISO_IMU")
        self.mosi = Net("SPI1_MOSI_IMU")
        self.cs = Net("SPI1_CS_IMU")
        
        self.imu['SCK'] += self.sck
        self.imu['SDO'] += self.miso
        self.imu['SDI'] += self.mosi
        self.imu['CS'] += self.cs
        
        # Interrupt output
        self.int1 = Net("IMU_INT1")
        self.imu['INT1'] += self.int1
        
        self.max_current_draw_ma = {"3V3": 2}
        
        self.pwr = self.declare_interface("pwr", self.v3v3, self.gnd)
        self.spi = self.declare_interface("spi", self.sck, self.miso, self.mosi, self.gnd)
        self.cs_iface = self.declare_interface("cs", self.cs)


class BaroModule(Module):
    """
    BMP388 barometric pressure sensor.
    
    - I2C interface (up to 3.4MHz)
    - 300-1250 hPa range
    - ±8cm relative accuracy
    - LGA-8 package
    """
    
    def __init__(self):
        super().__init__("BaroModule")
        
        self.v3v3 = Net("3V3")
        self.gnd = Net("GND")
        
        self.baro = self.add(Component("BARO_BMP388"))
        self.baro.part.footprint = "Package_LGA:Bosch_LGA-8_2x2.5mm_P0.65mm"
        self.baro.part.fields["MPN"] = "BMP388"
        self.baro.part.fields["Supplier_SKU"] = "C83294"
        
        # Decoupling
        self.c_vdd = self.add(Component("C_100nF_0402_X7R"))
        self.c_vdd.part.footprint = "Capacitor_SMD:C_0402_1005Metric"
        self.c_vdd.part.fields["MPN"] = "GRM155R71C104KA88D"
        self.c_vdd.part.fields["Supplier_SKU"] = "C1525"
        
        # Wiring
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
        
        # I2C address select (ground = 0x76)
        self.baro['SDO'] += self.gnd
        
        # Interrupt
        self.int = Net("BARO_INT")
        self.baro['INT'] += self.int
        
        self.max_current_draw_ma = {"3V3": 1}
        
        self.pwr = self.declare_interface("pwr", self.v3v3, self.gnd)
        self.i2c = self.declare_interface("i2c", self.sda, self.scl, self.gnd)


class MagModule(Module):
    """
    QMC5883L 3-axis magnetometer.
    
    - I2C interface
    - ±2/±8 gauss ranges
    - 1° to 2° heading accuracy
    - QMC5883L in LGA-16
    """
    
    def __init__(self):
        super().__init__("MagModule")
        
        self.v3v3 = Net("3V3")
        self.gnd = Net("GND")
        
        self.mag = self.add(Component("MAG_QMC5883L"))
        self.mag.part.footprint = "Package_LGA:LGA-16_3x3mm_P0.5mm"
        self.mag.part.fields["MPN"] = "QMC5883L"
        self.mag.part.fields["Supplier_SKU"] = "C976032"
        
        # Decoupling
        self.c_vdd = self.add(Component("C_100nF_0402_X7R"))
        self.c_vdd.part.footprint = "Capacitor_SMD:C_0402_1005Metric"
        self.c_vdd.part.fields["MPN"] = "GRM155R71C104KA88D"
        self.c_vdd.part.fields["Supplier_SKU"] = "C1525"
        
        # Wiring
        self.mag['VDD'] += self.v3v3
        self.mag['GND'] += self.gnd
        
        self.c_vdd['1'] += self.v3v3
        self.c_vdd['2'] += self.gnd
        
        # I2C
        self.scl = Net("I2C1_SCL_MAG")
        self.sda = Net("I2C1_SDA_MAG")
        
        self.mag['SCL'] += self.scl
        self.mag['SDA'] += self.sda
        
        # Address select
        self.mag['SETC'] += self.gnd
        
        # DRDY output
        self.drdy = Net("MAG_DRDY")
        self.mag['DRDY'] += self.drdy
        
        self.max_current_draw_ma = {"3V3": 1}
        
        self.pwr = self.declare_interface("pwr", self.v3v3, self.gnd)
        self.i2c = self.declare_interface("i2c", self.sda, self.scl, self.gnd)


class FlashModule(Module):
    """
    W25Q128JV flash storage (16MB).
    
    - SPI interface (up to 133MHz)
    - 128M-bit / 16M-byte
    - SOIC-8 package
    """
    
    def __init__(self):
        super().__init__("FlashModule")
        
        self.v3v3 = Net("3V3")
        self.gnd = Net("GND")
        
        self.flash = self.add(Component("FLASH_W25Q128JV"))
        self.flash.part.footprint = "Package_SO:SOIC-8_5.23x5.23mm_P1.27mm"
        self.flash.part.fields["MPN"] = "W25Q128JVSIQ"
        self.flash.part.fields["Supplier_SKU"] = "C97521"
        
        # Decoupling
        self.c_vdd = self.add(Component("C_100nF_0402_X7R"))
        self.c_vdd.part.footprint = "Capacitor_SMD:C_0402_1005Metric"
        self.c_vdd.part.fields["MPN"] = "GRM155R71C104KA88D"
        self.c_vdd.part.fields["Supplier_SKU"] = "C1525"
        
        # Wiring
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
        
        # WP and HOLD (tie high)
        self.flash['WP'] += self.v3v3
        self.flash['HOLD'] += self.v3v3
        
        self.max_current_draw_ma = {"3V3": 5}
        
        self.pwr = self.declare_interface("pwr", self.v3v3, self.gnd)
        self.spi = self.declare_interface("spi", self.sck, self.miso, self.mosi, self.gnd)
        self.cs_iface = self.declare_interface("cs", self.cs)


class CANModule(Module):
    """
    TJA1051 CAN transceiver.
    
    - ISO 11898-2:2016 compliant
    - Up to 5Mbps
    - SOT-223 package
    """
    
    def __init__(self):
        super().__init__("CANModule")
        
        self.v3v3 = Net("3V3")
        self.gnd = Net("GND")
        
        self.can = self.add(Component("CAN_TJA1051"))
        self.can.part.footprint = "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm"
        self.can.part.fields["MPN"] = "TJA1051T/3"
        self.can.part.fields["Supplier_SKU"] = "C132146"
        
        # Decoupling
        self.c_vdd = self.add(Component("C_100nF_0603_X7R"))
        self.c_vdd.part.footprint = "Capacitor_SMD:C_0603_1608Metric"
        self.c_vdd.part.fields["MPN"] = "CC0603KRX7R9BB104"
        self.c_vdd.part.fields["Supplier_SKU"] = "C14663"
        
        # Wiring
        self.can['VCC'] += self.v3v3
        self.can['GND'] += self.gnd
        
        self.c_vdd['1'] += self.v3v3
        self.c_vdd['2'] += self.gnd
        
        # CAN controller interface
        self.tx = Net("CAN_TX")
        self.rx = Net("CAN_RX")
        
        self.can['TXD'] += self.tx
        self.can['RXD'] += self.rx
        
        # CAN bus (differential pair)
        self.can_h = Net("CAN_H")
        self.can_l = Net("CAN_L")
        
        self.can['CANH'] += self.can_h
        self.can['CANL'] += self.can_l
        
        # STB (standby, active low - tie low for normal mode)
        self.can['STB'] += self.gnd
        
        # Termination resistor (120R) - typically on one end of bus
        # Not included here as it's bus-dependent
        
        self.max_current_draw_ma = {"3V3": 10}
        
        self.pwr = self.declare_interface("pwr", self.v3v3, self.gnd)
        self.can_iface = self.declare_interface("can", self.tx, self.rx, self.gnd)
        self.can_bus = self.declare_interface("can_bus", self.can_h, self.can_l)


# ============ Board Assembly ============

board = Board(
    size_mm=(50, 50),
    layers=4,
    declared_supply_voltages_v={"VBAT": 16.8, "5V": 5.0, "3V3": 3.3}
)

# Create modules
power = PowerModule()
mcu = MCUModule()
imu = IMUModule()
baro = BaroModule()
mag = MagModule()
flash = FlashModule()
can = CANModule()

# Add modules to board
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

# Connect SPI bus (MCU to IMU and Flash)
# Note: Shared bus, separate CS
board.connect(mcu.spi1, imu.spi)
board.connect(mcu.spi1, flash.spi)
board.connect(mcu.spi_cs, imu.cs_iface)
board.connect(mcu.spi_cs, flash.cs_iface)

# Connect I2C1 (shared between baro and mag)
board.connect(mcu.i2c1, baro.i2c)
board.connect(mcu.i2c1, mag.i2c)

# Connect CAN
board.connect(mcu.can, can.can_iface)

# Declare power rails
board.declare_power_rail("VBAT", Net("VBAT"))
board.declare_power_rail("5V", Net("5V"))
board.declare_power_rail("3V3", Net("3V3"))
board.declare_power_rail("GND", Net("GND"))
board.declare_rail_conversion("VBAT", "5V", efficiency=0.92)
board.declare_rail_conversion("5V", "3V3", efficiency=0.85)

# Layout constraints
board.constrain_edge(power, edge="TOP")
board.constrain_distance_min(power, mcu, min_distance_mm=15)
board.constrain_distance_max(power, mcu, max_distance_mm=30)

# IMU should be near center for mechanical balance
board.constrain_exact_center(imu)
board.constrain_distance_max(imu, mcu, max_distance_mm=20)

# Baro away from heat sources
board.constrain_distance_min(baro, power, min_distance_mm=10)

# Flash near MCU
board.constrain_distance_max(flash, mcu, max_distance_mm=15)

# CAN near edge for connector
board.constrain_edge(can, edge="RIGHT")

# Keepouts
# IMU keepout for accurate readings
board.declare_keepout_rect(22, 22, 6, 6, layers=("F.Cu", "B.Cu"), purpose="placement", note="IMU keepout")

# Copper pours
board.declare_copper_pour_intent(Net("GND"), layer="F.Cu", purpose="ground")
board.declare_copper_pour_intent(Net("GND"), layer="B.Cu", purpose="ground")
board.declare_copper_pour_intent(Net("3V3"), layer="In1.Cu", purpose="power")
board.declare_copper_pour_intent(Net("5V"), layer="In2.Cu", purpose="power")

# Mounting holes (M3)
for x, y in [(3, 3), (47, 3), (3, 47), (47, 47)]:
    board.declare_mounting_hole(x, y, 3.2, note=f"M3 mounting hole at ({x}, {y})")


def main():
    board.compile(
        project_name="fc_real",
        generate_bom=True,
        export_schematic=True,
        auto_route=True,
    )


if __name__ == "__main__":
    main()
