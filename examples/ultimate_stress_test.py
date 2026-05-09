"""
ultimate_stress_test.py — The Motherboard Compilation Stress Test

This script models a high-density "Compute Module Carrier Motherboard".
It is designed to crush the compiler with hundreds of components, 
deep hierarchical trees, massive parallel buses (PCIe, RGMII, USB), 
and dense power sequencing networks.

Key Motherboard Features:
1. ATX Power Supply Network (12V, 5V, 3V3, 1V8, 1V2, 0V9) with cascaded switchers.
2. Power Sequencer / BMC (Board Management Controller) using an ESP32-S3.
3. Compute Module Core (representing a 200-pin high-density SoM).
4. PCIe Gen3 x4 NVMe M.2 Slot.
5. Gigabit Ethernet PHY (RGMII) + MagJack.
6. 4-Port USB 2.0 Hub + Type-A Connectors.
7. HDMI output with high-speed ESD protection arrays.
8. Dozens of decoupling capacitors and pull-up arrays for solver stress.

Compile Command:
OPENHAC_SCHEMATIC_MULTI_SHEET=1 OPENHAC_AUTO_BOARD_UTILIZATION=0.65 python3 -m openhac.cli compile examples/ultimate_stress_test.py --name cm_motherboard --auto-enrich-board --deoverlap-iters 1000 --no-route
"""

from __future__ import annotations
import math

from openhac.core import Board
from openhac.core.base import Component, Module
from openhac.core.net import Net


def MockComp(name: str, pin_count: int = 0, pin_dict: dict | None = None, lcsc_id: str | None = None) -> Component:
    """Helper to guarantee compilation without DB lookup failures."""
    if pin_dict is None:
        pin_dict = {str(i): (f"P{i}", "passive") for i in range(1, pin_count + 1)}
    kwargs = {"pins": pin_dict}
    if lcsc_id:
        kwargs["lcsc_id"] = lcsc_id
    return Component(name, **kwargs)


class ATXPowerSupply(Module):
    def __init__(self) -> None:
        super().__init__("ATX_PowerSupply")
        self.schematic_layer = 0

        self.v12 = Net("12V")
        self.v5 = Net("5V")
        self.v3v3 = Net("3V3")
        self.v1v8 = Net("1V8")
        self.v1v2 = Net("1V2")
        self.v0v9 = Net("0V9")
        self.gnd = Net("GND")

        # ATX 24-Pin Connector Stub
        self.atx = self.add(MockComp("CONN_ATX_24PIN", 24))
        self.atx["1"] += self.v3v3; self.atx["2"] += self.v3v3
        self.atx["10"] += self.v12; self.atx["11"] += self.v12
        for p in ["3", "5", "7", "15", "17", "18", "19", "24"]:
            self.atx[p] += self.gnd
        self.atx["4"] += self.v5; self.atx["6"] += self.v5; self.atx["21"] += self.v5
        self.atx["22"] += self.v5; self.atx["23"] += self.v5
        
        buck_pins = {"1": ("IN", "power_in"), "2": ("GND", "power_in"), "3": ("SW", "power_out")}
        
        # 1.8V Buck (from 5V)
        self.buck_1v8 = self.add(MockComp("BUCK_1V8", pin_dict=buck_pins))
        self.l_1v8 = self.add(MockComp("INDUCTOR_4R7_2520", 2))
        self.buck_1v8["1"] += self.v5; self.buck_1v8["2"] += self.gnd
        self.buck_1v8["3"] += self.l_1v8["1"]; self.l_1v8["2"] += self.v1v8
        
        # 1.2V Buck (from 5V)
        self.buck_1v2 = self.add(MockComp("BUCK_1V2", pin_dict=buck_pins))
        self.l_1v2 = self.add(MockComp("INDUCTOR_2R2_2520", 2))
        self.buck_1v2["1"] += self.v5; self.buck_1v2["2"] += self.gnd
        self.buck_1v2["3"] += self.l_1v2["1"]; self.l_1v2["2"] += self.v1v2
        
        # 0.9V Buck (Core voltage from 5V)
        self.buck_0v9 = self.add(MockComp("BUCK_0V9", pin_dict=buck_pins))
        self.l_0v9 = self.add(MockComp("INDUCTOR_1R0_2520", 2))
        self.buck_0v9["1"] += self.v5; self.buck_0v9["2"] += self.gnd
        self.buck_0v9["3"] += self.l_0v9["1"]; self.l_0v9["2"] += self.v0v9

        # Massive input/output bulk decoupling
        for rail, n_caps in [(self.v12, 4), (self.v5, 6), (self.v3v3, 6), (self.v1v8, 4), (self.v1v2, 4), (self.v0v9, 8)]:
            for i in range(n_caps):
                c = self.add(Component("C_22UF_0805"))
                c["1"] += rail; c["2"] += self.gnd

        # Interfaces
        self.pwr_12v = self.declare_interface("pwr_12v", self.v12, self.gnd)
        self.pwr_5v = self.declare_interface("pwr_5v", self.v5, self.gnd)
        self.pwr_3v3 = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)
        self.pwr_1v8 = self.declare_interface("pwr_1v8", self.v1v8, self.gnd)
        self.pwr_1v2 = self.declare_interface("pwr_1v2", self.v1v2, self.gnd)
        self.pwr_0v9 = self.declare_interface("pwr_0v9", self.v0v9, self.gnd)


