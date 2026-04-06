"""ARCH / SCH-005: named ERC plugin registry."""

from __future__ import annotations

import pytest

import openhac.core  # noqa: F401
from skidl import Net, Part

from openhac.core import Board
from openhac.core.base import Component, OpenHaCError
from openhac.compiler.rule_check import run_erc
from openhac.stdlib import erc_rule_packs as erp
from openhac.stdlib.erc_plugin_registry import (
    apply_erc_plugin,
    clear_user_erc_plugins,
    list_erc_plugin_names,
    register_erc_plugin,
)


@pytest.fixture(autouse=True)
def _clear_user_plugins():
    yield
    clear_user_erc_plugins()


def test_builtin_plugin_names_match_rule_packs_exports():
    names = set(list_erc_plugin_names())
    for export in erp.ERC_RULE_PACK_EXPORTS:
        assert export.startswith("apply_")
        expected = export[len("apply_") :]
        assert expected in names


def test_apply_i2c_pullup_pack_via_registry(tmp_db, monkeypatch):
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
    for ref, net in (("U1", sda), ("U2", sda), ("U3", scl), ("U4", scl)):
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
    apply_erc_plugin(board, "i2c_pullup_pack", scl, sda)
    assert len(getattr(board, "_erc_hooks", [])) == 1
    run_erc(board)


def test_board_apply_erc_plugin_delegates(tmp_db, monkeypatch):
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
    for ref, net in (("U1", sda), ("U2", sda), ("U3", scl), ("U4", scl)):
        u = Part("Device", "R", value="0", ref=ref)
        u[1] += net
        u[2] += gnd
    for net in (sda, scl):
        pu = Component("R_10k_0805")
        pu["1"] += vcc
        pu["2"] += net

    board = Board(size_mm=(10, 10))
    board.apply_erc_plugin("i2c_pullup_pack", scl, sda)
    run_erc(board)


def test_register_user_plugin():
    seen: list[int] = []

    def my_plugin(board, x):
        _ = board
        seen.append(x)

    register_erc_plugin("my_demo_plugin", my_plugin)
    board = Board(size_mm=(1, 1))
    apply_erc_plugin(board, "my_demo_plugin", 42)
    assert seen == [42]


def test_register_duplicate_user_plugin_raises():
    register_erc_plugin("dup_test_plugin", lambda b: None)

    with pytest.raises(OpenHaCError, match="already registered"):
        register_erc_plugin("dup_test_plugin", lambda b: None)


def test_builtin_name_reserved_without_overwrite():
    with pytest.raises(OpenHaCError, match="reserved"):
        register_erc_plugin("i2c_pullup_pack", lambda b: None)


def test_unknown_plugin_raises():
    board = Board(size_mm=(1, 1))
    with pytest.raises(OpenHaCError, match="Unknown ERC plugin"):
        apply_erc_plugin(board, "no_such_plugin_xyz")


def test_shadow_builtin_with_overwrite(tmp_db, monkeypatch):
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
    for ref, net in (("U1", sda), ("U2", sda), ("U3", scl), ("U4", scl)):
        u = Part("Device", "R", value="0", ref=ref)
        u[1] += net
        u[2] += gnd
    for net in (sda, scl):
        pu = Component("R_10k_0805")
        pu["1"] += vcc
        pu["2"] += net

    called: list[str] = []

    def shadow(board, s, d):
        _ = board, s, d
        called.append("shadow")

    register_erc_plugin("i2c_pullup_pack", shadow, overwrite=True)
    board = Board(size_mm=(10, 10))
    board.apply_erc_plugin("i2c_pullup_pack", scl, sda)
    assert called == ["shadow"]
    assert getattr(board, "_erc_hooks", []) == []

    clear_user_erc_plugins()
    board2 = Board(size_mm=(10, 10))
    board2.apply_erc_plugin("i2c_pullup_pack", scl, sda)
    assert len(getattr(board2, "_erc_hooks", [])) == 1
    run_erc(board2)
