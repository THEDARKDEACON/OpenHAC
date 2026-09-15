#!/usr/bin/env python3
"""
complex_zx7_400mini_welder.py — ZX7-400MINI LCD inverter welder interconnect

Recreates the factory wiring diagram of a ZX7-400MINI LCD ZKB MMA/MIG plant:

  1~220 Vac / 3~380 Vac  →  C253i DV ZLB rectifier  →  C253i DV LBB DC bus
  IGBT H-bridge + T1     →  D1–D6 output rectifier  →  L1 / HALL  →  XS1+/XS2−
  HV PSB aux             →  +24 V / +15 V
  ZX7-400MINI LCD ZKB    — gate drive, sense, feeder, panel
  EMIG-FEEDER            — 24 V wire-feed motor + torch
  C2B1 CKS32 Panel       — dual 8.8.8 displays + keys

Connector names (CN / JP / 4CN / 6CN) match the source drawing. Gate-drive
silicon is not shown on that drawing; TIM1 PWM on an STM32F103 stands in for
the ZKB control core.

Compile::

    OPENHAC_NO_NETWORK=1 OPENHAC_SCHEMATIC_MULTI_SHEET=1 \\
      python3 -m openhac.cli compile examples/complex_zx7_400mini_welder.py \\
      --name zx7_400mini_welder --target-kicad 10 --compile-goal handoff \\
      --no-route -o /tmp/openhac_zx7
"""

from __future__ import annotations

import sys
from pathlib import Path

_EX = Path(__file__).resolve().parent
if str(_EX) not in sys.path:
    sys.path.insert(0, str(_EX))

import openhac.core  # noqa: F401
from openhac.core import Board
from openhac.core.base import Module
from openhac.core.net import Net

from _offline_parts import (
    AMS1117_33,
    C_0603,
    C_0805,
    HEADER_1x04,
    HEADER_1x06,
    HEADER_1x08,
    R_0805,
    STM32F103C8,
    XTAL_8MHZ,
    mk_component as _mk,
    offline_part,
)


# ---------------------------------------------------------------------------
# Local parts (stock KiCad symbols + footprints)
# ---------------------------------------------------------------------------


def _hdr(n: int) -> dict:
    w = f"{n:02d}"
    return offline_part(
        generic_name=f"HDR_1x{w}",
        footprint=f"Connector_PinHeader_2.54mm:PinHeader_1x{w}_P2.54mm_Vertical",
        pins={i: (str(i), "passive") for i in range(1, n + 1)},
        category="Connector",
        symbol=f"Connector:Conn_01x{w}_Pin",
        package="PinHeader",
        description=f"1x{n} pin header",
    )


HEADER_1x02 = _hdr(2)
HEADER_1x03 = _hdr(3)
HEADER_1x05 = _hdr(5)

IGBT_TO247 = offline_part(
    generic_name="IRG4PF50W",
    footprint="Package_TO_SOT_THT:TO-247-3_Vertical",
    pins={1: ("G", "input"), 2: ("C", "passive"), 3: ("E", "passive")},
    category="transistor",
    symbol="Transistor_IGBT:IRG4PF50W",
    package="TO-247",
    mpn="IRG4PF50W",
    description="900 V IGBT (schematic stand-in for the ZX7 brick)",
)

D_PWR = lambda name: offline_part(
    generic_name=name,
    footprint="Diode_THT:D_DO-201_P15.24mm_Horizontal",
    pins={1: ("K", "passive"), 2: ("A", "passive")},
    category="Diode",
    symbol="Diode:1N5408",
    package="DO-201",
    mpn="1N5408",
    description="3 A rectifier / fast-recovery stand-in",
)

XFMR_1P2S = offline_part(
    generic_name="XFMR_INV_T1",
    footprint="Transformer_THT:Transformer_Toroid_Tapped_Horizontal_D14.0mm_Amidon-T50",
    pins={
        1: ("AA", "passive"),
        2: ("AB", "passive"),
        3: ("SA", "passive"),
        4: ("SB", "passive"),
        5: ("SC", "passive"),
        6: ("SD", "passive"),
    },
    category="Transformer",
    symbol="Device:Transformer_1P_2S",
    package="Toroid",
    description="Inverter transformer T1 (1 primary, 2 secondaries)",
)