class BoardManagementController(Module):
    """ESP32-S3 used as an ATX Power Sequencer & BMC"""
    def __init__(self) -> None:
        super().__init__("BMC_SuperIO")
        self.schematic_layer = 1

        self.v3v3 = Net("3V3_BMC")
        self.gnd = Net("GND")
        
        mcu_pins = {"1": ("3V3", "power_in"), "2": ("GND", "power_in"), "3": ("IO4", "bidirectional"), "4": ("IO5", "bidirectional"), "5": ("IO6", "bidirectional"), "6": ("IO7", "bidirectional"), "7": ("IO8", "bidirectional"), "8": ("IO9", "bidirectional")}
        # Trigger 3D download for this specific LCSC ID if it exists, otherwise fallback to our pins!
        self.mcu = self.add(MockComp("ESP32-S3-WROOM-1", pin_dict=mcu_pins, lcsc_id="C701341"))
        self.mcu["1"] += self.v3v3
        self.mcu["2"] += self.gnd
        
        # Flash / PSRAM decoupling
        for _ in range(4):
            c = self.add(Component("C_100NF_0402"))
            c["1"] += self.v3v3; c["2"] += self.gnd
            
        # Sequencing outputs (Enables for bucks)
        self.en_5v = Net("EN_5V")
        self.en_1v8 = Net("EN_1V8")
        self.en_1v2 = Net("EN_1V2")
        self.en_0v9 = Net("EN_0V9")
        
        self.mcu["3"] += self.en_5v
        self.mcu["4"] += self.en_1v8
        self.mcu["5"] += self.en_1v2
        self.mcu["6"] += self.en_0v9
        
        self.i2c_sda = Net("BMC_I2C_SDA")
        self.i2c_scl = Net("BMC_I2C_SCL")
        self.mcu["7"] += self.i2c_sda
        self.mcu["8"] += self.i2c_scl
        
        # I2C Pull-ups
        self.r_sda = self.add(Component("R_4K7_0402"))
        self.r_scl = self.add(Component("R_4K7_0402"))
        self.r_sda["1"] += self.v3v3; self.r_sda["2"] += self.i2c_sda
        self.r_scl["1"] += self.v3v3; self.r_scl["2"] += self.i2c_scl

        self.pwr = self.declare_interface("pwr", self.v3v3, self.gnd)
        self.i2c = self.declare_interface("i2c", self.i2c_sda, self.i2c_scl, self.gnd)


