import os
from openhac.core.base import Component, Module, Net
from openhac.core.board import Board

def MockComp(name: str, pin_count: int = 0, pin_dict: dict | None = None, lcsc_id: str | None = None) -> Component:
    if pin_dict is None:
        pin_dict = {str(i): (f"P{i}", "passive") for i in range(1, pin_count + 1)}
    kwargs = {"pins": pin_dict}
    if lcsc_id:
        kwargs["lcsc_id"] = lcsc_id
    return Component(name, **kwargs)


class EmbeddedController(Module):
    """ENE KB3940 / ITE IT8518E - Keyboard & Power Controller"""
    def __init__(self) -> None:
        super().__init__("KBC_EC")
        self.schematic_layer = 1
        self.v3v3_alw = Net("3V3_ALW")
        self.gnd = Net("GND")
        self.ec = self.add(MockComp("IC_IT8518E_LQFP128", 128))
        for p in ["11", "24", "33", "67", "73", "94", "109", "116"]: self.ec[p] += self.v3v3_alw
        for p in ["12", "25", "34", "68", "74", "95", "110", "117"]: self.ec[p] += self.gnd
        self.pwrbtn_n = Net("PWRBTN#")
        self.ec["125"] += self.pwrbtn_n
        for _ in range(8):
            c = self.add(Component("C_100NF_0402"))
            c["1"] += self.v3v3_alw; c["2"] += self.gnd

class DDR3_SODIMM(Module):
    def __init__(self, channel_name: str) -> None:
        super().__init__(f"DDR3_SLOT_{channel_name}")
        self.schematic_layer = 2
        self.v1v5 = Net("1V5_S3")
        self.gnd = Net("GND")
        self.slot = self.add(MockComp("CONN_SODIMM_204PIN", 204))
        self.dq = [Net(f"DDR_{channel_name}_DQ{i}") for i in range(64)]
        for i in range(64): self.slot[str(10 + i)] += self.dq[i]
        for p in range(1, 204, 6):
            self.slot[str(p)] += self.v1v5; self.slot[str(p+1)] += self.gnd
        for _ in range(12):
            c = self.add(Component("C_1UF_0402"))
            c["1"] += self.v1v5; c["2"] += self.gnd

class AMD_APU(Module):
    """AMD Trinity/Richland APU (FS1r2 or BGA)"""
    def __init__(self) -> None:
        super().__init__("AMD_APU_Trinity")
        self.schematic_layer = 3
        self.vcore = Net("VCC_CORE")
        self.vddnb = Net("VDD_NB")
        self.v1v5 = Net("1V5_S3")
        self.gnd = Net("GND")
        self.cpu = self.add(MockComp("IC_AMD_APU_BGA", 822))
        for _ in range(25):
            c = self.add(Component("C_10UF_0603"))
            c["1"] += self.vcore; c["2"] += self.gnd
        for _ in range(15):
            c = self.add(Component("C_10UF_0603"))
            c["1"] += self.vddnb; c["2"] += self.gnd

class AMD_FCH(Module):
    """AMD Hudson-M3 / Bolton FCH (Southbridge)"""
    def __init__(self) -> None:
        super().__init__("AMD_FCH")
        self.schematic_layer = 4
        self.v1v1 = Net("1V1_ALW")
        self.v3v3 = Net("3V3_S5")
        self.gnd = Net("GND")
        self.fch = self.add(MockComp("IC_FCH_HUDSON_BGA", 656))
        for _ in range(10):
            c = self.add(Component("C_1UF_0402"))
            c["1"] += self.v1v1; c["2"] += self.gnd

class DiscreteGPU(Module):
    """AMD Thames / Mars discrete GPU"""
    def __init__(self) -> None:
        super().__init__("AMD_GPU")
        self.schematic_layer = 5
        self.vga_core = Net("VGA_CORE")
        self.gnd = Net("GND")
        self.gpu = self.add(MockComp("IC_AMD_GPU_BGA", 700))
        for _ in range(20):
            c = self.add(Component("C_10UF_0603"))
            c["1"] += self.vga_core; c["2"] += self.gnd

