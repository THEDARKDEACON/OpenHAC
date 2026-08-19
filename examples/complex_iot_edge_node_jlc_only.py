"""
complex_iot_edge_node_jlc_only.py — multi-module JLC-style bring-up board (non-flight).

Uses LCSC-oriented ``generic_name`` parts and the SQLite catalog (seed or ``sync_jlc``).

Compile (netlist/BOM only, no KiCad pcbnew layout):

    OPENHAC_SKIP_LAYOUT=1 python -m openhac compile \\
        examples/complex_iot_edge_node_jlc_only.py -o build --name iot_edge --no-route --no-schematic

Full schematic + PCB (requires DB rows, KiCad paths, and time):

    python -m openhac compile examples/complex_iot_edge_node_jlc_only.py -o build --name iot_edge
"""

from __future__ import annotations

from openhac.core.net import Net
from openhac.core import Board
from openhac.core.base import Module, Component


class PowerModule(Module):
    """Buck + LDO + indicators (same LCSC-style generics as flight power bring-up)."""

    def __init__(self) -> None:
        super().__init__("PowerModule")

        self.vbat = Net("VBAT")
        self.gnd = Net("GND")
        self.v5 = Net("5V")
        self.v3v3 = Net("3V3")

        self.buck = self.add(Component("BUCK_TPS63001DRCR"))
        self.l_buck = self.add(Component("INDUCTOR_2R2_2520"))
        self.cin_10u = self.add(Component("C_10UF_0805"))
        self.cin_100n = self.add(Component("C_100NF_0603"))
        self.cout5v_22u = self.add(Component("C_22UF_0805"))
        self.cout5v_100n = self.add(Component("C_100NF_0603"))
        self.ldo = self.add(Component("LDO_LDL1117S33R"))
        self.cldo_in = self.add(Component("C_10UF_0805"))
        self.cldo_out_10u = self.add(Component("C_10UF_0805"))
        self.cldo_out_100n = self.add(Component("C_100NF_0603"))
        self.r_fb1 = self.add(Component("R_100K_0603"))
        self.r_fb2 = self.add(Component("R_32K4_0603"))
        self.led_pwr = self.add(Component("LED_GREEN_0603"))
        self.r_led = self.add(Component("R_1K_0603"))

        vbat_fused = Net("VBAT_FUSED")

        self.cin_10u["1"] += vbat_fused
        self.cin_10u["2"] += self.gnd
        self.cin_100n["1"] += vbat_fused
        self.cin_100n["2"] += self.gnd

        self.buck["VIN"] += vbat_fused
        self.buck["GND"] += self.gnd
        self.buck["L1"] += self.l_buck["1"]
        self.l_buck["2"] += self.v5
        self.buck["FB"] += Net("FB_5V")

        self.r_fb1["1"] += self.v5
        self.r_fb1["2"] += Net("FB_5V")
        self.r_fb2["1"] += Net("FB_5V")
        self.r_fb2["2"] += self.gnd

        self.cout5v_22u["1"] += self.v5
        self.cout5v_22u["2"] += self.gnd
        self.cout5v_100n["1"] += self.v5
        self.cout5v_100n["2"] += self.gnd

        self.cldo_in["1"] += self.v5
        self.cldo_in["2"] += self.gnd
        self.ldo["IN"] += self.v5
        self.ldo["GND"] += self.gnd
        self.ldo["OUT"] += self.v3v3

        self.cldo_out_10u["1"] += self.v3v3
        self.cldo_out_10u["2"] += self.gnd
        self.cldo_out_100n["1"] += self.v3v3
        self.cldo_out_100n["2"] += self.gnd

        self.r_led["1"] += self.v5
        self.r_led["2"] += Net("LED_PWR_NODE")
        self.led_pwr["A"] += Net("LED_PWR_NODE")
        self.led_pwr["K"] += self.gnd

        self.source_current_max_ma = {"5V": 2000, "3V3": 800}
        self.pwr_5v = self.declare_interface("pwr_5v", self.v5, self.gnd)
        self.pwr_3v3 = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)


