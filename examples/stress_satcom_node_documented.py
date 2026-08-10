"""
stress_satcom_node_documented.py — stress test: many modules, lots of nets, multi-sheet schematic.

This example is designed to be:
- **Deterministic and offline** when compiled with a seed DB (no vendor APIs).
- **Documentation-forward**: many named nets, clear module interfaces, multi-sheet schematic.
- **Layout-safe**: you can set Board(size_mm=None) to auto-size before placement.

Recommended (offline, docs-grade):

    OPENHAC_SKIP_LAYOUT=1 openhac compile examples/stress_satcom_node_documented.py \\
      --name stress_satcom -o build --no-route \\
      --pre-seed-file seeds/stress_satcom_seed.json \\
      --schematic-strict

Full PCB generation (requires pcbnew + footprints; will auto-size if size_mm=None):

    openhac compile examples/stress_satcom_node_documented.py \\
      --name stress_satcom -o build --no-route --schematic-strict
"""

from __future__ import annotations

from openhac.core import Board
from openhac.core.base import Component, Module
from openhac.core.net import Net


class PowerTree(Module):
    def __init__(self) -> None:
        super().__init__("PowerTree")
        self.schematic_layer = 0  # Power sources on the left
        self.vbat = Net("VBAT")
        self.gnd = Net("GND")
        self.v5 = Net("5V")
        self.v3v3 = Net("3V3")

        self.buck = self.add(Component("BUCK_TPS63001DRCR"))
        self.l_buck = self.add(Component("INDUCTOR_2R2_2520"))
        self.cin = self.add(Component("C_10UF_0805"))
        self.cin2 = self.add(Component("C_100NF_0603"))
        self.cout = self.add(Component("C_22UF_0805"))
        self.ldo = self.add(Component("LDO_LDL1117S33R"))
        self.cldo = self.add(Component("C_10UF_0805"))
        self.cldo2 = self.add(Component("C_100NF_0603"))

        vbat_fused = self.vbat
        self.cin["1"] += vbat_fused
        self.cin["2"] += self.gnd
        self.cin2["1"] += vbat_fused
        self.cin2["2"] += self.gnd

        self.buck["VIN"] += vbat_fused
        self.buck["GND"] += self.gnd
        self.buck["L1"] += self.l_buck["1"]
        buck_fb = Net("BUCK_FB")
        self.buck["FB"] += buck_fb
        rfb1 = self.add(Component("R_1K_0603"))
        rfb2 = self.add(Component("R_1K_0603"))
        rfb1["1"] += self.v5
        rfb1["2"] += buck_fb
        rfb2["1"] += buck_fb
        rfb2["2"] += self.gnd
        self.l_buck["2"] += self.v5
        self.cout["1"] += self.v5
        self.cout["2"] += self.gnd

        self.ldo["IN"] += self.v5
        self.ldo["GND"] += self.gnd
        self.ldo["OUT"] += self.v3v3
        self.cldo["1"] += self.v3v3
        self.cldo["2"] += self.gnd
        self.cldo2["1"] += self.v3v3
        self.cldo2["2"] += self.gnd

        self.source_current_max_ma = {"5V": 1500, "3V3": 900}
        self.pwr_5v = self.declare_interface("pwr_5v", self.v5, self.gnd)
        self.pwr_3v3 = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)


class HostMCU(Module):
    def __init__(self, name: str, *, can_role: str) -> None:
        super().__init__(name)
        self.schematic_layer = 1  # MCU processing in the center
        self.v3v3 = Net("3V3")
        self.gnd = Net("GND")
        self.mcu = self.add(Component("MCU_EDGE_STUB_SOIC8"))
        self.dec1 = self.add(Component("C_100NF_0402"))
        self.dec2 = self.add(Component("C_100NF_0402"))
        self.bulk = self.add(Component("C_4U7_0603"))

        self.mcu["VDD"] += self.v3v3
        self.mcu["VSS"] += self.gnd
        self.dec1["1"] += self.v3v3
        self.dec1["2"] += self.gnd
        self.dec2["1"] += self.v3v3
        self.dec2["2"] += self.gnd
        self.bulk["1"] += self.v3v3
        self.bulk["2"] += self.gnd

        # Role-specific nets so the schematic has meaningful documentation.
        self.can_tx = Net(f"{can_role}_CAN_TX")
        self.can_rx = Net(f"{can_role}_CAN_RX")
        self.mcu["CAN_TX"] += self.can_tx
        self.mcu["CAN_RX"] += self.can_rx
        nrst = Net(f"{can_role}_NRST")
        self.mcu["NRST"] += nrst
        rst_pull = self.add(Component("R_1K_0603"))
        rst_pull["1"] += self.v3v3
        rst_pull["2"] += nrst

        self.max_current_draw_ma = {"3V3": 120}
        self.pwr = self.declare_interface("pwr", self.v3v3, self.gnd)
        self.can = self.declare_interface("can", self.can_tx, self.can_rx, self.gnd)


