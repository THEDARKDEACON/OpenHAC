"""Tests for openhac.compiler.rule_check — ERC and DRC checks."""

import pytest
from unittest.mock import patch, MagicMock

from openhac.core.base import Module
from openhac.core.board import Board
from openhac.compiler.rule_check import (
    run_erc,
    run_drc,
    ERCPowerBudgetError,
    ERCFloatingNetError,
    ERCUnconnectedPinError,
    ERCMissingPowerFlagError,
    ERCPluginError,
    DRCViolationError,
    calculate_ipc2152_trace_width,
    _effective_drc_defaults,
)
from openhac.stdlib.erc_rules import (
    i2c_pullup_erc_hook,
    mdio_pullup_erc_hook,
    missing_footprint_erc_hook,
    one_wire_pullup_erc_hook,
    reset_pullup_erc_hook,
    spi_cs_pullup_erc_hook,
    uart_rx_pullup_erc_hook,
)


# ---------------------------------------------------------------------------
# ERC — Power Budget
# ---------------------------------------------------------------------------


class TestERCPowerBudget:

    def test_passes_within_budget(self):
        board = Board(size_mm=(60, 40))
        supply = Module("PSU")
        supply.source_current_max_ma = 500
        load = Module("MCU")
        load.max_current_draw_ma = 250
        board.add_module(supply)
        board.add_module(load)
        # Should not raise
        run_erc(board)

    def test_fails_over_budget(self):
        board = Board(size_mm=(60, 40))
        supply = Module("PSU")
        supply.source_current_max_ma = 100
        load = Module("MCU")
        load.max_current_draw_ma = 250
        board.add_module(supply)
        board.add_module(load)
        with pytest.raises(ERCPowerBudgetError, match="exceeds"):
            run_erc(board)

    def test_no_sources_skips_budget(self):
        board = Board(size_mm=(60, 40))
        load = Module("MCU")
        load.max_current_draw_ma = 250
        board.add_module(load)
        # No supply → budget check skipped, should not raise
        run_erc(board)

    def test_exact_budget(self):
        board = Board(size_mm=(60, 40))
        supply = Module("PSU")
        supply.source_current_max_ma = 250
        load = Module("MCU")
        load.max_current_draw_ma = 250
        board.add_module(supply)
        board.add_module(load)
        # Exact match (not exceeding) should pass
        run_erc(board)

    def test_dict_supply_requires_dict_draw(self):
        """PWR-001: dict supply forbids scalar max_current_draw_ma on consumers."""
        board = Board(size_mm=(60, 40))
        supply = Module("PSU")
        supply.source_current_max_ma = {"5V": 3000, "3V3": 800}
        load = Module("MCU")
        load.max_current_draw_ma = 100
        board.add_module(supply)
        board.add_module(load)
        with pytest.raises(ERCPowerBudgetError, match="per-rail dicts"):
            run_erc(board)

    def test_per_rail_budget_passes(self):
        board = Board(size_mm=(60, 40))
        supply = Module("PSU")
        supply.source_current_max_ma = {"3V3": 500, "5V": 2000}
        a = Module("A")
        a.max_current_draw_ma = {"3V3": 100}
        b = Module("B")
        b.max_current_draw_ma = {"5V": 500}
        board.add_module(supply)
        board.add_module(a)
        board.add_module(b)
        run_erc(board)

    def test_per_rail_budget_fails(self):
        board = Board(size_mm=(60, 40))
        supply = Module("PSU")
        supply.source_current_max_ma = {"3V3": 100}
        load = Module("MCU")
        load.max_current_draw_ma = {"3V3": 150}
        board.add_module(supply)
        board.add_module(load)
        with pytest.raises(ERCPowerBudgetError, match="rail '3V3'"):
            run_erc(board)

    def test_dict_draw_requires_dict_supply_when_sources_exist(self):
        board = Board(size_mm=(60, 40))
        supply = Module("PSU")
        supply.source_current_max_ma = 500
        load = Module("MCU")
        load.max_current_draw_ma = {"3V3": 100}
        board.add_module(supply)
        board.add_module(load)
        with pytest.raises(ERCPowerBudgetError, match="source_current_max_ma dict"):
            run_erc(board)

    def test_nested_scalar_supply_ignored_under_dict_subtree(self):
        """Scalar source_current_max_ma on nested regulators must not inflate the supply pool."""

        class Parent(Module):
            def __init__(self):
                super().__init__("PMU")
                self.source_current_max_ma = {"3V3": 200}
                buck = Module("BUCK")
                buck.source_current_max_ma = 3000
                self.add(buck)

        board = Board(size_mm=(60, 40))
        p = Parent()
        load = Module("MCU")
        load.max_current_draw_ma = {"3V3": 180}
        board.add_module(p)
        board.add_module(load)
        run_erc(board)

        board2 = Board(size_mm=(60, 40))
        p2 = Parent()
        load2 = Module("MCU")
        load2.max_current_draw_ma = {"3V3": 220}
        board2.add_module(p2)
        board2.add_module(load2)
        with pytest.raises(ERCPowerBudgetError, match="rail '3V3'"):
            run_erc(board2)

    def test_buck_input_current_on_input_rail_passes(self):
        """PWR-002: model buck input using buck_input_current_ma + per-rail draw."""
        from openhac.stdlib.power import buck_input_current_ma

        board = Board(size_mm=(60, 40))
        supply = Module("PSU")
        supply.source_current_max_ma = {"12V": 50}
        load = Module("SYS")
        i_in = buck_input_current_ma(100, 3.3, 12.0, 0.9)
        load.max_current_draw_ma = {"12V": i_in}
        board.add_module(supply)
        board.add_module(load)
        run_erc(board)

    def test_buck_input_current_exceeds_supply_fails(self):
        from openhac.stdlib.power import buck_input_current_ma

        board = Board(size_mm=(60, 40))
        supply = Module("PSU")
        supply.source_current_max_ma = {"12V": 20}
        load = Module("SYS")
        i_in = buck_input_current_ma(100, 3.3, 12.0, 0.9)
        load.max_current_draw_ma = {"12V": i_in}
        board.add_module(supply)
        board.add_module(load)
        with pytest.raises(ERCPowerBudgetError, match="rail '12V'"):
            run_erc(board)


