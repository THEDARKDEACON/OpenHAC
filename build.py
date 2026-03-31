print("Starting OpenHaC test...")
from openhac.core import Board
from openhac.stdlib.power import LDO_5V, XT60_Input
from openhac.stdlib.mcu import ESP32_WROOM
print("Imports loaded.")

board = Board(size_mm=(50, 50), layers=2)
print("Board initialized.")

# 2. Instantiate high-level modules (Backed by real MPNs in the DB)
power_in = XT60_Input()
power_in.name = "POWER_IN"
power_in.width = 15
power_in.height = 10
print("XT60_Input initialized.")

regulator = LDO_5V()
regulator.name = "LDO"
regulator.width = 10
regulator.height = 10
print("LDO_5V initialized.")

mcu = ESP32_WROOM()
mcu.name = "ESP32"
mcu.width = 20
mcu.height = 25
print("MCU initialized.")

board.add_module(power_in)
board.add_module(regulator)
board.add_module(mcu)

# 3. Declarative Interfacing (Agnostic to raw pins)
board.connect(power_in.v_out, regulator.v_in)
board.connect(regulator.v_out, mcu.power)
print("Connections made.")

# SMT Mathematical Constraints
print("Injecting spatial constraints...")
# 1. Power Connector must be on the TOP edge
board.constrain_edge(power_in, "TOP")
# 2. Regulator should be relatively close to the ESP32 (Manhattan distance <= 15mm)
board.constrain_distance_max(regulator, mcu, 15)
# 3. But the hot Regulator must be at least 8mm away from the MCU
board.constrain_distance_min(regulator, mcu, 8)

# 4. Compile the Hardware
print("Compiling hardware...")
board.compile(
    project_name="iot_node",
    generate_bom=True,
    auto_route=True
)
print("Done!")