XFMR_AUX = offline_part(
    generic_name="XFMR_AUX_HV",
    footprint="Transformer_THT:Transformer_Zeming_ZMPT101K",
    pins={
        1: ("AA", "passive"),
        2: ("AB", "passive"),
        3: ("SA", "passive"),
        4: ("SB", "passive"),
    },
    category="Transformer",
    symbol="Device:Transformer_1P_1S",
    package="ZMPT101K",
    description="HV PSB auxiliary transformer",
)

XFMR_CT = offline_part(
    generic_name="XFMR_CP1",
    footprint="Transformer_THT:Transformer_Zeming_ZMPT101K",
    pins={
        1: ("AA", "passive"),
        2: ("AB", "passive"),
        3: ("SA", "passive"),
        4: ("SB", "passive"),
    },
    category="Transformer",
    symbol="Device:Transformer_1P_1S",
    package="ZMPT101K",
    description="C253i DV LBB current transformer CP1",
)

L_OUT = lambda name: offline_part(
    generic_name=name,
    footprint="Inductor_THT:L_Toroid_Horizontal_D40.0mm_P48.26mm",
    pins={1: ("1", "passive"), 2: ("2", "passive")},
    category="Inductor",
    symbol="Device:L",
    package="Toroid",
    description="Welding output choke",
)

FAN_24V = offline_part(
    generic_name="FAN_24V",
    footprint="Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical",
    pins={1: ("1", "passive"), 2: ("2", "passive")},
    category="Motor",
    symbol="Motor:Fan",
    package="PinHeader",
    description="24 V cooling fan",
)

MOTOR_WF = offline_part(
    generic_name="MOTOR_WIRE_FEED",
    footprint="Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical",
    pins={1: ("1", "passive"), 2: ("2", "passive")},
    category="Motor",
    symbol="Motor:Motor_DC",
    package="PinHeader",
    description="24 V wire-feed motor M1",
)

SW_DPST = offline_part(
    generic_name="SW_POWER_DPST",
    footprint="Button_Switch_THT:SW_Push_2P1T_Toggle_CK_PVA1xxH1xxxxxxV2",
    pins={1: ("1", "passive"), 2: ("2", "passive"), 3: ("3", "passive"), 4: ("4", "passive")},
    category="Switch",
    symbol="Switch:SW_DPST",
    package="Toggle",
    description="Front-panel power switch",
)

SW_KEY = lambda name: offline_part(
    generic_name=name,
    footprint="Button_Switch_THT:SW_PUSH_6mm",
    pins={1: ("A", "passive"), 2: ("B", "passive")},
    category="Switch",
    symbol="Switch:SW_SPST",
    package="6mm",
    description="Panel pushbutton",
)

R_POT = lambda name: offline_part(
    generic_name=name,
    footprint="Potentiometer_THT:Potentiometer_Bourns_3296W_Vertical",
    pins={1: ("1", "passive"), 2: ("2", "passive"), 3: ("3", "passive")},
    category="Potentiometer",
    symbol="Device:R_Potentiometer",
    package="3296W",
    description="Panel encoder / pot",
)

SCREW_1 = lambda name: offline_part(
    generic_name=name,
    footprint="TerminalBlock_WAGO:TerminalBlock_WAGO_236-101_1x01_P5.00mm_45Degree",
    pins={1: ("Pin_1", "passive")},
    category="Connector",
    symbol="Connector:Screw_Terminal_01x01",
    package="WAGO-236",
    description="Single screw terminal",
)

SCREW_2 = lambda name: offline_part(
    generic_name=name,
    footprint="TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-1,5-2_1x02_P5.00mm_Horizontal",
    pins={1: ("Pin_1", "passive"), 2: ("Pin_2", "passive")},
    category="Connector",
    symbol="Connector:Screw_Terminal_01x02",
    package="MKDS-1.5",
    description="Dual screw terminal",
)

ACS712 = offline_part(
    generic_name="SENSOR_ACS712_20A",
    footprint="Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
    pins={
        1: ("IP+", "passive"),
        2: ("IP+_2", "passive"),
        3: ("IP-", "passive"),
        4: ("IP-_2", "passive"),
        5: ("GND", "power_in"),
        6: ("FILTER", "passive"),
        7: ("VIOUT", "output"),
        8: ("VCC", "power_in"),
    },
    category="Sensor",
    symbol="Sensor_Current:ACS712xLCTR-20A",
    package="SOIC-8",
    mpn="ACS712ELCTR-20A-T",
    description="Hall current sensor (HALL on XS2−)",
)