# ---------------------------------------------------------------------------
# ERC — Exception hierarchy
# ---------------------------------------------------------------------------


class TestERCExceptions:

    def test_all_inherit_from_openhac_error(self):
        from openhac.core.base import OpenHaCError
        for cls in [ERCPowerBudgetError, ERCFloatingNetError,
                    ERCUnconnectedPinError, ERCMissingPowerFlagError,
                    DRCViolationError]:
            assert issubclass(cls, OpenHaCError)


# ---------------------------------------------------------------------------
# IPC-2152 trace width (stub → should become real)
# ---------------------------------------------------------------------------


class TestIPC2152:

    def test_returns_float(self):
        result = calculate_ipc2152_trace_width(1.0)
        assert isinstance(result, float)
        assert result > 0

    def test_higher_current_wider_trace(self):
        w1 = calculate_ipc2152_trace_width(0.5)
        w2 = calculate_ipc2152_trace_width(2.0)
        assert w2 > w1

    def test_higher_temp_rise_narrower_trace(self):
        w1 = calculate_ipc2152_trace_width(1.0, temp_rise_c=10)
        w2 = calculate_ipc2152_trace_width(1.0, temp_rise_c=30)
        assert w2 < w1

    def test_thicker_copper_narrower_trace(self):
        w1 = calculate_ipc2152_trace_width(1.0, copper_oz=1.0)
        w2 = calculate_ipc2152_trace_width(1.0, copper_oz=2.0)
        assert w2 < w1

    def test_known_value_1A(self):
        """1A at 10°C rise on 1oz copper should be roughly 0.2–0.5mm."""
        w = calculate_ipc2152_trace_width(1.0, temp_rise_c=10, copper_oz=1.0)
        assert 0.1 < w < 1.0  # sanity check range

    def test_invalid_current_raises(self):
        with pytest.raises(ValueError, match="current_amps"):
            calculate_ipc2152_trace_width(0)

    def test_invalid_temp_rise_raises(self):
        with pytest.raises(ValueError, match="temp_rise_c"):
            calculate_ipc2152_trace_width(1.0, temp_rise_c=0)


# ---------------------------------------------------------------------------
# DRC
# ---------------------------------------------------------------------------


class TestDRC:

    def test_passes_valid_board(self):
        board = Board(size_mm=(60, 40))
        run_drc(board)

    def test_fails_invalid_dimensions(self):
        board = Board(size_mm=(0, 40))
        with pytest.raises(DRCViolationError, match="Invalid board dimensions"):
            run_drc(board)

    def test_fails_module_out_of_bounds(self):
        board = Board(size_mm=(20, 20))
        mod = Module("big")
        mod.width = 15
        mod.height = 15
        mod.placed_x = 10
        mod.placed_y = 10
        board.add_module(mod)
        with pytest.raises(DRCViolationError, match="exceeds board"):
            run_drc(board)

    def test_passes_module_in_bounds(self):
        board = Board(size_mm=(100, 100))
        mod = Module("small")
        mod.width = 10
        mod.height = 10
        mod.placed_x = 5
        mod.placed_y = 5
        board.add_module(mod)
        run_drc(board)

    def test_ipc_trace_wider_than_design_min_raises(self):
        """PCB-006: stated draw must not require wider traces than default fab min (0.15mm)."""
        board = Board(size_mm=(100, 100))
        mod = Module("heavy")
        mod.max_current_draw_ma = 1000  # ~0.3mm IPC @ 1oz / 10°C — exceeds 0.15mm default
        board.add_module(mod)
        with pytest.raises(DRCViolationError, match="IPC-2152"):
            run_drc(board)

    def test_board_min_trace_width_overrides_default(self):
        """High draw is allowed when ``Board.min_trace_width_mm`` meets IPC."""
        board = Board(size_mm=(100, 100))
        board.min_trace_width_mm = 0.35
        mod = Module("heavy")
        mod.max_current_draw_ma = 1000
        board.add_module(mod)
        run_drc(board)

    def test_ipc_trace_within_design_min_passes(self):
        board = Board(size_mm=(100, 100))
        mod = Module("light")
        mod.max_current_draw_ma = 500  # IPC width below 0.15mm default
        board.add_module(mod)
        run_drc(board)


