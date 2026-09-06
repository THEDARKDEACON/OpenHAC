#!/usr/bin/env python3
"""Fundi MIG welder controller — OpenHaC port of the JKUAT live topology.

Live sheets only (root + V/I analog + R4 thermocouples). Archives/Drafts
duplicate analog islands are omitted.

SPICE: AnalogVnI island (AD620 front-end) with physics models in
examples/fundi_mig_spice/. 3D: stock KiCad footprints (${KICAD9_3DMODEL_DIR}).

Arduino Mega is a used-pin header (no stock Mega 2560 footprint). MAX6675
modules are 5-pin headers. Analog Devices vendor AD620.cir can replace
ad620.cir later via OPENHAC_SPICE_VENDOR_DIR.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_EX = Path(__file__).resolve().parent
_SPICE = _EX / "fundi_mig_spice"
os.environ.setdefault("OPENHAC_SPICE_MODEL_OVERLAY", str(_SPICE / "overlay.json"))
os.environ.setdefault("OPENHAC_SPICE_VENDOR_DIR", str(_SPICE))
if str(_EX) not in sys.path:
    sys.path.insert(0, str(_EX))

from openhac.compiler.spice_models import reset_spice_model_registry_cache

reset_spice_model_registry_cache()

import openhac.core  # noqa: F401
from openhac.core import Board
from openhac.core.base import Module
from openhac.core.net import Net

from fundi_mig_parts import (
    AC_LOAD,
    AD620,
    ADS1115,
    BT137,
    C,
    D_1N4007,
    D_1N5819,
    HALL,
    HC14,
    LED,
    MAX1044,
    MAX485,
    MAX6675,
    MEGA,
    MOC3021,
    NANO,
    NANO_EVERY,
    PC817,
    R,
    SERVO,
    SW_SPST,
    TERM2,
    mk,
)


def _r(mod: Module, name: str, ohms: str, a, b):
    c = mod.add(mk(name, R(name, ohms)))
    c[1] += a
    c[2] += b
    return c


def _c(mod: Module, name: str, val: str, a, b):
    c = mod.add(mk(name, C(name, val)))
    c[1] += a
    c[2] += b
    return c


class PowerRails(Module):
    """Isolated battery / wall-wart stand-ins (connectors; omitted from SPICE)."""

    def __init__(self) -> None:
        super().__init__("PowerRails")
        self.gnd = Net("GND")
        self.gnd2 = Net("GND2")
        self.gnd3 = Net("GND3")
        self.p5_sens = Net("P5V_SENS")
        self.p5_vni = Net("P5V_VNI")
        self.p5_liion = Net("P5V_LIION")
        self.p5_servo = Net("P5V_SERVO")
        self.p9 = Net("P9V")
        self.n9 = Net("N9V")

        def _cell(name, pos, neg):
            j = self.add(mk(name, TERM2))
            j[1] += pos
            j[2] += neg
            return j

        _cell("J_P5_SENS", self.p5_sens, self.gnd)
        _cell("J_P5_SERVO", self.p5_servo, self.gnd)
        _cell("J_P5_VNI", self.p5_vni, self.gnd3)
        _cell("J_P5_LIION", self.p5_liion, self.gnd2)
        _cell("J_P9", self.p9, self.gnd3)
        _cell("J_N9", self.gnd3, self.n9)
        _c(self, "C_SENS_100N", "100nF", self.p5_sens, self.gnd)
        _c(self, "C_SERVO_100N", "100nF", self.p5_servo, self.gnd)
        _c(self, "C_VNI_100N", "100nF", self.p5_vni, self.gnd3)
        _c(self, "C_P9_100N", "100nF", self.p9, self.gnd3)
        _c(self, "C_N9_100N", "100nF", self.n9, self.gnd3)

        inv = self.add(mk("MAX1044", MAX1044))
        inv["V+"] += self.p9
        inv["GND"] += self.gnd3
        inv["VOUT"] += self.n9
        inv.nc_unused_pins()


class AnalogVnI(Module):
    """Live AD620 voltage/current front-end (default SPICE island)."""

    def __init__(self) -> None:
        super().__init__("AnalogVnI")
        g3 = Net("GND3")
        p9, n9 = Net("P9V"), Net("N9V")
        torch = Net("TORCH")
        torch_ret = Net("GND3")
        shunt_p = Net("SHUNT_P")
        tap_hi, tap, u1p, u1n = Net("TORCH_MID"), Net("TORCH_TAP"), Net("U1_INP"), Net("U1_INN")
        u2p, u2n = Net("U2_INP"), Net("U2_INN")
        self.u1_out, self.u2_out = Net("U1_OUT"), Net("U2_OUT")
        ads_a0, ads_a2 = Net("ADS_A0"), Net("ADS_A2")
        rg1, rg2 = Net("U2_RG1"), Net("U2_RG2")

        j1 = self.add(mk("J_TORCH", TERM2))
        j1[1] += torch
        j1[2] += torch_ret
        j2 = self.add(mk("J_SHUNT", TERM2))
        j2[1] += shunt_p
        j2[2] += g3

        _r(self, "R_TORCH_1MEG", "1Meg", torch, tap_hi)
        _r(self, "R_TORCH_MID_100K", "100k", tap_hi, tap)
        _r(self, "R_TORCH_LO_100K", "100k", tap, torch_ret)
        _r(self, "R_U1P_5K", "5k", tap, u1p)
        _r(self, "R_U1N_82K", "82k", torch_ret, Net("U1_NBRIDGE"))
        _r(self, "R_U1N_5K", "5k", Net("U1_NBRIDGE"), u1n)
        _r(self, "R_U1P_BLEED_1MEG", "1Meg", u1p, g3)
        _r(self, "R_U1N_BLEED_1MEG", "1Meg", u1n, g3)
        _c(self, "C_U1DIFF_1U", "1uF", u1n, u1p)
        _c(self, "C_U1P_100N", "100nF", u1p, g3)
        _c(self, "C_U1N_100N", "100nF", u1n, g3)

        u1 = self.add(mk("AD620_V", AD620))
        u1[1] += Net("U1_RG1")
        u1[8] += Net("U1_RG2")
        _r(self, "R_U1_RG_10MEG", "10Meg", Net("U1_RG1"), Net("U1_RG2"))
        u1[2] += u1n
        u1[3] += u1p
        u1[4] += n9
        u1[5] += g3
        u1[6] += self.u1_out
        u1[7] += p9
        _r(self, "R_U1_OUT_440R", "440R", self.u1_out, ads_a0)

        _r(self, "R_SHUNT_P_5K", "5k", shunt_p, u2p)
        _r(self, "R_SHUNT_N_5K", "5k", g3, u2n)
        _r(self, "R_U2P_BLEED_1MEG", "1Meg", u2p, g3)
        _r(self, "R_U2N_BLEED_1MEG", "1Meg", u2n, g3)
        _c(self, "C_U2DIFF_1U", "1uF", u2n, u2p)
        _c(self, "C_U2P_100N", "100nF", u2p, g3)
        _c(self, "C_U2N_100N", "100nF", u2n, g3)

        u2 = self.add(mk("AD620_I", AD620))
        u2[1] += rg1
        u2[8] += rg2
        _r(self, "R_U2_RG_10K", "10k", rg1, rg2)
        u2[2] += u2n
        u2[3] += u2p
        u2[4] += n9
        u2[5] += g3
        u2[6] += self.u2_out
        u2[7] += p9
        _r(self, "R_U2_OUT_440R", "440R", self.u2_out, ads_a2)

        d7 = self.add(mk("LED_P9", LED))
        d7["A"] += Net("LED_P9_A")
        d7["K"] += g3
        _r(self, "R_LED_P9A_330R", "330R", p9, Net("LED_P9_MID"))
        _r(self, "R_LED_P9B_330R", "330R", Net("LED_P9_MID"), Net("LED_P9_A"))


class AnalogAdc(Module):
    """ADS1115 on isolated I2C (outside the analog SPICE island)."""

    def __init__(self) -> None:
        super().__init__("AnalogAdc")
        g3, p5 = Net("GND3"), Net("P5V_VNI")
        scl, sda = Net("SCL_ISO"), Net("SDA_ISO")
        u = self.add(mk("ADS1115", ADS1115))
        u["VDD"] += p5
        u["GND"] += g3
        u["SCL"] += scl
        u["SDA"] += sda
        u["AIN0"] += Net("ADS_A0")
        u["AIN2"] += Net("ADS_A2")
        u["ADDR"] += g3
        u.nc_unused_pins()
        d8 = self.add(mk("LED_VNI", LED))
        d8["A"] += Net("LED_VNI_A")
        d8["K"] += g3
        _r(self, "R_LED_VNI_220R", "220R", p5, Net("LED_VNI_A"))


class I2cIsolator(Module):
    """Bidirectional PC817 pair for Mega SCL/SDA ↔ isolated ADS1115."""

    def __init__(self) -> None:
        super().__init__("I2cIsolator")
        gnd, g3 = Net("GND"), Net("GND3")
        p5s, p5i = Net("P5V_SENS"), Net("P5V_VNI")
        scl, sda = Net("SCL"), Net("SDA")
        scl_i, sda_i = Net("SCL_ISO"), Net("SDA_ISO")

        def _chan(tag, mcu, iso, r_mcu, r_iso, r_pu_m, r_pu_i):
            u_m = self.add(mk(f"PC817_{tag}_M", PC817))
            u_i = self.add(mk(f"PC817_{tag}_I", PC817))
            d_m = self.add(mk(f"D5819_{tag}_M", D_1N5819))
            d_i = self.add(mk(f"D5819_{tag}_I", D_1N5819))
            n_ka_m, n_ka_i = Net(f"{tag}_KA_M"), Net(f"{tag}_KA_I")
            d_m["A"] += mcu
            d_m["K"] += n_ka_m
            u_m["A"] += n_ka_m
            u_m["K"] += mcu
            u_m["E"] += g3
            u_m["C"] += n_ka_i
            d_i["A"] += iso
            d_i["K"] += n_ka_i
            u_i["A"] += n_ka_i
            u_i["K"] += iso
            u_i["E"] += gnd
            u_i["C"] += n_ka_m
            _r(self, r_mcu, "135R", p5s, n_ka_m)
            _r(self, r_iso, "135R", p5i, n_ka_i)
            _r(self, r_pu_m, "2k2", p5s, mcu)
            _r(self, r_pu_i, "2k2", p5i, iso)

        _chan("SCL", scl, scl_i, "R_SCL_M_135R", "R_SCL_I_135R", "R_SCL_PU_M_2K2", "R_SCL_PU_I_2K2")
        _chan("SDA", sda, sda_i, "R_SDA_M_135R", "R_SDA_I_135R", "R_SDA_PU_M_2K2", "R_SDA_PU_I_2K2")


class MegaMinimal(Module):
    def __init__(self) -> None:
        super().__init__("MegaMinimal")
        gnd, p5 = Net("GND"), Net("P5V_SENS")
        m = self.add(mk("MEGA2560", MEGA))
        m["P5V"] += p5
        m["GND"] += gnd
        m["D3"] += Net("HALL")
        m["D7"] += Net("SERVO2")
        m["D19"] += Net("DAT")
        m["D20"] += Net("SDA")
        m["D21"] += Net("SCL")
        m["A0"] += Net("T4CS")
        m["A1"] += Net("T4SCK")
        m["A2"] += Net("T3CS")
        m["A3"] += Net("T3SCK")
        m["A4"] += Net("T4SO")
        m["A5"] += Net("T3SO")
        m["A6"] += Net("T2SO")
        m["A7"] += Net("T1SO")
        m["A8"] += Net("T2CS")
        m["A9"] += Net("T2SCK")
        m["A10"] += Net("T1CS")
        m["A11"] += Net("T1SCK")
        m["A14"] += Net("TRIAC")
        m["A15"] += Net("ZERO")
        m.nc_unused_pins()


class ThermoR23(Module):
    """R2/R3 MAX6675 behind PC817 + 74HC14, RS-485 DI from inverter."""

    def __init__(self) -> None:
        super().__init__("ThermoR23")
        gnd, g2 = Net("GND"), Net("GND2")
        p5s, p5l = Net("P5V_SENS"), Net("P5V_LIION")
        tc = self.add(mk("MAX6675_R23", MAX6675))
        tc["VCC"] += p5l
        tc["GND"] += g2
        tc["SO"] += Net("T1SO_ISO")
        tc["SCK"] += Net("T1SCK_ISO")
        tc["CS"] += Net("T1CS_ISO")

        u_sck = self.add(mk("PC817_T1SCK", PC817))
        u_sck["A"] += Net("T1SCK_LED")
        u_sck["K"] += Net("T1SCK")
        u_sck["E"] += g2
        u_sck["C"] += Net("HC14_1A")
        _r(self, "R_T1SCK_LED_330R", "330R", p5s, Net("T1SCK_LED"))
        _r(self, "R_T1SCK_PU_3K", "3k", p5l, Net("HC14_1A"))

        u_cs = self.add(mk("PC817_T1CS", PC817))
        u_cs["A"] += Net("T1CS_LED")
        u_cs["K"] += Net("T1CS")
        u_cs["E"] += g2
        u_cs["C"] += Net("T1CS_ISO")
        _r(self, "R_T1CS_LED_330R", "330R", p5s, Net("T1CS_LED"))
        _r(self, "R_T1CS_PU_3K", "3k", p5l, Net("T1CS_ISO"))

        u_so = self.add(mk("PC817_T1SO", PC817))
        u_so["A"] += Net("T1SO_LED")
        u_so["K"] += Net("T1SO_ISO")
        u_so["E"] += gnd
        u_so["C"] += Net("T1SO")
        _r(self, "R_T1SO_LED_330R", "330R", p5l, Net("T1SO_LED"))
        _r(self, "R_T1SO_PU_10K", "10k", p5s, Net("T1SO"))

        hc = self.add(mk("HC14_R23", HC14))
        hc["VCC"] += p5l
        hc["GND"] += g2
        hc["1A"] += Net("HC14_1A")
        hc["1Y"] += Net("T1SCK_ISO")
        hc["6A"] += Net("R1_SO_MIX")
        hc["6Y"] += Net("RS485_DI")
        hc["2A"] += p5l
        hc["3A"] += p5l
        hc["4A"] += p5l
        hc["5A"] += p5l
        hc.nc_unused_pins()

        tx = self.add(mk("MAX485_R23", MAX485))
        tx["VCC"] += p5s
        tx["GND"] += gnd
        tx["DI"] += Net("RS485_DI")
        tx["DE"] += p5s
        tx["RE"] += p5s
        tx["A"] += Net("RS485_A")
        tx["B"] += Net("RS485_B")
        tx.nc_unused_pins()


class ThermoR1(Module):
    def __init__(self) -> None:
        super().__init__("ThermoR1")
        g2, p5l = Net("GND2"), Net("P5V_LIION")
        nano = self.add(mk("NANO_R1", NANO))
        nano["VIN"] += p5l
        nano["GND1"] += g2
        nano["GND2"] += g2
        nano["A0"] += Net("R1_SO")
        nano["A1"] += Net("R1_SCK")
        nano["A2"] += Net("R1_CS")
        nano["D1_TX"] += Net("R1_TX")
        nano.nc_unused_pins()
        tc = self.add(mk("MAX6675_R1", MAX6675))
        tc["VCC"] += p5l
        tc["GND"] += g2
        tc["SO"] += Net("R1_SO")
        tc["SCK"] += Net("R1_SCK")
        tc["CS"] += Net("R1_CS")
        opt = self.add(mk("PC817_R1", PC817))
        opt["A"] += Net("R1_TX_LED")
        opt["K"] += g2
        opt["E"] += Net("GND")
        opt["C"] += Net("R1_SO_MIX")
        _r(self, "R_R1_TX_330R", "330R", Net("R1_TX"), Net("R1_TX_LED"))
        _r(self, "R_R1_MIX_3K", "3k", Net("P5V_SENS"), Net("R1_SO_MIX"))


class ThermoR4(Module):
    """Nano Every + four MAX6675 + local RS-485 (R4 sheet)."""

    def __init__(self) -> None:
        super().__init__("ThermoR4")
        g2, p5 = Net("GND2"), Net("P5V_LIION")
        n = self.add(mk("NANO_EVERY", NANO_EVERY))
        n["VIN"] += p5
        n["GND1"] += g2
        n["GND2"] += g2
        n["A0"] += Net("T1SO")
        n["A1"] += Net("T1CS")
        n["A2"] += Net("T1SCK")
        n["A3"] += Net("T2SCK")
        n["A4_SDA"] += Net("T2CS")
        n["A5_SCL"] += Net("T2SO")
        n["D2"] += Net("T3SCK")
        n["D3"] += Net("T3CS")
        n["D4"] += Net("T3SO")
        n["D5"] += Net("T4SCK")
        n["D6"] += Net("T4CS")
        n["D7"] += Net("T4SO")
        n["D1_TX"] += Net("T_SUBSTRATE")
        n.nc_unused_pins()
        for i, cs, sck, so in (
            (1, "T1CS", "T1SCK", "T1SO"),
            (2, "T2CS", "T2SCK", "T2SO"),
            (3, "T3CS", "T3SCK", "T3SO"),
            (4, "T4CS", "T4SCK", "T4SO"),
        ):
            tc = self.add(mk(f"MAX6675_T{i}", MAX6675))
            tc["VCC"] += p5
            tc["GND"] += g2
            tc["CS"] += Net(cs)
            tc["SCK"] += Net(sck)
            tc["SO"] += Net(so)
        opt = self.add(mk("PC817_R4", PC817))
        opt["A"] += Net("R4_LED")
        opt["K"] += g2
        opt["E"] += Net("GND")
        opt["C"] += Net("R4_C")
        _r(self, "R_R4_LED_330R", "330R", Net("T_SUBSTRATE"), Net("R4_LED"))
        _r(self, "R_R4_C_3K", "3k", Net("P5V_SENS"), Net("R4_C"))
        hc = self.add(mk("HC14_R4", HC14))
        hc["VCC"] += p5
        hc["GND"] += g2
        hc["6A"] += Net("R4_C")
        hc["6Y"] += Net("R4_DI")
        hc["1A"] += p5
        hc["2A"] += p5
        hc["3A"] += p5
        hc["4A"] += p5
        hc["5A"] += p5
        hc.nc_unused_pins()
        for tag, de in (("TX", True), ("RX", False)):
            u = self.add(mk(f"MAX485_R4_{tag}", MAX485))
            u["VCC"] += Net("P5V_SENS")
            u["GND"] += Net("GND")
            u["A"] += Net("RS485_A")
            u["B"] += Net("RS485_B")
            if de:
                u["DE"] += Net("P5V_SENS")
                u["RE"] += Net("P5V_SENS")
                u["DI"] += Net("R4_DI")
            else:
                u["DE"] += Net("GND")
                u["RE"] += Net("GND")
                u["RO"] += Net("T_SUBSTRATE")
            u.nc_unused_pins()


class Wfs(Module):
    def __init__(self) -> None:
        super().__init__("Wfs")
        gnd, p5, psv = Net("GND"), Net("P5V_SENS"), Net("P5V_SERVO")
        h = self.add(mk("A3144", HALL))
        h["VCC"] += p5
        h["GND"] += gnd
        h["VOUT"] += Net("HALL")
        _r(self, "R_HALL_1K", "1k", p5, Net("HALL"))
        s = self.add(mk("SERVO_WFS", SERVO))
        s["PWM"] += Net("SERVO2")
        s["V+"] += psv
        s["GND"] += gnd


class TriacControl(Module):
    def __init__(self) -> None:
        super().__init__("TriacControl")
        gnd, p5 = Net("GND"), Net("P5V_SENS")
        acp, acn = Net("AC_P"), Net("AC_N")
        sw = self.add(mk("SW_AC", SW_SPST))
        mains = self.add(mk("J_MAINS", TERM2))
        mains[1] += Net("MAINS_L")
        mains[2] += acn
        sw["A"] += Net("MAINS_L")
        sw["B"] += acp
        moc = self.add(mk("MOC3021", MOC3021))
        moc["A"] += Net("MOC_A")
        moc["K"] += gnd
        moc["MT1"] += Net("TRIAC_G")
        moc["MT2"] += Net("MOC_MT2")
        moc.nc_unused_pins()
        _r(self, "R_MOC_LED_330R", "330R", Net("TRIAC"), Net("MOC_A"))
        _r(self, "R_MOC_MT_330R", "330R", acp, Net("MOC_MT2"))
        q = self.add(mk("BT137", BT137))
        q["A2"] += acp
        q["A1"] += Net("MOTOR_HOT")
        q["G"] += Net("TRIAC_G")
        motor = self.add(mk("J_MOTOR", AC_LOAD))
        motor[1] += Net("MOTOR_HOT")
        motor[2] += acn
        d1 = self.add(mk("D4007_ZXA", D_1N4007))
        d2 = self.add(mk("D4007_ZXB", D_1N4007))
        d3 = self.add(mk("D4007_ZXC", D_1N4007))
        d4 = self.add(mk("D4007_ZXD", D_1N4007))
        d1["A"] += Net("ZX_AK")
        d1["K"] += Net("ZX_D1K")
        d2["A"] += Net("ZX_AK")
        d2["K"] += Net("ZX_D2K")
        d3["A"] += Net("ZX_D1K")
        d3["K"] += Net("ZX_CK")
        d4["A"] += Net("ZX_D2K")
        d4["K"] += Net("ZX_CK")
        _r(self, "R_ZX_AC_50K", "50k", acp, Net("ZX_D1K"))
        _r(self, "R_ZX_ACN_50K", "50k", acn, Net("ZX_D2K"))
        u3 = self.add(mk("PC817_ZX", PC817))
        u3["A"] += Net("ZX_CK")
        u3["K"] += Net("ZX_AK")
        u3["E"] += gnd
        u3["C"] += Net("ZERO")
        _r(self, "R_ZERO_1K", "1k", p5, Net("ZERO"))


class Rs485Listen(Module):
    def __init__(self) -> None:
        super().__init__("Rs485Listen")
        gnd, p5 = Net("GND"), Net("P5V_SENS")
        u = self.add(mk("MAX485_LISTEN", MAX485))
        u["VCC"] += p5
        u["GND"] += gnd
        u["RO"] += Net("DAT")
        u["RE"] += gnd
        u["DE"] += gnd
        u["A"] += Net("RS485_A")
        u["B"] += Net("RS485_B")
        u.nc_unused_pins()
        bus = self.add(mk("J_RS485", TERM2))
        bus[1] += Net("RS485_A")
        bus[2] += Net("RS485_B")


def build_board() -> Board:
    board = Board(size_mm=None, layers=2, compile_goal="handoff", strict=False)
    pwr = PowerRails()
    analog = AnalogVnI()
    adc = AnalogAdc()
    i2c = I2cIsolator()
    mega = MegaMinimal()
    r23 = ThermoR23()
    r1 = ThermoR1()
    r4 = ThermoR4()
    wfs = Wfs()
    triac = TriacControl()
    rs = Rs485Listen()
    for m in (pwr, analog, adc, i2c, mega, r23, r1, r4, wfs, triac, rs):
        board.add_module(m)
    board.set_schematic_sheet("POWER", pwr)
    board.set_schematic_sheet("MCU", mega, i2c, rs)
    board.set_schematic_sheet("ANALOG", analog, adc)
    board.set_schematic_sheet("FIELD", r23, r1, r4, wfs, triac)

    board.declare_power_rail("P5V_SENS", pwr.p5_sens)
    board.declare_power_rail("P5V_VNI", pwr.p5_vni)
    board.declare_power_rail("P5V_LIION", pwr.p5_liion)
    board.declare_power_rail("P5V_SERVO", pwr.p5_servo)
    board.declare_power_rail("P9V", pwr.p9)
    board.declare_power_rail("GND", pwr.gnd)
    board.declare_power_rail("GND2", pwr.gnd2)
    board.declare_power_rail("GND3", pwr.gnd3)

    board.declare_spice_island(analog)
    board.declare_spice_ground("GND3")
    board.declare_spice_rail("P9V", 9.0)
    board.declare_spice_rail("N9V", -9.0)
    board.declare_spice_rail("P5V_VNI", 5.0)
    board.declare_spice_rail("P5V_SENS", 5.0)
    board.declare_spice_rail("P5V_LIION", 5.0)
    board.declare_spice_rail("P5V_SERVO", 5.0)
    board.declare_spice_rail("TORCH", 10.0)
    board.declare_spice_rail("SHUNT_P", 0.05)
    board.declare_spice_probe("U1_OUT", 0.5, 1.3)
    board.declare_spice_probe("U2_OUT", 0.15, 0.55)
    return board


board = build_board()

if __name__ == "__main__":
    n = sum(len(m.components) for m in board._get_all_modules())
    print(f"Fundi MIG controller: {n} components, analog island AnalogVnI")