SEG7 = lambda name: offline_part(
    generic_name=name,
    footprint="Display_7Segment:CA56-12EWA",
    pins={
        1: ("e", "passive"),
        2: ("d", "passive"),
        3: ("DPX", "passive"),
        4: ("c", "passive"),
        5: ("g", "passive"),
        6: ("CA4", "passive"),
        7: ("b", "passive"),
        8: ("CA3", "passive"),
        9: ("CA2", "passive"),
        10: ("f", "passive"),
        11: ("a", "passive"),
        12: ("CA1", "passive"),
    },
    category="Display",
    symbol="Display_Character:CA56-12EWA",
    package="CA56",
    description="4-digit 7-segment (stand-in for panel 8.8.8)",
)


def _r(mod: Module, ref: str, ohms: str, a, b):
    c = mod.add(_mk(ref, R_0805(ref, ohms)))
    c[1] += a
    c[2] += b
    return c


def _c(mod: Module, ref: str, val: str, a, b, *, pkg: str = "0805"):
    data = C_0805(ref, val) if pkg == "0805" else C_0603(ref, val)
    c = mod.add(_mk(ref, data))
    c[1] += a
    c[2] += b
    return c


def _d(mod: Module, ref: str, anode, cathode):
    c = mod.add(_mk(ref, D_PWR(ref)))
    c[2] += anode
    c[1] += cathode
    return c


def _q(mod: Module, ref: str):
    return mod.add(_mk(ref, IGBT_TO247))


def _h(mod: Module, ref: str, n: int):
    table = {2: HEADER_1x02, 3: HEADER_1x03, 4: HEADER_1x04, 5: HEADER_1x05, 6: HEADER_1x06, 8: HEADER_1x08}
    return mod.add(_mk(ref, table[n]))


# ---------------------------------------------------------------------------
# INPUT — mains, power switch, earth
# ---------------------------------------------------------------------------


class AcMainsInput(Module):
    """U / W / V / EARTH and the front-panel POWER switch."""

    def __init__(self) -> None:
        super().__init__("AcMainsInput", schematic_sheet="INPUT", schematic_flow="power")
        self.u, self.w, self.v = Net("AC_U"), Net("AC_W"), Net("AC_V")
        self.u_sw, self.w_sw = Net("AC_U_SW"), Net("AC_W_SW")
        self.earth = Net("EARTH")
        tu = self.add(_mk("XS_U", SCREW_1("XS_U")))
        tw = self.add(_mk("XS_W", SCREW_1("XS_W")))
        tv = self.add(_mk("XS_V", SCREW_1("XS_V")))
        te = self.add(_mk("XS_EARTH", SCREW_1("XS_EARTH")))
        sw = self.add(_mk("SW_POWER", SW_DPST))
        tu[1] += self.u
        tw[1] += self.w
        tv[1] += self.v
        te[1] += self.earth
        sw[1] += self.u
        sw[2] += self.u_sw
        sw[3] += self.w
        sw[4] += self.w_sw
        self.draws_from("AC_U", ma=0)


# ---------------------------------------------------------------------------
# C253i DV ZLB — input rectifier / fan / sense harness
# ---------------------------------------------------------------------------


class C253iDvZlb(Module):
    """C253i DV ZLB: 3-phase bridge, C6, fan, CN1–CN4 / JP1–JP5."""

    def __init__(self) -> None:
        super().__init__("C253iDvZlb", schematic_sheet="INPUT", schematic_flow="compute")
        u, w, v = Net("AC_U_SW"), Net("AC_W_SW"), Net("AC_V")
        dc_p, dc_n = Net("DC_BUS_P"), Net("DC_BUS_N")
        v24, gnd = Net("V24"), Net("GND")
        jp = _h(self, "JP_ZLB_AC", 3)
        jp[1] += u  # JP1 Red Line
        jp[2] += w  # JP2 Red Line
        jp[3] += v  # JP3 Black Line
        jp5 = _h(self, "JP5", 2)
        jp5[1] += dc_p
        jp5[2] += dc_n
        _d(self, "D_ZLB_UH", u, dc_p)
        _d(self, "D_ZLB_WH", w, dc_p)
        _d(self, "D_ZLB_VH", v, dc_p)
        _d(self, "D_ZLB_UL", dc_n, u)
        _d(self, "D_ZLB_WL", dc_n, w)
        _d(self, "D_ZLB_VL", dc_n, v)
        _c(self, "C6", "470uF", dc_p, dc_n)
        bus = _h(self, "ZLB_BUS_1TO6", 6)
        for i, net in enumerate(
            (Net("ZLB_S1"), Net("ZLB_S2"), Net("ZLB_S3"), Net("ZLB_S4"), Net("ZLB_S5"), Net("ZLB_S6")),
            start=1,
        ):
            bus[i] += net
        cn4 = _h(self, "CN4", 2)
        cn4[1] += v24
        cn4[2] += gnd
        cn3 = _h(self, "CN3", 2)
        cn3[1] += v24
        cn3[2] += gnd
        fan = self.add(_mk("FAN", FAN_24V))
        fan[1] += v24
        fan[2] += gnd
        cn2 = _h(self, "CN2", 2)
        cn2[1] += gnd
        cn2[2] += gnd
        cn1 = _h(self, "CN1", 6)
        for i in range(1, 7):
            cn1[i] += Net(f"ZLB_S{i}")
        self.draws_from("V24", ma=200)