# ---------------------------------------------------------------------------
# SCH-004 / SCH-005 — Power rail registry & ERC hooks
# ---------------------------------------------------------------------------


class TestSCH004DeclarePowerRail:
    def test_declare_power_rail_requires_pwr_flag(self, tmp_db, monkeypatch):
        import openhac.core  # noqa: F401
        from skidl import Net, Part

        from openhac.core.base import Component

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

        gnd = Net("GND")
        Part("power", "PWR_FLAG")[1] += gnd
        rail = Net("XRAIL_CUSTOM")
        board = Board(size_mm=(10, 10))
        board.declare_power_rail("VPP", rail)
        r = Component("R_10k_0805")
        r["1"] += rail
        r["2"] += gnd

        with pytest.raises(Exception) as ei:
            run_erc(board)
        exc = ei.value
        nested = getattr(exc, "exceptions", None)
        text = "\n".join(str(e) for e in nested) if nested else str(exc)
        assert "PWR_FLAG" in text


class TestSCH005ErcHooks:
    def test_erc_hook_can_fail_check(self, tmp_db, monkeypatch):
        import openhac.core  # noqa: F401
        from skidl import Net, Part

        from openhac.core.base import Component

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
        Part("power", "PWR_FLAG")[1] += vcc
        Part("power", "PWR_FLAG")[1] += gnd
        r = Component("R_10k_0805")
        r["1"] += vcc
        r["2"] += gnd
        board = Board(size_mm=(10, 10))
        board.register_erc_hook(lambda b: ["demo SCH-005: add pull-ups on I2C"])

        with pytest.raises(ERCPluginError, match="SCH-005"):
            run_erc(board)

    def test_i2c_pullup_example_hook_passes_with_resistors(self, tmp_db, monkeypatch):
        import openhac.core  # noqa: F401
        from skidl import Net, Part

        from openhac.core.base import Component

        _, dm = tmp_db
        row = {
            "generic_name": "R_10k_0805",
            "kicad_symbol": "Device:R",
            "kicad_footprint": "Resistor_SMD:R_0805_2012Metric",
            "manufacturer": "",
            "mpn": "X",
            "supplier_sku": "",
            "description": "",
        }
        dm.insert_component(row)
        monkeypatch.setattr(Component, "db", dm)

        vcc, gnd = Net("3V3"), Net("GND")
        sda, scl = Net("SDA"), Net("SCL")
        Part("power", "PWR_FLAG")[1] += vcc
        Part("power", "PWR_FLAG")[1] += gnd
        # Two pins per I2C net (e.g. host + device) so net-level ERC is clean.
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
        board.register_erc_hook(i2c_pullup_erc_hook(sda, scl))
        run_erc(board)

    def test_i2c_pullup_example_hook_fails_without_pullups(self, tmp_db, monkeypatch):
        import openhac.core  # noqa: F401
        from skidl import Net, Part

        from openhac.core.base import Component

        _, dm = tmp_db
        row = {
            "generic_name": "R_10k_0805",
            "kicad_symbol": "Device:R",
            "kicad_footprint": "Resistor_SMD:R_0805_2012Metric",
            "manufacturer": "",
            "mpn": "X",
            "supplier_sku": "",
            "description": "",
        }
        dm.insert_component(row)
        monkeypatch.setattr(Component, "db", dm)

        vcc, gnd = Net("3V3"), Net("GND")
        sda, scl = Net("SDA"), Net("SCL")
        Part("power", "PWR_FLAG")[1] += vcc
        Part("power", "PWR_FLAG")[1] += gnd
        for ref, net in (("U_SDA1", sda), ("U_SDA2", sda), ("U_SCL1", scl), ("U_SCL2", scl)):
            u = Part("Device", "R", value="0", ref=ref)
            u[1] += net
            u[2] += gnd

        board = Board(size_mm=(10, 10))
        board.register_erc_hook(i2c_pullup_erc_hook(sda, scl))
        with pytest.raises(ERCPluginError, match="I2C"):
            run_erc(board)

    def test_missing_footprint_example_hook_fails_without_footprint(self, tmp_db, monkeypatch):
        import openhac.core  # noqa: F401
        from skidl import Net, Part

        from openhac.core.base import Component

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
        Part("power", "PWR_FLAG")[1] += vcc
        Part("power", "PWR_FLAG")[1] += gnd
        r = Part("Device", "R", value="1k", footprint="")
        r[1] += vcc
        r[2] += gnd

        board = Board(size_mm=(10, 10))
        board.register_erc_hook(missing_footprint_erc_hook)
        with pytest.raises(ERCPluginError, match="footprint"):
            run_erc(board)

    def test_spi_cs_pullup_example_passes_with_resistor(self, tmp_db, monkeypatch):
        import openhac.core  # noqa: F401
        from skidl import Net, Part

        from openhac.core.base import Component

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
        cs = Net("CSn")
        Part("power", "PWR_FLAG")[1] += vcc
        Part("power", "PWR_FLAG")[1] += gnd
        for ref, net in (("U_M1", cs), ("U_M2", cs)):
            u = Part("Device", "R", value="0", ref=ref)
            u[1] += net
            u[2] += gnd
        pu = Component("R_10k_0805")
        pu["1"] += vcc
        pu["2"] += cs

        board = Board(size_mm=(10, 10))
        board.register_erc_hook(spi_cs_pullup_erc_hook(cs))
        run_erc(board)

    def test_reset_pullup_example_passes_with_resistor(self, tmp_db, monkeypatch):
        import openhac.core  # noqa: F401
        from skidl import Net, Part

        from openhac.core.base import Component

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
        rst = Net("RSTn")
        Part("power", "PWR_FLAG")[1] += vcc
        Part("power", "PWR_FLAG")[1] += gnd
        for ref, net in (("U_A", rst), ("U_B", rst)):
            u = Part("Device", "R", value="0", ref=ref)
            u[1] += net
            u[2] += gnd
        pu = Component("R_10k_0805")
        pu["1"] += vcc
        pu["2"] += rst

        board = Board(size_mm=(10, 10))
        board.register_erc_hook(reset_pullup_erc_hook(rst))
        run_erc(board)

    def test_mdio_pullup_example_passes_with_resistor(self, tmp_db, monkeypatch):
        import openhac.core  # noqa: F401
        from skidl import Net, Part

        from openhac.core.base import Component

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
        mdio = Net("MDIO")
        Part("power", "PWR_FLAG")[1] += vcc
        Part("power", "PWR_FLAG")[1] += gnd
        u = Part("Device", "R", value="0", ref="U_PHY")
        u[1] += mdio
        u[2] += gnd
        pu = Component("R_10k_0805")
        pu["1"] += vcc
        pu["2"] += mdio

        board = Board(size_mm=(10, 10))
        board.register_erc_hook(mdio_pullup_erc_hook(mdio))
        run_erc(board)

    def test_one_wire_pullup_example_passes_with_resistor(self, tmp_db, monkeypatch):
        import openhac.core  # noqa: F401
        from skidl import Net, Part

        from openhac.core.base import Component

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
        dq = Net("DQ")
        Part("power", "PWR_FLAG")[1] += vcc
        Part("power", "PWR_FLAG")[1] += gnd
        for ref, net in (("U_ROM", dq), ("U_MCU", dq)):
            u = Part("Device", "R", value="0", ref=ref)
            u[1] += net
            u[2] += gnd
        pu = Component("R_10k_0805")
        pu["1"] += vcc
        pu["2"] += dq

        board = Board(size_mm=(10, 10))
        board.register_erc_hook(one_wire_pullup_erc_hook(dq))
        run_erc(board)

    def test_one_wire_pullup_example_fails_without_pullup(self, tmp_db, monkeypatch):
        import openhac.core  # noqa: F401
        from skidl import Net, Part

        from openhac.core.base import Component

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
        dq = Net("DQ")
        Part("power", "PWR_FLAG")[1] += vcc
        Part("power", "PWR_FLAG")[1] += gnd
        for ref, net in (("U_ROM", dq), ("U_MCU", dq)):
            u = Part("Device", "R", value="0", ref=ref)
            u[1] += net
            u[2] += gnd

        board = Board(size_mm=(10, 10))
        board.register_erc_hook(one_wire_pullup_erc_hook(dq))
        with pytest.raises(ERCPluginError, match="1-Wire"):
            run_erc(board)

    def test_uart_rx_pullup_example_passes_with_resistor(self, tmp_db, monkeypatch):
        import openhac.core  # noqa: F401
        from skidl import Net, Part

        from openhac.core.base import Component

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
        rx = Net("UART_RX")
        Part("power", "PWR_FLAG")[1] += vcc
        Part("power", "PWR_FLAG")[1] += gnd
        for ref, net in (("U_MCU_TX", rx), ("U_LEVELSHIFT_RX", rx)):
            u = Part("Device", "R", value="0", ref=ref)
            u[1] += net
            u[2] += gnd
        pu = Component("R_10k_0805")
        pu["1"] += vcc
        pu["2"] += rx

        board = Board(size_mm=(10, 10))
        board.register_erc_hook(uart_rx_pullup_erc_hook(rx))
        run_erc(board)

    def test_uart_rx_pullup_example_fails_without_pullup(self, tmp_db, monkeypatch):
        import openhac.core  # noqa: F401
        from skidl import Net, Part

        from openhac.core.base import Component

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
        rx = Net("UART_RX")
        Part("power", "PWR_FLAG")[1] += vcc
        Part("power", "PWR_FLAG")[1] += gnd
        for ref, net in (("U_MCU_TX", rx), ("U_CONN_RX", rx)):
            u = Part("Device", "R", value="0", ref=ref)
            u[1] += net
            u[2] += gnd

        board = Board(size_mm=(10, 10))
        board.register_erc_hook(uart_rx_pullup_erc_hook(rx))
        with pytest.raises(ERCPluginError, match="UART"):
            run_erc(board)


