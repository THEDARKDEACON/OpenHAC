"""SCH-005: erc_rule_packs convenience bundles."""

from __future__ import annotations

import openhac.core  # noqa: F401
from skidl import Net, Part

from openhac.core import Board
from openhac.core.base import Component
from openhac.compiler.rule_check import run_erc
from openhac.stdlib.erc_rule_packs import (
    apply_can_eth_phy_pullup_pack,
    apply_hdmi_display_pullup_pack,
    apply_i2c_pullup_pack,
    apply_jtag_boundary_pullup_pack,
    apply_lin_rs485_re_pullup_pack,
    apply_sd_mmc_pullup_pack,
    apply_spi_nor_protect_pullup_pack,
)


def test_apply_i2c_pullup_pack_registers_hook(tmp_db, monkeypatch):
    _, dm = tmp_db
    dm.insert_component(
        {
            "generic_name": "R_10k_0805",
            "kicad_symbol": "Device:R",
            "kicad_footprint": "Resistor_SMD:R_0805_2012Metric",
            "manufacturer": "",
            "mpn": "X",
            "supplier_sku": "",
            "description": "",
        }
    )
    monkeypatch.setattr(Component, "db", dm)

    vcc, gnd = Net("3V3"), Net("GND")
    sda, scl = Net("SDA"), Net("SCL")
    Part("power", "PWR_FLAG")[1] += vcc
    Part("power", "PWR_FLAG")[1] += gnd
    for ref, net in (("U_SDA1", sda), ("U_SDA2", sda), ("U_SCL1", scl), ("U_SCL2", scl)):
        u = Part("Device", "R", value="0", ref=ref)
        u[1] += net
        u[2] += gnd
    pu_sda = Component("R_10k_0805")
    pu_scl = Component("R_10k_0805")
    pu_sda["1"] += vcc
    pu_sda["2"] += sda
    pu_scl["1"] += vcc
    pu_scl["2"] += scl

    board = Board(size_mm=(10, 10))
    apply_i2c_pullup_pack(board, scl, sda)
    assert len(getattr(board, "_erc_hooks", [])) == 1
    run_erc(board)


def test_apply_hdmi_display_pullup_pack_registers_two_hooks(tmp_db, monkeypatch):
    _, dm = tmp_db
    dm.insert_component(
        {
            "generic_name": "R_10k_0805",
            "kicad_symbol": "Device:R",
            "kicad_footprint": "Resistor_SMD:R_0805_2012Metric",
            "manufacturer": "",
            "mpn": "X",
            "supplier_sku": "",
            "description": "",
        }
    )
    monkeypatch.setattr(Component, "db", dm)

    vcc, gnd = Net("3V3"), Net("GND")
    cec, hpd = Net("HDMI_CEC"), Net("HDMI_HPD")
    Part("power", "PWR_FLAG")[1] += vcc
    Part("power", "PWR_FLAG")[1] += gnd
    for ref, net in (
        ("U_CEC1", cec),
        ("U_CEC2", cec),
        ("U_HPD1", hpd),
        ("U_HPD2", hpd),
    ):
        u = Part("Device", "R", value="0", ref=ref)
        u[1] += net
        u[2] += gnd
    for net in (cec, hpd):
        pu = Component("R_10k_0805")
        pu["1"] += vcc
        pu["2"] += net

    board = Board(size_mm=(10, 10))
    apply_hdmi_display_pullup_pack(board, cec, hpd)
    assert len(getattr(board, "_erc_hooks", [])) == 2
    run_erc(board)


def test_apply_sd_mmc_pullup_pack_registers_two_hooks(tmp_db, monkeypatch):
    _, dm = tmp_db
    dm.insert_component(
        {
            "generic_name": "R_10k_0805",
            "kicad_symbol": "Device:R",
            "kicad_footprint": "Resistor_SMD:R_0805_2012Metric",
            "manufacturer": "",
            "mpn": "X",
            "supplier_sku": "",
            "description": "",
        }
    )
    monkeypatch.setattr(Component, "db", dm)

    vcc, gnd = Net("3V3"), Net("GND")
    cmd, cd = Net("SD_CMD"), Net("SD_CD")
    Part("power", "PWR_FLAG")[1] += vcc
    Part("power", "PWR_FLAG")[1] += gnd
    for ref, net in (
        ("J_SD1", cmd),
        ("J_SD2", cmd),
        ("J_SD3", cd),
        ("J_SD4", cd),
    ):
        u = Part("Device", "R", value="0", ref=ref)
        u[1] += net
        u[2] += gnd
    for net in (cmd, cd):
        pu = Component("R_10k_0805")
        pu["1"] += vcc
        pu["2"] += net

    board = Board(size_mm=(10, 10))
    apply_sd_mmc_pullup_pack(board, cmd, cd)
    assert len(getattr(board, "_erc_hooks", [])) == 2
    run_erc(board)