# ---------------------------------------------------------------------------
# C253i DV LBB — DC bus / CP1
# ---------------------------------------------------------------------------


class C253iDvLbb(Module):
    """C253i DV LBB capacitor bank, 2CN1/2CN2, 2JP1/2JP2, CP1."""

    def __init__(self) -> None:
        super().__init__("C253iDvLbb", schematic_sheet="POWER", schematic_flow="power")
        dc_p, dc_n = Net("DC_BUS_P"), Net("DC_BUS_N")
        cn1 = _h(self, "2CN1", 2)
        cn2 = _h(self, "2CN2", 2)
        cn1[1] += dc_p
        cn1[2] += dc_n
        cn2[1] += dc_p
        cn2[2] += dc_n
        _c(self, "C_LBB_A", "470uF", dc_p, dc_n)
        _c(self, "C_LBB_B", "470uF", dc_p, dc_n)
        jp = _h(self, "2JP12", 2)
        jp[1] += dc_p
        jp[2] += dc_n
        ct = self.add(_mk("CP1", XFMR_CT))
        ct["AA"] += dc_p
        ct["AB"] += Net("DC_BUS_P_CT")
        ct["SA"] += Net("CP1_SENSE_P")
        ct["SB"] += Net("CP1_SENSE_N")
        sense = _h(self, "LBB_SENSE", 2)
        sense[1] += Net("CP1_SENSE_P")
        sense[2] += Net("CP1_SENSE_N")


# ---------------------------------------------------------------------------
# IGBT H-bridge + T1
# ---------------------------------------------------------------------------


class IgbtInverter(Module):
    """Four IGBTs, gate resistors, CE snubbers, T1, 3CN / CN1-2."""

    def __init__(self) -> None:
        super().__init__("IgbtInverter", schematic_sheet="POWER", schematic_flow="compute")
        dc_p, dc_n = Net("DC_BUS_P_CT"), Net("DC_BUS_N")
        sw_a, sw_b = Net("INV_SW_A"), Net("INV_SW_B")
        g1, g2, g3, g4 = Net("G1"), Net("G2"), Net("G3"), Net("G4")
        e1, e2, e3, e4 = Net("E1"), Net("E2"), Net("E3"), Net("E4")
        v24, gnd = Net("V24"), Net("GND")

        q1, q2, q3, q4 = (_q(self, n) for n in ("IGBT1", "IGBT2", "IGBT3", "IGBT4"))
        # Left leg: IGBT1 (G1) high, IGBT2 (G3) low. Right: IGBT3 (G2), IGBT4 (G4).
        q1["C"] += dc_p
        q1["E"] += sw_a
        q2["C"] += sw_a
        q2["E"] += dc_n
        q3["C"] += dc_p
        q3["E"] += sw_b
        q4["C"] += sw_b
        q4["E"] += dc_n
        e1 += sw_a
        e2 += sw_b
        e3 += dc_n
        e4 += dc_n
        _r(self, "R10", "10", g1, q1["G"])
        _r(self, "R_G3", "10", g3, q2["G"])
        _r(self, "R9", "10", g2, q3["G"])
        _r(self, "R12", "10", g4, q4["G"])
        _c(self, "C1", "10nF", q1["C"], q1["E"])
        _c(self, "C12", "10nF", q1["C"], q1["E"])
        _c(self, "C13", "10nF", q2["C"], q2["E"])
        _c(self, "C8", "10nF", q3["C"], q3["E"])
        _c(self, "C9", "10nF", q3["C"], q3["E"])
        _c(self, "C14", "10nF", q3["C"], q3["E"])
        _c(self, "C11_CE", "10nF", q4["C"], q4["E"])
        _c(self, "C11", "10nF", sw_a, sw_b)

        t1 = self.add(_mk("T1", XFMR_1P2S))
        t1["AA"] += sw_a
        t1["AB"] += sw_b
        t1["SA"] += Net("T1_SA")
        t1["SB"] += Net("T1_CT")
        t1["SC"] += Net("T1_CT")
        t1["SD"] += Net("T1_SD")

        cn_g = _h(self, "3CN", 8)
        for pin, net in enumerate((g1, e1, g2, e2, g3, e3, g4, e4), start=1):
            cn_g[pin] += net
        cn12 = _h(self, "CN1_2", 2)
        cn12[1] += v24
        cn12[2] += gnd