class EdgeHostModule(Module):
    """Minimal host MCU stub (SOIC-8) — CAN controller side + status LED."""

    def __init__(self) -> None:
        super().__init__("EdgeHostModule")

        self.v3v3 = Net("3V3")
        self.gnd = Net("GND")

        self.mcu = self.add(Component("MCU_EDGE_STUB_SOIC8"))
        self.c_dec1 = self.add(Component("C_100NF_0402"))
        self.c_dec2 = self.add(Component("C_100NF_0402"))
        self.led = self.add(Component("LED_BLUE_0603"))
        self.r_led = self.add(Component("R_1K_0603"))

        self.can_tx = Net("HOST_CAN_TX")
        self.can_rx = Net("HOST_CAN_RX")
        self.nrst = Net("HOST_NRST")

        self.mcu["VDD"] += self.v3v3
        self.mcu["VSS"] += self.gnd
        self.mcu["CAN_TX"] += self.can_tx
        self.mcu["CAN_RX"] += self.can_rx
        self.mcu["NRST"] += self.nrst
        self.r_nrst = self.add(Component("R_1K_0603"))
        self.r_nrst["1"] += self.nrst
        self.r_nrst["2"] += self.v3v3

        self.c_dec1["1"] += self.v3v3
        self.c_dec1["2"] += self.gnd
        self.c_dec2["1"] += self.v3v3
        self.c_dec2["2"] += self.gnd

        self.r_led["1"] += self.v3v3
        self.r_led["2"] += Net("HOST_LED_NODE")
        self.led["A"] += Net("HOST_LED_NODE")
        self.led["K"] += self.gnd

        self.max_current_draw_ma = {"3V3": 80}
        self.pwr = self.declare_interface("pwr", self.v3v3, self.gnd)
        self.can = self.declare_interface("can", self.can_tx, self.can_rx, self.gnd)


class CANModule(Module):
    """TJA1051 CAN transceiver (LCSC-style)."""

    def __init__(self) -> None:
        super().__init__("CANModule")

        self.v3v3 = Net("3V3")
        self.gnd = Net("GND")

        self.can = self.add(Component("CAN_TJA1051"))
        self.c_vdd = self.add(Component("C_100NF_0603"))

        self.can["VCC"] += self.v3v3
        self.can["GND"] += self.gnd
        self.c_vdd["1"] += self.v3v3
        self.c_vdd["2"] += self.gnd

        self.tx = Net("CAN_TX")
        self.rx = Net("CAN_RX")
        self.can["TXD"] += self.tx
        self.can["RXD"] += self.rx

        self.can_h = Net("CAN_H")
        self.can_l = Net("CAN_L")
        self.can["CANH"] += self.can_h
        self.can["CANL"] += self.can_l
        self.can["S"] += self.gnd
        self.r_term = self.add(Component("R_120_0603"))
        self.r_term["1"] += self.can_h
        self.r_term["2"] += self.can_l

        self.max_current_draw_ma = {"3V3": 10}
        self.pwr = self.declare_interface("pwr", self.v3v3, self.gnd)
        self.can_iface = self.declare_interface("can", self.tx, self.rx, self.gnd)


def build_board() -> Board:
    board = Board(
        size_mm=(46.0, 42.0),
        layers=4,
        strict=False,
        declared_supply_voltages_v={"VBAT": 16.8, "5V": 5.0, "3V3": 3.3},
    )

    power = PowerModule()
    host = EdgeHostModule()
    can = CANModule()

    board.add_module(power)
    board.add_module(host)
    board.add_module(can)

    board.connect(power.pwr_3v3, host.pwr)
    board.connect(power.pwr_3v3, can.pwr)
    board.connect(host.can, can.can_iface)

    board.declare_power_rail("VBAT", Net("VBAT"))
    board.declare_power_rail("5V", Net("5V"))
    board.declare_power_rail("3V3", Net("3V3"))
    board.declare_power_rail("GND", Net("GND"))
    board.declare_rail_conversion("VBAT", "5V", efficiency=0.92)
    board.declare_rail_conversion("5V", "3V3", efficiency=0.85)

    board.constrain_edge(power, edge="TOP")
    board.constrain_edge(can, edge="RIGHT")
    board.constrain_distance_min(power, host, min_distance_mm=8.0)
    board.constrain_distance_max(host, can, 25.0)

    board.declare_copper_pour_intent(Net("GND"), layer="F.Cu", purpose="ground")
    board.declare_copper_pour_intent(Net("GND"), layer="B.Cu", purpose="ground")

    for x, y in [(3.0, 3.0), (43.0, 3.0), (3.0, 39.0), (43.0, 39.0)]:
        board.declare_mounting_hole(x, y, 3.2, note=f"M3 at ({x},{y})")

    return board


def main() -> None:
    b = build_board()
    b.compile(
        project_name="iot_edge",
        generate_bom=True,
        export_schematic=True,
        auto_route=True,
    )


if __name__ == "__main__":
    main()