class ComputeModule(Module):
    """200-pin Compute Module Carrier Connector + Aggressive Decoupling"""
    def __init__(self) -> None:
        super().__init__("SoM_Core")
        self.schematic_layer = 2
        
        self.v5 = Net("5V")
        self.v3v3 = Net("3V3")
        self.v1v8 = Net("1V8")
        self.v1v2 = Net("1V2")
        self.v0v9 = Net("0V9")
        self.gnd = Net("GND")
        
        # Dual DF40 100-pin connectors
        self.conn_a = self.add(MockComp("CONN_DF40_100PIN", 100))
        self.conn_b = self.add(MockComp("CONN_DF40_100PIN", 100))
        
        # Wire Power and Ground across dozens of pins
        for i in range(1, 20, 2):
            self.conn_a[str(i)] += self.v5
            self.conn_a[str(i+1)] += self.gnd
            self.conn_b[str(i)] += self.v3v3
            self.conn_b[str(i+1)] += self.gnd
            
        for i in range(21, 40, 2):
            self.conn_a[str(i)] += self.v1v8
            self.conn_a[str(i+1)] += self.gnd
            self.conn_b[str(i)] += self.v1v2
            self.conn_b[str(i+1)] += self.gnd
            
        for i in range(41, 60, 2):
            self.conn_a[str(i)] += self.v0v9
            self.conn_a[str(i+1)] += self.gnd

        # Massive SoM Decoupling Array (50 capacitors)
        for _ in range(20):
            c = self.add(Component("C_100NF_0201"))
            c["1"] += self.v0v9; c["2"] += self.gnd
        for _ in range(10):
            c = self.add(Component("C_100NF_0402"))
            c["1"] += self.v1v2; c["2"] += self.gnd
        for _ in range(10):
            c = self.add(Component("C_100NF_0402"))
            c["1"] += self.v1v8; c["2"] += self.gnd
        for _ in range(10):
            c = self.add(Component("C_1UF_0402"))
            c["1"] += self.v3v3; c["2"] += self.gnd

        # High Speed Buses
        self.pcie_tx_p = [Net(f"PCIE_TX{i}_P") for i in range(4)]
        self.pcie_tx_n = [Net(f"PCIE_TX{i}_N") for i in range(4)]
        self.pcie_rx_p = [Net(f"PCIE_RX{i}_P") for i in range(4)]
        self.pcie_rx_n = [Net(f"PCIE_RX{i}_N") for i in range(4)]
        self.pcie_clk_p = Net("PCIE_CLK_P")
        self.pcie_clk_n = Net("PCIE_CLK_N")
        self.pcie_rst = Net("PCIE_RST")

        # RGMII (Gigabit Ethernet)
        self.rgmii_txc = Net("RGMII_TXC")
        self.rgmii_tx_ctl = Net("RGMII_TX_CTL")
        self.rgmii_txd = [Net(f"RGMII_TXD{i}") for i in range(4)]
        self.rgmii_rxc = Net("RGMII_RXC")
        self.rgmii_rx_ctl = Net("RGMII_RX_CTL")
        self.rgmii_rxd = [Net(f"RGMII_RXD{i}") for i in range(4)]
        self.mdc = Net("MDIO_MDC")
        self.mdio = Net("MDIO_DATA")
        
        # HDMI
        self.hdmi_clk_p = Net("HDMI_CLK_P")
        self.hdmi_clk_n = Net("HDMI_CLK_N")
        self.hdmi_d0_p = Net("HDMI_D0_P")
        self.hdmi_d0_n = Net("HDMI_D0_N")
        self.hdmi_d1_p = Net("HDMI_D1_P")
        self.hdmi_d1_n = Net("HDMI_D1_N")
        self.hdmi_d2_p = Net("HDMI_D2_P")
        self.hdmi_d2_n = Net("HDMI_D2_N")
        
        # USB 2.0 Host
        self.usb_dp = Net("USB_HOST_DP")
        self.usb_dn = Net("USB_HOST_DN")

        # Mock pinning out high speed buses to the connector
        for i in range(4):
            self.conn_a[str(61 + i*2)] += self.pcie_tx_p[i]
            self.conn_a[str(62 + i*2)] += self.pcie_tx_n[i]
            self.conn_a[str(71 + i*2)] += self.pcie_rx_p[i]
            self.conn_a[str(72 + i*2)] += self.pcie_rx_n[i]

        self.conn_b["61"] += self.hdmi_clk_p; self.conn_b["62"] += self.hdmi_clk_n
        self.conn_b["63"] += self.hdmi_d0_p;  self.conn_b["64"] += self.hdmi_d0_n
        
        # BMC I2C Management
        self.i2c_sda = Net("SOM_I2C_SDA")
        self.i2c_scl = Net("SOM_I2C_SCL")
        self.conn_a["81"] += self.i2c_sda
        self.conn_a["82"] += self.i2c_scl
        
        # Interfaces
        self.pwr_5v = self.declare_interface("pwr_5v", self.v5, self.gnd)
        self.pwr_3v3 = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)
        self.pwr_1v8 = self.declare_interface("pwr_1v8", self.v1v8, self.gnd)
        self.pwr_1v2 = self.declare_interface("pwr_1v2", self.v1v2, self.gnd)
        self.pwr_0v9 = self.declare_interface("pwr_0v9", self.v0v9, self.gnd)
        self.i2c = self.declare_interface("i2c", self.i2c_sda, self.i2c_scl, self.gnd)