# ---------------------------------------------------------------------------
# LIB-005 — JLC Extended assembly count (optional DRC)
# ---------------------------------------------------------------------------


class TestREL001PassiveVoltageRatings:
    def test_drc_requires_cap_voltage_rating_when_enabled(self, tmp_db, monkeypatch):
        import openhac.core  # noqa: F401
        from skidl import Net, Part

        from openhac.core.base import Component

        _, dm = tmp_db
        dm.insert_component(
            {
                "generic_name": "C_bad_cap",
                "kicad_symbol": "Device:C",
                "kicad_footprint": "Capacitor_SMD:C_0805_2012Metric",
                "manufacturer": "",
                "mpn": "X",
                "supplier_sku": "",
                "description": "",
                "category": "capacitors",
            }
        )
        monkeypatch.setattr(Component, "db", dm)

        vcc, gnd = Net("3V3"), Net("GND")
        Part("power", "PWR_FLAG")[1] += vcc
        Part("power", "PWR_FLAG")[1] += gnd

        class M(Module):
            def __init__(self):
                super().__init__("m1")
                c = self.add(Component("C_bad_cap"))
                c["1"] += vcc
                c["2"] += gnd

        board = Board(size_mm=(20, 20), require_passive_voltage_ratings=True)
        board.add_module(M())
        with pytest.raises(DRCViolationError, match="voltage_rating"):
            run_drc(board)

    def test_drc_requires_resistor_power_rating_when_enabled(self, tmp_db, monkeypatch):
        import openhac.core  # noqa: F401
        from skidl import Net, Part

        from openhac.core.base import Component

        _, dm = tmp_db
        dm.insert_component(
            {
                "generic_name": "R_bad_power",
                "kicad_symbol": "Device:R",
                "kicad_footprint": "Resistor_SMD:R_0805_2012Metric",
                "manufacturer": "",
                "mpn": "X",
                "supplier_sku": "",
                "description": "",
                "category": "resistors",
            }
        )
        monkeypatch.setattr(Component, "db", dm)

        vcc, gnd = Net("3V3"), Net("GND")
        Part("power", "PWR_FLAG")[1] += vcc
        Part("power", "PWR_FLAG")[1] += gnd

        class M(Module):
            def __init__(self):
                super().__init__("m1")
                r = self.add(Component("R_bad_power"))
                r["1"] += vcc
                r["2"] += gnd

        board = Board(size_mm=(20, 20), require_passive_power_ratings=True)
        board.add_module(M())
        with pytest.raises(DRCViolationError, match="power_watts"):
            run_drc(board)

    def test_drc_requires_inductor_voltage_rating_when_enabled(self, tmp_db, monkeypatch):
        import openhac.core  # noqa: F401
        from skidl import Net, Part

        from openhac.core.base import Component

        _, dm = tmp_db
        dm.insert_component(
            {
                "generic_name": "L_bad_ind",
                "kicad_symbol": "Device:R",
                "kicad_footprint": "Inductor_SMD:L_0805_2012Metric",
                "manufacturer": "",
                "mpn": "X",
                "supplier_sku": "",
                "description": "",
                "category": "inductors",
            }
        )
        monkeypatch.setattr(Component, "db", dm)

        vcc, gnd = Net("3V3"), Net("GND")
        Part("power", "PWR_FLAG")[1] += vcc
        Part("power", "PWR_FLAG")[1] += gnd

        class M(Module):
            def __init__(self):
                super().__init__("m1")
                x = self.add(Component("L_bad_ind"))
                x["1"] += vcc
                x["2"] += gnd

        board = Board(size_mm=(20, 20), require_inductor_voltage_ratings=True)
        board.add_module(M())
        with pytest.raises(DRCViolationError, match="voltage_rating"):
            run_drc(board)

    def test_cap_voltage_derating_vs_declared_rail(self, tmp_db, monkeypatch):
        import openhac.core  # noqa: F401
        from skidl import Net, Part

        from openhac.core.base import Component

        _, dm = tmp_db
        dm.insert_component(
            {
                "generic_name": "C_derate_ok",
                "kicad_symbol": "Device:C",
                "kicad_footprint": "Capacitor_SMD:C_0805_2012Metric",
                "manufacturer": "",
                "mpn": "X",
                "supplier_sku": "",
                "description": "",
                "category": "capacitors",
                "voltage_rating": 10.0,
            }
        )
        dm.insert_component(
            {
                "generic_name": "C_derate_bad",
                "kicad_symbol": "Device:C",
                "kicad_footprint": "Capacitor_SMD:C_0805_2012Metric",
                "manufacturer": "",
                "mpn": "Y",
                "supplier_sku": "",
                "description": "",
                "category": "capacitors",
                "voltage_rating": 5.0,
            }
        )
        monkeypatch.setattr(Component, "db", dm)

        vcc, gnd = Net("3V3"), Net("GND")
        Part("power", "PWR_FLAG")[1] += vcc
        Part("power", "PWR_FLAG")[1] += gnd

        class Good(Module):
            def __init__(self):
                super().__init__("g")
                c = self.add(Component("C_derate_ok"))
                c["1"] += vcc
                c["2"] += gnd

        board = Board(
            size_mm=(20, 20),
            declared_supply_voltages_v={"3V3": 3.3},
            require_cap_voltage_derating_ratio=2.0,
        )
        board.add_module(Good())
        run_drc(board)

        class Bad(Module):
            def __init__(self):
                super().__init__("b")
                c = self.add(Component("C_derate_bad"))
                c["1"] += vcc
                c["2"] += gnd

        board2 = Board(
            size_mm=(20, 20),
            declared_supply_voltages_v={"3v3": 3.3},
            require_cap_voltage_derating_ratio=2.0,
        )
        board2.add_module(Bad())
        with pytest.raises(DRCViolationError, match="voltage_rating must be"):
            run_drc(board2)