# ---------------------------------------------------------------------------
# Output rectifier, L1, HALL, XS1 / XS2
# ---------------------------------------------------------------------------


class OutputStage(Module):
    """D1–D6, RC snubbers, L1, HALL, welding terminals XS1+ / XS2−."""

    def __init__(self) -> None:
        super().__init__("OutputStage", schematic_sheet="OUTPUT", schematic_flow="io")
        sa, ct, sd = Net("T1_SA"), Net("T1_CT"), Net("T1_SD")
        weld_p, weld_n = Net("WELD_POS"), Net("WELD_NEG")
        hall_n = Net("WELD_NEG_HALL")
        v24, gnd = Net("V24"), Net("GND")
        for name in ("D1", "D2", "D3"):
            _d(self, name, sa, weld_p)
        for name in ("D4", "D5", "D6"):
            _d(self, name, sd, weld_p)
        _r(self, "R1", "100", sa, Net("SNUB_SA"))
        _c(self, "C_OUT_SNUB1", "10nF", Net("SNUB_SA"), ct)
        _r(self, "R2", "100", sd, Net("SNUB_SD"))
        _c(self, "C2", "10nF", Net("SNUB_SD"), ct)
        _c(self, "C3", "100nF", weld_p, ct)
        _c(self, "C4", "100nF", weld_p, ct)
        _r(self, "R3", "1k", weld_p, ct)
        l1 = self.add(_mk("L1", L_OUT("L1")))
        l1[1] += weld_p
        l1[2] += Net("XS1_POS")
        xs = self.add(_mk("XS12", SCREW_2("XS12")))
        xs[1] += Net("XS1_POS")
        xs[2] += Net("XS2_NEG")
        hall = self.add(_mk("HALL", ACS712))
        hall["IP+"] += ct
        hall["IP+_2"] += ct
        hall["IP-"] += hall_n
        hall["IP-_2"] += hall_n
        hall["VCC"] += v24
        hall["GND"] += gnd
        hall["VIOUT"] += Net("I_WELD_SENSE")
        _c(self, "C_HALL_FILT", "100nF", hall["FILTER"], gnd, pkg="0603")
        hall_n += Net("XS2_NEG")
        self.draws_from("V24", ma=15)


# ---------------------------------------------------------------------------
# HV PSB — auxiliary 24 V / 15 V
# ---------------------------------------------------------------------------