class NVMeSlot(Module):
    """M.2 Key M Slot for PCIe x4 NVMe SSDs"""
    def __init__(self) -> None:
        super().__init__("M2_NVMe_Slot")
        self.schematic_layer = 3
        
        self.v3v3 = Net("3V3")
        self.gnd = Net("GND")
        
        self.m2 = self.add(MockComp("CONN_M2_KEY_M_75PIN", 75))
        
        # Power Delivery to SSD (up to 3A)
        for p in ["2", "4", "70", "72", "74"]:
            self.m2[p] += self.v3v3
        for p in ["3", "5", "11", "21", "27", "33", "39", "45", "51", "57", "71", "73", "75"]:
            self.m2[p] += self.gnd
            
        # PCIe AC Coupling Capacitors (TX side)
        self.pcie_tx_p = [Net(f"M2_TX{i}_P") for i in range(4)]
        self.pcie_tx_n = [Net(f"M2_TX{i}_N") for i in range(4)]
        self.pcie_rx_p = [Net(f"M2_RX{i}_P") for i in range(4)]
        self.pcie_rx_n = [Net(f"M2_RX{i}_N") for i in range(4)]
        
        for i in range(4):
            c_p = self.add(Component("C_220NF_0402"))
            c_n = self.add(Component("C_220NF_0402"))
            c_p["2"] += self.pcie_tx_p[i]; c_n["2"] += self.pcie_tx_n[i]
            
        self.pwr = self.declare_interface("pwr", self.v3v3, self.gnd)


class GigabitEthernet(Module):
    """RTL8211F PHY + MagJack"""
    def __init__(self) -> None:
        super().__init__("GbE_PHY")
        self.schematic_layer = 3
        
        self.v3v3 = Net("3V3")
        self.v1v2 = Net("1V2")
        self.gnd = Net("GND")
        
        phy_pins = {"1": ("VDD33", "power_in"), "2": ("GND", "power_in"), "3": ("VDD12", "power_in")}
        for i in range(4):
            phy_pins[str(4 + i*2)] = (f"MDI{i}_P", "bidirectional")
            phy_pins[str(5 + i*2)] = (f"MDI{i}_N", "bidirectional")
            
        self.phy = self.add(MockComp("PHY_RTL8211F", pin_dict=phy_pins, lcsc_id="C2846353"))
        self.magjack = self.add(MockComp("CONN_MAGJACK_RJ45", 12))
        
        self.phy["1"] += self.v3v3; self.phy["2"] += self.gnd
        self.phy["3"] += self.v1v2
        
        for _ in range(6):
            c = self.add(Component("C_100NF_0402"))
            c["1"] += self.v3v3; c["2"] += self.gnd
            
        # MDI Pairs to MagJack
        for i in range(4):
            self.phy[str(4 + i*2)] += self.magjack[str(1 + i*2)]
            self.phy[str(5 + i*2)] += self.magjack[str(2 + i*2)]
            
        self.pwr_3v3 = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)
        self.pwr_1v2 = self.declare_interface("pwr_1v2", self.v1v2, self.gnd)