class TestLIB006StrictPassiveCatalog:
    def test_drc_requires_cap_tolerance_when_strict(self, tmp_db, monkeypatch):
        import openhac.core  # noqa: F401
        from skidl import Net, Part

        from openhac.core.base import Component

        _, dm = tmp_db
        dm.insert_component(
            {
                "generic_name": "C_no_tol",
                "kicad_symbol": "Device:C",
                "kicad_footprint": "Capacitor_SMD:C_0805_2012Metric",
                "manufacturer": "",
                "mpn": "X",
                "supplier_sku": "",
                "description": "",
                "category": "capacitors",
                "voltage_rating": 50.0,
            }
        )
        monkeypatch.setattr(Component, "db", dm)

        vcc, gnd = Net("3V3"), Net("GND")
        Part("power", "PWR_FLAG")[1] += vcc
        Part("power", "PWR_FLAG")[1] += gnd

        class M(Module):
            def __init__(self):
                super().__init__("m1")
                c = self.add(Component("C_no_tol"))
                c["1"] += vcc
                c["2"] += gnd

        board = Board(size_mm=(20, 20), strict_passive_catalog_fields=True)
        board.add_module(M())
        with pytest.raises(DRCViolationError, match="Capacitor.*tolerance"):
            run_drc(board)

    def test_drc_passes_cap_with_tolerance_when_strict(self, tmp_db, monkeypatch):
        import openhac.core  # noqa: F401
        from skidl import Net, Part

        from openhac.core.base import Component

        _, dm = tmp_db
        dm.insert_component(
            {
                "generic_name": "C_ok_tol",
                "kicad_symbol": "Device:C",
                "kicad_footprint": "Capacitor_SMD:C_0805_2012Metric",
                "manufacturer": "",
                "mpn": "X",
                "supplier_sku": "",
                "description": "",
                "category": "capacitors",
                "voltage_rating": 50.0,
                "tolerance": "10%",
            }
        )
        monkeypatch.setattr(Component, "db", dm)

        vcc, gnd = Net("3V3"), Net("GND")
        Part("power", "PWR_FLAG")[1] += vcc
        Part("power", "PWR_FLAG")[1] += gnd

        class M(Module):
            def __init__(self):
                super().__init__("m1")
                c = self.add(Component("C_ok_tol"))
                c["1"] += vcc
                c["2"] += gnd

        board = Board(size_mm=(20, 20), strict_passive_catalog_fields=True)
        board.add_module(M())
        run_drc(board)

    def test_drc_requires_inductor_tolerance_when_strict(self, tmp_db, monkeypatch):
        import openhac.core  # noqa: F401
        from skidl import Net, Part

        from openhac.core.base import Component

        _, dm = tmp_db
        dm.insert_component(
            {
                "generic_name": "L_no_tol",
                "kicad_symbol": "Device:R",
                "kicad_footprint": "Resistor_SMD:R_0805_2012Metric",
                "manufacturer": "",
                "mpn": "X",
                "supplier_sku": "",
                "description": "",
                "category": "inductors",
            }
        )
        monkeypatch.setattr(Component, "db", dm)

        vcc, gnd = Net("3V3"), Net("GND")
        Part("power", "PWR_FLAG")[1] += vcc
        Part("power", "PWR_FLAG")[1] += gnd

        class M(Module):
            def __init__(self):
                super().__init__("m1")
                x = self.add(Component("L_no_tol"))
                x["1"] += vcc
                x["2"] += gnd

        board = Board(size_mm=(20, 20), strict_passive_catalog_fields=True)
        board.add_module(M())
        with pytest.raises(DRCViolationError, match="Inductor.*tolerance"):
            run_drc(board)