class HvPsb(Module):
    """HV PSB: mains on 3CN1, aux transformer, +24 V / +15 V on 3CN3."""

    def __init__(self) -> None:
        super().__init__("HvPsb", schematic_sheet="AUX", schematic_flow="power")
        u_sw, w_sw = Net("AC_U_SW"), Net("AC_W_SW")
        v24, v15, gnd = Net("V24"), Net("V15"), Net("GND")
        aux_p, aux_n = Net("AUX_DC_P"), Net("GND")
        cn1 = _h(self, "3CN1", 2)
        cn1[1] += u_sw
        cn1[2] += w_sw
        xf = self.add(_mk("T_AUX", XFMR_AUX))
        xf["AA"] += u_sw
        xf["AB"] += w_sw
        _d(self, "D_AUX_H1", xf["SA"], aux_p)
        _d(self, "D_AUX_H2", xf["SB"], aux_p)
        _d(self, "D_AUX_L1", aux_n, xf["SA"])
        _d(self, "D_AUX_L2", aux_n, xf["SB"])
        _c(self, "C_AUX_BULK", "470uF", aux_p, gnd)
        r24 = self.add(_mk("U_24V", AMS1117_33))
        r24["VIN"] += aux_p
        r24["GND"] += gnd
        r24["VOUT"] += v24
        _c(self, "C_24V", "22uF", v24, gnd)
        r15 = self.add(_mk("U_15V", AMS1117_33))
        r15["VIN"] += v24
        r15["GND"] += gnd
        r15["VOUT"] += v15
        _c(self, "C_15V", "22uF", v15, gnd)
        cn3 = _h(self, "3CN3", 8)
        # 1=+15V  2=+24V  3=GND  4=GND  5=+24V  6=GND  7=+24V  8=EXD
        cn3[1] += v15
        cn3[2] += v24
        cn3[3] += gnd
        cn3[4] += gnd
        cn3[5] += v24
        cn3[6] += gnd
        cn3[7] += v24
        cn3[8] += Net("EXD")
        cn4 = _h(self, "3CN4", 2)
        cn4[1] += gnd
        cn4[2] += Net("EXD")
        self.draws_from("AC_U", ma=50)


# ---------------------------------------------------------------------------
# ZX7-400MINI LCD ZKB — control core + harness
# ---------------------------------------------------------------------------


class CtrlZkb(Module):
    """ZX7-400MINI LCD ZKB: STM32F103 + every 4CNx connector on the drawing."""

    def __init__(self) -> None:
        super().__init__("CtrlZkb", schematic_sheet="CTRL", schematic_flow="compute")
        v24, v15, v3, gnd = Net("V24"), Net("V15"), Net("3V3"), Net("GND")
        ldo = self.add(_mk("U_3V3", AMS1117_33))
        ldo["VIN"] += v15
        ldo["GND"] += gnd
        ldo["VOUT"] += v3
        _c(self, "C_3V3", "10uF", v3, gnd)
        _c(self, "C_3V3N", "100nF", v3, gnd, pkg="0603")

        m = self.add(_mk("U_ZKB", STM32F103C8))
        for p in (24, 36, 48, 9):
            m[p] += v3
        for p in (23, 35, 47, 8):
            m[p] += gnd
        m[7] += Net("STM_NRST")
        _r(self, "R_NRST", "10k", v3, Net("STM_NRST"))
        m[5] += Net("OSC_IN")
        m[6] += Net("OSC_OUT")
        xtal = self.add(_mk("XTAL_8M", XTAL_8MHZ))
        xtal[1] += Net("OSC_IN")
        xtal[3] += Net("OSC_OUT")
        xtal[2] += gnd
        xtal[4] += gnd
        _c(self, "C_XTAL_18PF_A", "18pF", Net("OSC_IN"), gnd, pkg="0603")
        _c(self, "C_XTAL_18PF_B", "18pF", Net("OSC_OUT"), gnd, pkg="0603")

        # TIM1 PWM → 3CN gate harness
        m[29] += Net("G1")  # PA8
        m[30] += Net("G2")  # PA9
        m[31] += Net("G3")  # PA10
        m[32] += Net("G4")  # PA11
        m[10] += Net("I_WELD_SENSE")  # PA0 hall
        m[11] += Net("CP1_SENSE_P")  # PA1 bus CT
        m[12] += Net("PANEL_TX")  # PA2
        m[13] += Net("PANEL_RX")  # PA3
        m[18] += Net("FEED_PWM")  # PB0
        m[19] += Net("TORCH_IN")  # PB1
        m[25] += Net("GAS_OUT")  # PB12
        m[14] += Net("PANEL_KEY")  # PA4
        m[15] += Net("FEED_DIR")  # PA5
        m[16] += Net("PANEL_ENC_A")  # PA6
        m[17] += Net("PANEL_ENC_B")  # PA7
        m[34] += Net("SWDIO")  # PA13
        m[37] += Net("SWCLK")  # PA14
        m.nc_unused_pins()

        cn5 = _h(self, "4CN5", 2)
        cn5[1] += Net("CP1_SENSE_P")
        cn5[2] += Net("CP1_SENSE_N")
        cn2 = _h(self, "4CN2", 8)
        for pin, name in enumerate(("G1", "E1", "G2", "E2", "G3", "E3", "G4", "E4"), start=1):
            cn2[pin] += Net(name)
        cn9 = _h(self, "4CN9", 2)
        cn9[1] += v24
        cn9[2] += gnd
        cn15 = _h(self, "4CN15", 6)
        for i in range(1, 7):
            cn15[i] += Net(f"ZLB_S{i}")
        cn13 = _h(self, "4CN13", 2)
        cn13[1] += gnd
        cn13[2] += gnd
        cn6 = _h(self, "4CN6", 8)
        cn6[1] += v15
        cn6[2] += v24
        cn6[3] += gnd
        cn6[4] += gnd
        cn6[5] += v24
        cn6[6] += gnd
        cn6[7] += v24
        cn6[8] += Net("EXD")
        cn16 = _h(self, "4CN16", 5)  # DP1 INCH4
        cn16[1] += v3
        cn16[2] += gnd
        cn16[3] += Net("SWDIO")
        cn16[4] += Net("SWCLK")
        cn16[5] += Net("STM_NRST")
        cn10 = _h(self, "4CN10", 6)
        for pin, net in enumerate((gnd, v24, v15, v15, gnd, gnd), start=1):
            cn10[pin] += net
        cn12 = _h(self, "4CN12", 2)
        cn12[1] += gnd
        cn12[2] += gnd
        cn7 = _h(self, "4CN7", 8)
        for pin, name in enumerate(
            ("FEED_PWM", "TORCH_IN", "GAS_OUT", "V24", "GND", "V24", "GND", "FEED_DIR"),
            start=1,
        ):
            cn7[pin] += Net(name)
        cn8 = _h(self, "4CN8", 5)
        cn8[1] += v24
        cn8[2] += gnd
        cn8[3] += Net("PANEL_TX")
        cn8[4] += Net("PANEL_RX")
        cn8[5] += Net("PANEL_KEY")
        self.draws_from("V15", ma=80)
        self.draws_from("V24", ma=40)


