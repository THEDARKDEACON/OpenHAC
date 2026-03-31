print("Starting OpenHaC test...")
from openhac.core import Board
from openhac.stdlib.power import LDO_5V, XT60_Input
from openhac.stdlib.mcu import ESP32_WROOM
print("Imports loaded.")

# 1. Define physical constraints
board = Board(size_mm=(50, 50), layers=2)
print("Board initialized.")

# 2. Instantiate high-level modules (Backed by real MPNs in the DB)
power_in = XT60_Input()
print("XT60_Input initialized.")
regulator = LDO_5V()
print("LDO_5V initialized.")
mcu = ESP32_WROOM()
print("MCU initialized.")

# 3. Declarative Interfacing (Agnostic to raw pins)
board.connect(power_in.v_out, regulator.v_in)
board.connect(regulator.v_out, mcu.power)
print("Connections made.")

# 4. Compile the Hardware
print("Compiling hardware...")
board.compile(
    project_name="iot_node",
    generate_bom=True,
    auto_route=True
)
print("Done!")