class TestMFG004FabProfiles:
    def test_generic_2layer_profile_merges_via_drill(self):
        board = Board(size_mm=(10, 10), fab_profile="generic_2layer")
        d = _effective_drc_defaults(board)
        assert d["min_via_drill_mm"] == pytest.approx(0.35)
        assert d["min_trace_width_mm"] == pytest.approx(0.15)

    def test_eurocircuits_4layer_profile_loads(self):
        board = Board(size_mm=(10, 10), fab_profile="eurocircuits_4layer")
        d = _effective_drc_defaults(board)
        assert d["min_via_drill_mm"] == pytest.approx(0.25)
        assert d["min_trace_width_mm"] == pytest.approx(0.1)

    def test_oshpark_2layer_profile_loads(self):
        board = Board(size_mm=(10, 10), fab_profile="oshpark_2layer")
        d = _effective_drc_defaults(board)
        assert d["min_trace_width_mm"] == pytest.approx(0.1524)
        assert d["min_via_drill_mm"] == pytest.approx(0.33)


class TestLIB005JlcExtendedLimit:
    def test_drc_fails_when_extended_count_exceeds_limit(self, tmp_db, monkeypatch):
        import openhac.core  # noqa: F401
        from skidl import Net, Part

        from openhac.core.base import Component

        _, dm = tmp_db
        base = {
            "kicad_symbol": "Device:R",
            "kicad_footprint": "Resistor_SMD:R_0805_2012Metric",
            "manufacturer": "",
            "mpn": "X",
            "supplier_sku": "",
            "description": "",
        }
        dm.insert_component({**base, "generic_name": "R_EXT_ONE", "jlc_class": "Extended"})
        dm.insert_component({**base, "generic_name": "R_EXT_TWO", "jlc_class": "Extended"})
        monkeypatch.setattr(Component, "db", dm)

        vcc, gnd = Net("3V3"), Net("GND")
        Part("power", "PWR_FLAG")[1] += vcc
        Part("power", "PWR_FLAG")[1] += gnd
        r1 = Component("R_EXT_ONE")
        r2 = Component("R_EXT_TWO")
        r1["1"] += vcc
        r1["2"] += gnd
        r2["1"] += vcc
        r2["2"] += gnd

        board = Board(size_mm=(10, 10))
        board.max_jlc_extended_parts = 1
        with pytest.raises(DRCViolationError, match="JLC assembly"):
            run_drc(board)

    def test_drc_passes_within_extended_limit(self, tmp_db, monkeypatch):
        import openhac.core  # noqa: F401
        from skidl import Net, Part

        from openhac.core.base import Component

        _, dm = tmp_db
        base = {
            "kicad_symbol": "Device:R",
            "kicad_footprint": "Resistor_SMD:R_0805_2012Metric",
            "manufacturer": "",
            "mpn": "X",
            "supplier_sku": "",
            "description": "",
        }
        dm.insert_component({**base, "generic_name": "R_EXT_ONE", "jlc_class": "Extended"})
        dm.insert_component({**base, "generic_name": "R_EXT_TWO", "jlc_class": "Extended"})
        monkeypatch.setattr(Component, "db", dm)

        vcc, gnd = Net("3V3"), Net("GND")
        Part("power", "PWR_FLAG")[1] += vcc
        Part("power", "PWR_FLAG")[1] += gnd
        r1 = Component("R_EXT_ONE")
        r2 = Component("R_EXT_TWO")
        r1["1"] += vcc
        r1["2"] += gnd
        r2["1"] += vcc
        r2["2"] += gnd

        board = Board(size_mm=(10, 10))
        board.max_jlc_extended_parts = 2
        run_drc(board)

    def test_drc_warns_when_extended_lines_and_warn_flag(self, tmp_db, monkeypatch, capsys):
        import openhac.core  # noqa: F401
        from skidl import Net, Part

        from openhac.core.base import Component

        _, dm = tmp_db
        base = {
            "kicad_symbol": "Device:R",
            "kicad_footprint": "Resistor_SMD:R_0805_2012Metric",
            "manufacturer": "",
            "mpn": "X",
            "supplier_sku": "",
            "description": "",
        }
        dm.insert_component({**base, "generic_name": "R_EXT_ONE", "jlc_class": "Extended"})
        monkeypatch.setattr(Component, "db", dm)

        vcc, gnd = Net("3V3"), Net("GND")
        Part("power", "PWR_FLAG")[1] += vcc
        Part("power", "PWR_FLAG")[1] += gnd
        r1 = Component("R_EXT_ONE")
        r1["1"] += vcc
        r1["2"] += gnd

        board = Board(size_mm=(10, 10), warn_jlc_extended_parts=True)
        run_drc(board)
        err = capsys.readouterr().err
        assert "LIB-005" in err and "JLC_Class" in err