# ---------------------------------------------------------------------------
# EMIG-FEEDER + wire-feed motor + torch
# ---------------------------------------------------------------------------


class EmigFeeder(Module):
    """EMIG-FEEDER: 6CN02, 5CN1 motor, L2, torch, gas."""

    def __init__(self) -> None:
        super().__init__("EmigFeeder", schematic_sheet="FEEDER", schematic_flow="io")
        v24, gnd = Net("V24"), Net("GND")
        cn02 = _h(self, "6CN02", 8)
        for pin, name in enumerate(
            ("FEED_PWM", "TORCH_IN", "GAS_OUT", "V24", "GND", "V24", "GND", "FEED_DIR"),
            start=1,
        ):
            cn02[pin] += Net(name)
        cn5_2 = _h(self, "5CN2", 2)
        cn5_2[1] += v24
        cn5_2[2] += gnd
        cn1 = _h(self, "5CN1", 2)
        l2 = self.add(_mk("L2", L_OUT("L2")))
        mot = self.add(_mk("M1", MOTOR_WF))
        cn1[1] += Net("FEED_MOTOR_P")
        cn1[2] += gnd
        l2[1] += v24
        l2[2] += Net("FEED_MOTOR_P")
        mot[1] += Net("FEED_MOTOR_P")
        mot[2] += gnd
        torch = _h(self, "6CN104", 2)
        torch[1] += Net("TORCH_IN")
        torch[2] += gnd
        self.draws_from("V24", ma=200)


# ---------------------------------------------------------------------------
# C2B1 CKS32 Panel
# ---------------------------------------------------------------------------