class USBHub(Module):
    """FE1.1s USB 2.0 4-Port Hub"""
    def __init__(self) -> None:
        super().__init__("USB2_Hub")
        self.schematic_layer = 3
        
        self.v5 = Net("5V")
        self.v3v3 = Net("3V3")
        self.gnd = Net("GND")
        
        hub_pins = {"1": ("VDD5", "power_in"), "2": ("GND", "power_in"), "3": ("VDD33", "power_in"), "4": ("XIN", "input"), "5": ("XOUT", "output")}
        for i in range(4):
            hub_pins[str(6 + i*2)] = (f"DP{i}", "bidirectional")
            hub_pins[str(7 + i*2)] = (f"DM{i}", "bidirectional")
            
        self.hub = self.add(MockComp("HUB_FE1.1S", pin_dict=hub_pins, lcsc_id="C43621"))
        self.hub["1"] += self.v5; self.hub["2"] += self.gnd
        self.hub["3"] += self.v3v3
        
        self.xtal = self.add(MockComp("XTAL_12MHZ_SMD", 2))
        self.hub["4"] += self.xtal["1"]
        self.hub["5"] += self.xtal["2"]
        
        for i in range(4):
            port = self.add(MockComp("CONN_USB_A", 4))
            port["1"] += self.v5; port["4"] += self.gnd
            port["2"] += Net(f"HUB_DP{i}")
            port["3"] += Net(f"HUB_DN{i}")
            self.hub[str(6 + i*2)] += Net(f"HUB_DP{i}")
            self.hub[str(7 + i*2)] += Net(f"HUB_DN{i}")
            
            # ESD Protection
            esd = self.add(MockComp("ESD_SRV05_4", 6))
            esd["5"] += self.v5; esd["2"] += self.gnd
            esd["1"] += Net(f"HUB_DP{i}"); esd["3"] += Net(f"HUB_DN{i}")

        self.pwr_5v = self.declare_interface("pwr_5v", self.v5, self.gnd)
        self.pwr_3v3 = self.declare_interface("pwr_3v3", self.v3v3, self.gnd)


def build_board() -> Board:
    # Large format board for the complex motherboards
    b = Board(size_mm=(170.0, 170.0), layers=6, strict=False)

    psu = ATXPowerSupply()
    bmc = BoardManagementController()
    som = ComputeModule()
    nvme = NVMeSlot()
    gbe = GigabitEthernet()
    usb = USBHub()

    b.add_module(psu)
    b.add_module(bmc)
    b.add_module(som)
    b.add_module(nvme)
    b.add_module(gbe)
    b.add_module(usb)

    # Power Distribution Network (PDN)
    b.connect(psu.pwr_5v, som.pwr_5v)
    b.connect(psu.pwr_5v, usb.pwr_5v)
    
    b.connect(psu.pwr_3v3, bmc.pwr)
    b.connect(psu.pwr_3v3, som.pwr_3v3)
    b.connect(psu.pwr_3v3, nvme.pwr)
    b.connect(psu.pwr_3v3, gbe.pwr_3v3)
    b.connect(psu.pwr_3v3, usb.pwr_3v3)
    
    b.connect(psu.pwr_1v8, som.pwr_1v8)
    
    b.connect(psu.pwr_1v2, som.pwr_1v2)
    b.connect(psu.pwr_1v2, gbe.pwr_1v2)
    
    b.connect(psu.pwr_0v9, som.pwr_0v9)

    # I2C Management Bus
    b.connect(bmc.i2c, som.i2c) if hasattr(som, "i2c") else None

    # Power Rails declarations
    b.declare_power_rail("12V", Net("12V"))
    b.declare_power_rail("5V", Net("5V"))
    b.declare_power_rail("3V3", Net("3V3"))
    b.declare_power_rail("1V8", Net("1V8"))
    b.declare_power_rail("1V2", Net("1V2"))
    b.declare_power_rail("0V9", Net("0V9"))
    b.declare_power_rail("GND", Net("GND"))

    # Geometric Physical Layout Constraints (Mini-ITX Style placement)
    b.constrain_edge(psu, edge="TOP")
    b.constrain_edge(nvme, edge="BOTTOM")
    b.constrain_edge(usb, edge="LEFT")
    b.constrain_edge(gbe, edge="LEFT")
    
    # Keep high-speed interfaces close to SoM
    b.constrain_distance_max(nvme, som, 30.0)
    b.constrain_distance_max(gbe, som, 40.0)

    # Manufacturing Intents
    b.declare_copper_pour_intent(Net("GND"), layer="In1.Cu", purpose="ground_plane")
    b.declare_copper_pour_intent(Net("GND"), layer="In4.Cu", purpose="ground_plane")
    b.declare_copper_pour_intent(Net("3V3"), layer="In2.Cu", purpose="power_plane")
    b.declare_copper_pour_intent(Net("5V"), layer="In3.Cu", purpose="power_plane")
    
    # Mini-ITX Mounting Holes (approximate)
    for x, y in [(10.0, 10.0), (160.0, 10.0), (10.0, 160.0), (160.0, 160.0)]:
        b.declare_mounting_hole(x, y, 3.2, note=f"Mini-ITX Mount")

    return b


if __name__ == "__main__":
    board = build_board()
    board.compile(project_name="cm_motherboard", generate_bom=True, export_schematic=True, auto_route=False)