class VRAM_GDDR3(Module):
    """1GB/2GB VRAM Block for Discrete GPU"""
    def __init__(self) -> None:
        super().__init__("VRAM_GDDR3")
        self.schematic_layer = 5
        self.v1v5_vga = Net("1V5_VGA")
        self.gnd = Net("GND")
        self.chips = [self.add(MockComp("IC_K4W2G1646C_FBGA96", 96)) for _ in range(4)]
        for chip in self.chips:
            for _ in range(4):
                c = self.add(Component("C_100NF_0402"))
                c["1"] += self.v1v5_vga; c["2"] += self.gnd

class SystemPower(Module):
    """TPS51125 Dual Buck + BQ24725 Battery Charger"""
    def __init__(self) -> None:
        super().__init__("System_Power")
        self.schematic_layer = 6
        self.vin = Net("DCBATOUT")
        self.gnd = Net("GND")
        self.v3v3 = Net("3V3_ALW")
        self.v5 = Net("5V_ALW")
        self.vcore = Net("VCC_CORE")
        
        self.tps51125 = self.add(MockComp("IC_TPS51125_QFN24", 24))
        self.bq24725 = self.add(MockComp("IC_BQ24725_RGN20", 20))
        self.bat_conn = self.add(MockComp("CONN_BATTERY_8PIN", 8))
        
        for _ in range(10):
            c = self.add(Component("C_10UF_1206"))
            c["1"] += self.vin; c["2"] += self.gnd

class WLAN_MiniPCIe(Module):
    """Half-Mini PCIe for Wi-Fi / Bluetooth"""
    def __init__(self) -> None:
        super().__init__("WLAN_Slot")
        self.schematic_layer = 7
        self.v3v3 = Net("3V3_S0")
        self.gnd = Net("GND")
        self.conn = self.add(MockComp("CONN_MINIPCIE_52PIN", 52))
        for p in ["2", "24", "39", "41", "52"]: self.conn[p] += self.v3v3
        for p in ["4", "9", "15", "18", "21", "26", "27", "29", "34", "35", "37", "40", "43", "50"]: self.conn[p] += self.gnd

class ThermalControl(Module):
    """SMSC EMC2103 Fan Controller & Sensor"""
    def __init__(self) -> None:
        super().__init__("Thermal_Fan")
        self.schematic_layer = 8
        self.v5 = Net("5V_ALW")
        self.gnd = Net("GND")
        self.fan_ic = self.add(MockComp("IC_EMC2103_DFN", 14))
        self.fan_hdr = self.add(MockComp("CONN_FAN_4PIN", 4))
        self.fan_hdr["1"] += self.gnd; self.fan_hdr["2"] += self.v5

class CardReader(Module):
    """Realtek RTS5229 PCIe SD Card Reader"""
    def __init__(self) -> None:
        super().__init__("Card_Reader")
        self.schematic_layer = 9
        self.v3v3 = Net("3V3_S0")
        self.gnd = Net("GND")
        self.ic = self.add(MockComp("IC_RTS5229_QFN", 48))
        self.slot = self.add(MockComp("CONN_SDCARD_12PIN", 12))
        c = self.add(Component("C_1UF_0402"))
        c["1"] += self.v3v3; c["2"] += self.gnd


# -----------------------------------------------------------------------------
# Main Board Assembly
# -----------------------------------------------------------------------------
board = Board(size_mm=(300, 220), layers=6, strict=False)

ec = EmbeddedController()
pwr = SystemPower()
cpu = AMD_APU()
fch = AMD_FCH()
gpu = DiscreteGPU()
vram = VRAM_GDDR3()
ram_a = DDR3_SODIMM("A")
ram_b = DDR3_SODIMM("B")
wlan = WLAN_MiniPCIe()
fan = ThermalControl()
card = CardReader()

# Attach modules
for m in [ec, pwr, cpu, fch, gpu, vram, ram_a, ram_b, wlan, fan, card]:
    board.add_module(m)

# Global net routing (simulating copper fills and net ties)
board.connect(pwr.gnd, cpu.gnd)
board.connect(pwr.gnd, fch.gnd)
board.connect(pwr.v3v3, ec.v3v3_alw)
board.connect(pwr.vcore, cpu.vcore)
board.connect(ram_a.v1v5, cpu.v1v5)
board.connect(ram_b.v1v5, cpu.v1v5)

# Connect memory buses
for i in range(64):
    board.connect(ram_a.dq[i], Net(f"CPU_MEM_A_DQ{i}"))
    board.connect(ram_b.dq[i], Net(f"CPU_MEM_B_DQ{i}"))