def test_apply_jtag_boundary_pullup_pack_registers_two_hooks(tmp_db, monkeypatch):
    _, dm = tmp_db
    dm.insert_component(
        {
            "generic_name": "R_10k_0805",
            "kicad_symbol": "Device:R",
            "kicad_footprint": "Resistor_SMD:R_0805_2012Metric",
            "manufacturer": "",
            "mpn": "X",
            "supplier_sku": "",
            "description": "",
        }
    )
    monkeypatch.setattr(Component, "db", dm)

    vcc, gnd = Net("3V3"), Net("GND")
    tms, tck = Net("JTAG_TMS"), Net("JTAG_TCK")
    Part("power", "PWR_FLAG")[1] += vcc
    Part("power", "PWR_FLAG")[1] += gnd
    for ref, net in (
        ("J_HDR1", tms),
        ("J_HDR2", tms),
        ("J_HDR3", tck),
        ("J_HDR4", tck),
    ):
        u = Part("Device", "R", value="0", ref=ref)
        u[1] += net
        u[2] += gnd
    for net in (tms, tck):
        pu = Component("R_10k_0805")
        pu["1"] += vcc
        pu["2"] += net

    board = Board(size_mm=(10, 10))
    apply_jtag_boundary_pullup_pack(board, tms, tck)
    assert len(getattr(board, "_erc_hooks", [])) == 2
    run_erc(board)


def test_apply_spi_nor_protect_pullup_pack_registers_two_hooks(tmp_db, monkeypatch):
    _, dm = tmp_db
    dm.insert_component(
        {
            "generic_name": "R_10k_0805",
            "kicad_symbol": "Device:R",
            "kicad_footprint": "Resistor_SMD:R_0805_2012Metric",
            "manufacturer": "",
            "mpn": "X",
            "supplier_sku": "",
            "description": "",
        }
    )
    monkeypatch.setattr(Component, "db", dm)

    vcc, gnd = Net("3V3"), Net("GND")
    wp, hold = Net("FLASH_WP"), Net("FLASH_HOLD")
    Part("power", "PWR_FLAG")[1] += vcc
    Part("power", "PWR_FLAG")[1] += gnd
    for ref, net in (
        ("U_F1", wp),
        ("U_F2", wp),
        ("U_F3", hold),
        ("U_F4", hold),
    ):
        u = Part("Device", "R", value="0", ref=ref)
        u[1] += net
        u[2] += gnd
    for net in (wp, hold):
        pu = Component("R_10k_0805")
        pu["1"] += vcc
        pu["2"] += net

    board = Board(size_mm=(10, 10))
    apply_spi_nor_protect_pullup_pack(board, wp, hold)
    assert len(getattr(board, "_erc_hooks", [])) == 2
    run_erc(board)


def test_apply_lin_rs485_re_pullup_pack_registers_two_hooks(tmp_db, monkeypatch):
    _, dm = tmp_db
    dm.insert_component(
        {
            "generic_name": "R_10k_0805",
            "kicad_symbol": "Device:R",
            "kicad_footprint": "Resistor_SMD:R_0805_2012Metric",
            "manufacturer": "",
            "mpn": "X",
            "supplier_sku": "",
            "description": "",
        }
    )
    monkeypatch.setattr(Component, "db", dm)

    vcc, gnd = Net("3V3"), Net("GND")
    lin, re_n = Net("LIN_BUS"), Net("RS485_RE")
    Part("power", "PWR_FLAG")[1] += vcc
    Part("power", "PWR_FLAG")[1] += gnd
    for ref, net in (
        ("U_LIN1", lin),
        ("U_LIN2", lin),
        ("U_RS1", re_n),
        ("U_RS2", re_n),
    ):
        u = Part("Device", "R", value="0", ref=ref)
        u[1] += net
        u[2] += gnd
    for net in (lin, re_n):
        pu = Component("R_10k_0805")
        pu["1"] += vcc
        pu["2"] += net

    board = Board(size_mm=(10, 10))
    apply_lin_rs485_re_pullup_pack(board, lin, re_n)
    assert len(getattr(board, "_erc_hooks", [])) == 2
    run_erc(board)


def test_apply_can_eth_phy_pullup_pack_registers_two_hooks(tmp_db, monkeypatch):
    _, dm = tmp_db
    dm.insert_component(
        {
            "generic_name": "R_10k_0805",
            "kicad_symbol": "Device:R",
            "kicad_footprint": "Resistor_SMD:R_0805_2012Metric",
            "manufacturer": "",
            "mpn": "X",
            "supplier_sku": "",
            "description": "",
        }
    )
    monkeypatch.setattr(Component, "db", dm)

    vcc, gnd = Net("3V3"), Net("GND")
    can_rx, phy_int = Net("CAN_RX"), Net("ETH_PHY_INT")
    Part("power", "PWR_FLAG")[1] += vcc
    Part("power", "PWR_FLAG")[1] += gnd
    for ref, net in (
        ("U_CAN1", can_rx),
        ("U_CAN2", can_rx),
        ("U_PHY1", phy_int),
        ("U_MCU1", phy_int),
    ):
        u = Part("Device", "R", value="0", ref=ref)
        u[1] += net
        u[2] += gnd
    for net in (can_rx, phy_int):
        pu = Component("R_10k_0805")
        pu["1"] += vcc
        pu["2"] += net

    board = Board(size_mm=(10, 10))
    apply_can_eth_phy_pullup_pack(board, can_rx, phy_int)
    assert len(getattr(board, "_erc_hooks", [])) == 2
    run_erc(board)
