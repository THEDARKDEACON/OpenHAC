import os
from skidl import *

# Environment bootstrapper runs automatically when openhac.core is imported.
# No manual KICAD8_SYMBOL_DIR or lib_search_paths hacks needed.

from openhac.core import Board
from openhac.core.base import Module, Component
from skidl import Net

# ==========================================
# 1. Complex Sub-Modules
# ==========================================

class PowerManagementUnit(Module):
    """
    Cascaded power system. Takes 4S-6S LiPo (14V-25V).
    Uses a switching buck converter for a heavy 5V rail (3A),
    and a low-dropout linear regulator (LDO) for a clean 3.3V rail.
    """
    def __init__(self):
        super().__init__("PMU")
        
        # High-power components (DB will pull exact LCSC parts)
        self.batt_in = self.add(Component("XT60_Vertical"))
        self.buck_5v = self.add(Component("LDO_5V_TO-252")) # 3A Switching Regulator
        self.ldo_3v3 = self.add(Component("LDO_3.3V_SOT-223"))  # Clean 3.3V LDO
        self.bulk_cap = self.add(Component("C_10uF_0805"))

        # Internal Net Logic
        v_batt = Net("V_BATT")
        v_5v = Net("5V_SYS")
        v_3v3 = Net("3V3_CLEAN")
        gnd = Net("GND")

        # Wire the cascade
        self.batt_in['1'] += v_batt
        self.batt_in['2'] += gnd
        
        # Buck takes Battery, outputs 5V
        self.buck_5v['VI'] += v_batt
        self.buck_5v['VO'] += v_5v
        self.buck_5v['GND'] += gnd
        
        # LDO takes 5V, outputs clean 3.3V
        self.ldo_3v3['VI'] += v_5v
        self.ldo_3v3['VO'] += v_3v3
        self.ldo_3v3['GND'] += gnd

        # ERC Constraints: Define the power limits for the compiler to track
        self.source_current_max_ma = {"5V": 3000, "3V3": 800}

        # Expose Interfaces
        self.batt = self.declare_interface("batt", v_batt, gnd)
        self.pwr_5v = self.declare_interface("pwr_5v", v_5v, gnd)
        self.pwr_3v3 = self.declare_interface("pwr_3v3", v_3v3, gnd)


class RedundantSensorArray(Module):
    """
    Dual IMUs on separate SPI buses for aerospace redundancy.
    Requires ultra-clean 3.3V power.
    """
    def __init__(self):
        super().__init__("SensorArray")
        
        # Two different gyro architectures to prevent resonant frequency overlap
        self.imu_primary = self.add(Component("ACCEL_X,Y,ZAXIS_LGA-16(3x3)")) # TDK InvenSense
        self.imu_backup = self.add(Component("ACCEL_X,Y,ZAXIS_LGA-14(3x5)"))       # Bosch
        vcc = Net("3V3")
        gnd = Net("GND")
        
        self.imu_primary['VDD'] += vcc
        self.imu_backup['VDD'] += vcc
        self.imu_primary['GND'] += gnd
        self.imu_backup['GND'] += gnd

        # ERC Constraint
        self.max_current_draw_ma = 50

        self.power = self.declare_interface("power", vcc, gnd)
        self.spi_1 = self.declare_interface("spi_1", self.imu_primary['SCK', 'MISO', 'MOSI', 'CS'])
        self.spi_2 = self.declare_interface("spi_2", self.imu_backup['SCK', 'MISO', 'MOSI', 'CS'])


class FlightComputeCore(Module):
    """
    High-end STM32H7 processing core. 
    """
    def __init__(self):
        super().__init__("ComputeCore")
        
        # 480MHz ARM Cortex-M7
        self.mcu = self.add(Component("MCU_STM32F407VET6_C28730"))
        self.usb = self.add(Component("Conn_USB_C_Receptacle"))

        vcc = Net("3V3")
        gnd = Net("GND")
        self.mcu['VDD'] += vcc
        self.mcu['VSS'] += gnd

        self.max_current_draw_ma = 400

        self.power = self.declare_interface("power", vcc, gnd)
        self.spi_1 = self.declare_interface("spi_1", self.mcu['PA5', 'PA6', 'PA7', 'PA4'])
        self.spi_2 = self.declare_interface("spi_2", self.mcu['PB13', 'PB14', 'PB15', 'PB12'])
        
        # Differential USB Interface
        self.usb_dp = self.mcu['PA12']
        self.usb_dm = self.mcu['PA11']


# ==========================================
# 2. Board Instantiation & Constraints
# ==========================================

# 6-Layer board required for dense routing and clean impedance matching
board = Board(size_mm=(36, 36), layers=6) 

pmu = PowerManagementUnit()
compute = FlightComputeCore()
sensors = RedundantSensorArray()

board.add_module(pmu)
board.add_module(compute)
board.add_module(sensors)

# --- ELECTRICAL LOGIC (The Netlist) ---
# Connect power (Compiler tracks the cascade: 3V3 rail draws from 5V rail)
board.connect(pmu.pwr_3v3, compute.power)
board.connect(pmu.pwr_3v3, sensors.power)

# Connect data buses
board.connect(compute.spi_1, sensors.spi_1)
board.connect(compute.spi_2, sensors.spi_2)

# --- SPATIAL CONSTRAINTS (The Z3 Solver & DRC Limits) ---
# 1. Physics constraint: Flight controllers need IMUs exactly in the center of mass
board.constrain_exact_center(sensors)

# 2. Noise isolation: Keep the noisy 3A switching inductor away from the analog gyros
board.constrain_distance_min(pmu.buck_5v, sensors, min_distance_mm=20)

# 3. High-Speed signal integrity: Force the auto-router to treat USB as differential
board.route_differential_pair(compute.usb_dp, compute.usb_dm, target_impedance_ohms=90)

# 4. Thermal mass: Force PMU to the board edge to dissipate heat to the frame
board.constrain_edge(pmu, edge="TOP")


# ==========================================
# 3. Compile Hardware
# ==========================================

board.compile(
    project_name="dojo_flight_controller",
    generate_bom=True,
    export_schematic=True,
    auto_route=True
)