# ---------------------------------------------------------------------------
# REL-003 — Minimum test points (optional DRC)
# ---------------------------------------------------------------------------


class TestREL003MinTestPoints:
    def test_drc_fails_when_below_min_test_points(self):
        board = Board(size_mm=(20, 20), min_test_points=1)
        board.add_module(Module("empty"))
        with pytest.raises(DRCViolationError, match="test point"):
            run_drc(board)

    def test_drc_passes_with_tp_generic(self, tmp_db, monkeypatch):
        import openhac.core  # noqa: F401

        from openhac.core.base import Component

        _, dm = tmp_db
        dm.insert_component(
            {
                "generic_name": "TP_Mech_1mm",
                "kicad_symbol": "Device:TestPoint",
                "kicad_footprint": "TestPoint:TestPoint_Pad_D1.0mm",
                "manufacturer": "",
                "mpn": "TP",
                "supplier_sku": "",
                "description": "",
                "category": "testability",
            }
        )
        monkeypatch.setattr(Component, "db", dm)

        class M(Module):
            def __init__(self):
                super().__init__("m1")
                self.add(Component("TP_Mech_1mm"))

        board = Board(size_mm=(20, 20), min_test_points=1)
        board.add_module(M())
        run_drc(board)

    def test_drc_rejects_negative_min_test_points(self):
        board = Board(size_mm=(20, 20), min_test_points=-1)
        with pytest.raises(DRCViolationError, match="min_test_points"):
            run_drc(board)

    def test_require_test_point_on_net_passes_when_tp_on_rail(self, tmp_db, monkeypatch):
        import openhac.core  # noqa: F401
        from skidl import Net, Part

        from openhac.core.base import Component

        _, dm = tmp_db
        dm.insert_component(
            {
                "generic_name": "TP_Mech_1mm",
                "kicad_symbol": "Device:TestPoint",
                "kicad_footprint": "TestPoint:TestPoint_Pad_D1.0mm",
                "manufacturer": "",
                "mpn": "TP",
                "supplier_sku": "",
                "description": "",
                "category": "testability",
            }
        )
        monkeypatch.setattr(Component, "db", dm)

        vcc, gnd = Net("3V3"), Net("GND")
        Part("power", "PWR_FLAG")[1] += vcc
        Part("power", "PWR_FLAG")[1] += gnd

        class M(Module):
            def __init__(self):
                super().__init__("m1")
                tp = self.add(Component("TP_Mech_1mm"))
                tp["1"] += vcc

        board = Board(size_mm=(20, 20), require_test_point_on_nets=("3V3",))
        board.add_module(M())
        run_drc(board)

    def test_require_test_point_on_net_fails_without_tp_on_rail(self, tmp_db, monkeypatch):
        import openhac.core  # noqa: F401
        from skidl import Net, Part

        from openhac.core.base import Component

        _, dm = tmp_db
        dm.insert_component(
            {
                "generic_name": "TP_Mech_1mm",
                "kicad_symbol": "Device:TestPoint",
                "kicad_footprint": "TestPoint:TestPoint_Pad_D1.0mm",
                "manufacturer": "",
                "mpn": "TP",
                "supplier_sku": "",
                "description": "",
                "category": "testability",
            }
        )
        monkeypatch.setattr(Component, "db", dm)

        vcc, gnd = Net("3V3"), Net("GND")
        Part("power", "PWR_FLAG")[1] += vcc
        Part("power", "PWR_FLAG")[1] += gnd

        class M(Module):
            def __init__(self):
                super().__init__("m1")
                tp = self.add(Component("TP_Mech_1mm"))
                tp["1"] += gnd

        board = Board(size_mm=(20, 20), require_test_point_on_nets=("3V3",))
        board.add_module(M())
        with pytest.raises(DRCViolationError, match="require_test_point_on_nets"):
            run_drc(board)