class CANTransceiver(Module):
    def __init__(self, name: str, *, bus_tag: str, ctrl_iface) -> None:
        super().__init__(name)
        self.schematic_layer = 2  # Physical transceivers on the right
        self.v3v3 = Net("3V3")
        self.gnd = Net("GND")
        self.can = self.add(Component("CAN_TJA1051"))
        self.c_vdd = self.add(Component("C_100NF_0603"))

        self.can["VCC"] += self.v3v3
        self.can["GND"] += self.gnd
        self.c_vdd["1"] += self.v3v3
        self.c_vdd["2"] += self.gnd
        # Tie standby low.
        self.can["S"] += self.gnd

        self.tx = Net(f"{bus_tag}_TX")
        self.rx = Net(f"{bus_tag}_RX")
        self.can["TXD"] += self.tx
        self.can["RXD"] += self.rx

        self.can_h = Net(f"{bus_tag}_H")
        self.can_l = Net(f"{bus_tag}_L")
        self.can["CANH"] += self.can_h
        self.can["CANL"] += self.can_l

        # Bus termination (documentation-friendly; satisfies ERC two-pin nets).
        term = self.add(Component("R_1K_0603"))
        term["1"] += self.can_h
        term["2"] += self.can_l

        # Connect to controller interface (documented cross-module link).
        # ctrl_iface signals are (tx, rx, gnd) per HostMCU.declare_interface("can", ...).
        try:
            self.tx += ctrl_iface.signals[0]
            self.rx += ctrl_iface.signals[1]
        except Exception:
            pass

        self.max_current_draw_ma = {"3V3": 15}
        self.pwr = self.declare_interface("pwr", self.v3v3, self.gnd)


class StatusLED(Module):
    def __init__(self, name: str, *, net_name: str) -> None:
        super().__init__(name)
        self.schematic_layer = 2  # Output LEDs on the right
        self.v3v3 = Net("3V3")
        self.gnd = Net("GND")
        self.led = self.add(Component("LED_BLUE_0603"))
        self.r = self.add(Component("R_1K_0603"))
        self.sig = Net(net_name)
        self.r["1"] += self.v3v3
        self.r["2"] += self.sig
        self.led["A"] += self.sig
        self.led["K"] += self.gnd
        self.max_current_draw_ma = {"3V3": 5}
        self.pwr = self.declare_interface("pwr", self.v3v3, self.gnd)


def build_board() -> Board:
    # Use autosize to avoid “board too small” UNSAT by construction.
    b = Board(size_mm=None, layers=4, strict=False, declared_supply_voltages_v={"VBAT": 16.8, "5V": 5.0, "3V3": 3.3})

    pwr = PowerTree()
    host_a = HostMCU("HostMCU_A", can_role="A")
    host_b = HostMCU("HostMCU_B", can_role="B")
    led_a = StatusLED("StatusLED_A", net_name="A_STATUS")
    led_b = StatusLED("StatusLED_B", net_name="B_STATUS")

    b.add_module(pwr)
    b.add_module(host_a)
    b.add_module(host_b)
    b.add_module(led_a)
    b.add_module(led_b)

    # Power distribution
    b.connect(pwr.pwr_3v3, host_a.pwr)
    b.connect(pwr.pwr_3v3, host_b.pwr)
    b.connect(pwr.pwr_3v3, led_a.pwr)
    b.connect(pwr.pwr_3v3, led_b.pwr)

    # Two CAN buses (documented)
    can_phy_a = CANTransceiver("CANPhy_A", bus_tag="CAN_A", ctrl_iface=host_a.can)
    can_phy_b = CANTransceiver("CANPhy_B", bus_tag="CAN_B", ctrl_iface=host_b.can)
    b.add_module(can_phy_a)
    b.add_module(can_phy_b)
    b.connect(pwr.pwr_3v3, can_phy_a.pwr)
    b.connect(pwr.pwr_3v3, can_phy_b.pwr)
    # Ensure interface validation sees >=2 pins per net by wiring the controller can nets
    # to the corresponding transceiver nets.
    b.connect(host_a.can, can_phy_a.declare_interface("ctrl", can_phy_a.tx, can_phy_a.rx, can_phy_a.gnd))
    b.connect(host_b.can, can_phy_b.declare_interface("ctrl", can_phy_b.tx, can_phy_b.rx, can_phy_b.gnd))

    # Rails for checks/manifests (reuse module nets — do not create duplicate Net objects)
    b.declare_power_rail("VBAT", pwr.vbat)
    b.declare_power_rail("5V", pwr.v5)
    b.declare_power_rail("3V3", pwr.v3v3)
    b.declare_power_rail("GND", pwr.gnd)
    b.declare_rail_conversion("VBAT", "5V", efficiency=0.92)
    b.declare_rail_conversion("5V", "3V3", efficiency=0.85)

    # Basic geometric hints (won’t block if autosize)
    b.constrain_edge(pwr, edge="TOP")
    b.constrain_edge(can_phy_a, edge="RIGHT")
    b.constrain_distance_min(pwr, host_a, min_distance_mm=8.0)
    b.constrain_distance_min(pwr, host_b, min_distance_mm=8.0)

    # Documentation-friendly pours and mounting
    b.declare_copper_pour_intent(Net("GND"), layer="F.Cu", purpose="ground")
    b.declare_copper_pour_intent(Net("GND"), layer="B.Cu", purpose="ground")
    for x, y in [(3.0, 3.0), (63.0, 3.0), (3.0, 43.0), (63.0, 43.0)]:
        b.declare_mounting_hole(x, y, 3.2, note=f"M3 at ({x},{y})")

    return b


def main() -> None:
    board = build_board()
    board.compile(project_name="stress_satcom", generate_bom=True, export_schematic=True, auto_route=False)


if __name__ == "__main__":
    main()