class Cks32Panel(Module):
    """C2B1 CKS32 Panel: 6CN11, dual 8.8.8, S1–S4, wire-gas headers."""

    def __init__(self) -> None:
        super().__init__("Cks32Panel", schematic_sheet="PANEL", schematic_flow="io")
        v24, gnd = Net("V24"), Net("GND")
        cn11 = _h(self, "6CN11", 5)
        cn11[1] += v24
        cn11[2] += gnd
        cn11[3] += Net("PANEL_TX")
        cn11[4] += Net("PANEL_RX")
        cn11[5] += Net("PANEL_KEY")
        for tag in ("DISP_CUR", "DISP_VOLT"):
            d = self.add(_mk(tag, SEG7(tag)))
            for p in (6, 8, 9, 12):  # CA4 CA3 CA2 CA1
                d[p] += v24
            d.nc_unused_pins()
        s2 = self.add(_mk("S2", SW_KEY("S2")))
        s1 = self.add(_mk("S1", SW_KEY("S1")))
        s2[1] += Net("PANEL_KEY")
        s2[2] += gnd
        s1[1] += Net("PANEL_KEY")
        s1[2] += gnd
        s4 = self.add(_mk("S4", R_POT("S4")))
        s3 = self.add(_mk("S3", R_POT("S3")))
        s4[1] += v24
        s4[2] += Net("PANEL_ENC_A")
        s4[3] += gnd
        s3[1] += v24
        s3[2] += Net("PANEL_ENC_B")
        s3[3] += gnd
        _r(self, "R_ENC_A", "10k", Net("PANEL_ENC_A"), gnd)
        _r(self, "R_ENC_B", "10k", Net("PANEL_ENC_B"), gnd)
        for ref in ("6CN4", "6CN5", "6CN9"):
            g = _h(self, ref, 2)
            g[1] += Net("GAS_OUT")
            g[2] += gnd
        for ref, n in (("6CN10", 2), ("6CN2", 2), ("6CN6", 2), ("6CN7", 2), ("6CN8", 2)):
            h = _h(self, ref, n)
            h[1] += gnd
            h[2] += gnd
        self.draws_from("V24", ma=80)


# ---------------------------------------------------------------------------
# Board
# ---------------------------------------------------------------------------


def build_board() -> Board:
    board = Board(size_mm=None, layers=2, compile_goal="handoff", strict=False, target_kicad=10)

    ac = AcMainsInput()
    zlb = C253iDvZlb()
    lbb = C253iDvLbb()
    inv = IgbtInverter()
    out = OutputStage()
    hv = HvPsb()
    zkb = CtrlZkb()
    feeder = EmigFeeder()
    panel = Cks32Panel()

    modules = (ac, zlb, lbb, inv, out, hv, zkb, feeder, panel)
    for m in modules:
        board.add_module(m)

    board.set_schematic_sheet("INPUT", ac, zlb)
    board.set_schematic_sheet("POWER", lbb, inv)
    board.set_schematic_sheet("OUTPUT", out)
    board.set_schematic_sheet("AUX", hv)
    board.set_schematic_sheet("CTRL", zkb)
    board.set_schematic_sheet("FEEDER", feeder)
    board.set_schematic_sheet("PANEL", panel)

    zlb.cluster_with(ac)
    lbb.cluster_with(zlb)
    inv.cluster_with(lbb)
    out.cluster_with(inv)
    hv.cluster_with(ac)
    feeder.cluster_with(zkb)
    panel.cluster_with(zkb)

    board.declare_power_rail("AC_U", ac.u)
    board.declare_power_rail("DC_BUS_P", Net("DC_BUS_P"))
    board.declare_power_rail("V24", Net("V24"))
    board.declare_power_rail("V15", Net("V15"))
    board.declare_power_rail("3V3", Net("3V3"))
    board.declare_power_rail("GND", Net("GND"))
    board.declare_rail_conversion("AC_U", "DC_BUS_P", efficiency=0.95)
    board.declare_rail_conversion("AC_U", "V24", efficiency=0.80)
    board.declare_rail_conversion("V24", "V15", efficiency=0.85)
    board.declare_rail_conversion("V15", "3V3", efficiency=0.85)

    board.declare_copper_pour_intent(Net("GND"), layer="F.Cu", purpose="ground")
    board.declare_copper_pour_intent(Net("GND"), layer="B.Cu", purpose="ground")
    board.set_net_current(Net("DC_BUS_P"), 8.0, note="inverter DC bus (PCB pour / busbar)")
    board.set_net_current(Net("WELD_POS"), 8.0, note="weld output (cable, not PCB trace)")
    board.set_net_current(Net("V24"), 2.0, note="aux 24V")
    board.set_net_current(Net("FEED_MOTOR_P"), 2.0, note="wire-feed motor")
    board.set_net_current(Net("GND"), 2.0, note="aux return")
    return board


board = build_board()

if __name__ == "__main__":
    n = sum(len(m.components) for m in board._get_all_modules())
    print(f"ZX7-400MINI welder: {n} components / {len(board._get_all_modules())} modules")
    print("Sheets: INPUT POWER OUTPUT AUX CTRL FEEDER PANEL")
