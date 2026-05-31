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
    hdmi_cec_pullup_erc_hook,
    hdmi_hpd_pullup_erc_hook,
    i2c_pullup_erc_hook,
    i2s_ws_pullup_erc_hook,
    stepper_dir_pullup_erc_hook,
    can_rx_pullup_erc_hook,
    eth_phy_int_n_pullup_erc_hook,
    pcie_wake_n_pullup_erc_hook,
    rtc_int_n_pullup_erc_hook,
    rs485_re_n_pullup_erc_hook,
    usb_vbus_sense_pullup_erc_hook,
    jtag_tck_pullup_erc_hook,
    jtag_tms_pullup_erc_hook,
    lin_bus_pullup_erc_hook,
    mdio_pullup_erc_hook,
    missing_footprint_erc_hook,
    one_wire_pullup_erc_hook,
    power_good_pullup_erc_hook,
    reset_pullup_erc_hook,
    sd_cd_pullup_erc_hook,
    sd_cmd_pullup_erc_hook,
    sensor_interrupt_pullup_erc_hook,
    smbus_alert_pullup_erc_hook,
    spi_cs_pullup_erc_hook,
    spi_hold_n_pullup_erc_hook,
    spi_wp_n_pullup_erc_hook,
    spi_miso_pullup_erc_hook,
    swd_swdio_pullup_erc_hook,
    uart_rx_pullup_erc_hook,
    usb_otg_id_pullup_erc_hook,
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

    def test_rail_conversion_propagates_supply_to_output_rail_passes(self):
        """PWR-002 stretch: declare_rail_conversion allows checking a derived rail against upstream supply."""
        board = Board(
            size_mm=(60, 40),
            declared_supply_voltages_v={"12v": 12.0, "3v3": 3.3},
        )
        board.declare_rail_conversion("12V", "3V3", efficiency=0.9)
        supply = Module("PSU")
        supply.source_current_max_ma = {"12V": 200}
        load = Module("LOAD")
        load.max_current_draw_ma = {"3V3": 500}
        board.add_module(supply)
        board.add_module(load)
        run_erc(board)

    def test_rail_conversion_insufficient_upstream_supply_fails(self):
        board = Board(
            size_mm=(60, 40),
            declared_supply_voltages_v={"12v": 12.0, "3v3": 3.3},
        )
        board.declare_rail_conversion("12V", "3V3", efficiency=0.9)
        supply = Module("PSU")
        supply.source_current_max_ma = {"12V": 100}
        load = Module("LOAD")
        load.max_current_draw_ma = {"3V3": 500}
        board.add_module(supply)
        board.add_module(load)
        with pytest.raises(ERCPowerBudgetError, match="rail '3V3'"):
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

    def test_mixed_signal_ground_roles_without_merge_hint_warns_when_not_strict(self, capsys):
        class _Net:
            def __init__(self, name: str):
                self.name = name

        board = Board(size_mm=(60, 40), strict=False)
        board.declare_net_role(_Net("AGND"), "analog_ground")
        board.declare_net_role(_Net("DGND"), "digital_ground")

        run_drc(board)
        err = capsys.readouterr().err
        assert "SIG-006" in err
        assert "declare_net_merge_hint" in err

    def test_mixed_signal_ground_roles_without_merge_hint_fails_when_strict(self):
        class _Net:
            def __init__(self, name: str):
                self.name = name

        board = Board(size_mm=(60, 40), strict=True)
        board.declare_net_role(_Net("AGND"), "analog_ground")
        board.declare_net_role(_Net("DGND"), "digital_ground")

        with pytest.raises(DRCViolationError, match="SIG-006"):
            run_drc(board)

    def test_require_verified_parts_fails_when_unverified_jit_present(self, tmp_db, monkeypatch):
        """LIB-003 stretch: production gate should block medium/low confidence parts."""
        from openhac.core.base import Component
        from openhac.database.lookup_meta import CONFIDENCE_MEDIUM, LOOKUP_CONFIDENCE_KEY

        _, dm = tmp_db
        monkeypatch.setenv("OPENHAC_REQUIRE_VERIFIED_PARTS", "1")

        data = {
            "generic_name": "JIT_MED",
            "kicad_symbol": "Device:R",
            "kicad_footprint": "Resistor_SMD:R_0805_2012Metric",
            "manufacturer": "",
            "mpn": "X",
            "supplier_sku": "",
            "description": "",
            "category": "resistors",
            LOOKUP_CONFIDENCE_KEY: CONFIDENCE_MEDIUM,
        }
        monkeypatch.setattr(Component, "db", dm)
        Component("JIT_MED", comp_data=data)
        board = Board(size_mm=(60, 40))
        with pytest.raises(DRCViolationError) as ei:
            run_drc(board)
        # Deterministic offender ordering (sorted)
        assert "OPENHAC_REQUIRE_VERIFIED_PARTS" in str(ei.value)

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

    def test_swd_swdio_pullup_example_passes_with_resistor(self, tmp_db, monkeypatch):
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
        swdio = Net("SWDIO")
        Part("power", "PWR_FLAG")[1] += vcc
        Part("power", "PWR_FLAG")[1] += gnd
        for ref, net in (("U_DBG", swdio), ("U_MCU", swdio)):
            u = Part("Device", "R", value="0", ref=ref)
            u[1] += net
            u[2] += gnd
        pu = Component("R_10k_0805")
        pu["1"] += vcc
        pu["2"] += swdio

        board = Board(size_mm=(10, 10))
        board.register_erc_hook(swd_swdio_pullup_erc_hook(swdio))
        run_erc(board)

    def test_swd_swdio_pullup_example_fails_without_pullup(self, tmp_db, monkeypatch):
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
        swdio = Net("SWDIO")
        Part("power", "PWR_FLAG")[1] += vcc
        Part("power", "PWR_FLAG")[1] += gnd
        for ref, net in (("U_DBG", swdio), ("U_MCU", swdio)):
            u = Part("Device", "R", value="0", ref=ref)
            u[1] += net
            u[2] += gnd

        board = Board(size_mm=(10, 10))
        board.register_erc_hook(swd_swdio_pullup_erc_hook(swdio))
        with pytest.raises(ERCPluginError, match="SWDIO"):
            run_erc(board)

    def test_jtag_tms_pullup_example_passes_with_resistor(self, tmp_db, monkeypatch):
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
        tms = Net("TMS")
        Part("power", "PWR_FLAG")[1] += vcc
        Part("power", "PWR_FLAG")[1] += gnd
        for ref, net in (("U_TAP", tms), ("U_MCU", tms)):
            u = Part("Device", "R", value="0", ref=ref)
            u[1] += net
            u[2] += gnd
        pu = Component("R_10k_0805")
        pu["1"] += vcc
        pu["2"] += tms

        board = Board(size_mm=(10, 10))
        board.register_erc_hook(jtag_tms_pullup_erc_hook(tms))
        run_erc(board)

    def test_jtag_tms_pullup_example_fails_without_pullup(self, tmp_db, monkeypatch):
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
        tms = Net("TMS")
        Part("power", "PWR_FLAG")[1] += vcc
        Part("power", "PWR_FLAG")[1] += gnd
        for ref, net in (("U_TAP", tms), ("U_MCU", tms)):
            u = Part("Device", "R", value="0", ref=ref)
            u[1] += net
            u[2] += gnd

        board = Board(size_mm=(10, 10))
        board.register_erc_hook(jtag_tms_pullup_erc_hook(tms))
        with pytest.raises(ERCPluginError, match="JTAG TMS"):
            run_erc(board)

    def test_sd_cmd_pullup_example_passes_with_resistor(self, tmp_db, monkeypatch):
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
        cmd = Net("SD_CMD")
        Part("power", "PWR_FLAG")[1] += vcc
        Part("power", "PWR_FLAG")[1] += gnd
        for ref, net in (("U_SD", cmd), ("U_MCU", cmd)):
            u = Part("Device", "R", value="0", ref=ref)
            u[1] += net
            u[2] += gnd
        pu = Component("R_10k_0805")
        pu["1"] += vcc
        pu["2"] += cmd

        board = Board(size_mm=(10, 10))
        board.register_erc_hook(sd_cmd_pullup_erc_hook(cmd))
        run_erc(board)

    def test_sd_cmd_pullup_example_fails_without_pullup(self, tmp_db, monkeypatch):
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
        cmd = Net("SD_CMD")
        Part("power", "PWR_FLAG")[1] += vcc
        Part("power", "PWR_FLAG")[1] += gnd
        for ref, net in (("U_SD", cmd), ("U_MCU", cmd)):
            u = Part("Device", "R", value="0", ref=ref)
            u[1] += net
            u[2] += gnd

        board = Board(size_mm=(10, 10))
        board.register_erc_hook(sd_cmd_pullup_erc_hook(cmd))
        with pytest.raises(ERCPluginError, match="SD/MMC CMD"):
            run_erc(board)

    def test_spi_miso_pullup_example_passes_with_resistor(self, tmp_db, monkeypatch):
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
        miso = Net("MISO")
        Part("power", "PWR_FLAG")[1] += vcc
        Part("power", "PWR_FLAG")[1] += gnd
        for ref, net in (("U_FLASH", miso), ("U_MCU", miso)):
            u = Part("Device", "R", value="0", ref=ref)
            u[1] += net
            u[2] += gnd
        pu = Component("R_10k_0805")
        pu["1"] += vcc
        pu["2"] += miso

        board = Board(size_mm=(10, 10))
        board.register_erc_hook(spi_miso_pullup_erc_hook(miso))
        run_erc(board)

    def test_spi_miso_pullup_example_fails_without_pullup(self, tmp_db, monkeypatch):
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
        miso = Net("MISO")
        Part("power", "PWR_FLAG")[1] += vcc
        Part("power", "PWR_FLAG")[1] += gnd
        for ref, net in (("U_FLASH", miso), ("U_MCU", miso)):
            u = Part("Device", "R", value="0", ref=ref)
            u[1] += net
            u[2] += gnd

        board = Board(size_mm=(10, 10))
        board.register_erc_hook(spi_miso_pullup_erc_hook(miso))
        with pytest.raises(ERCPluginError, match="SPI MISO"):
            run_erc(board)

    def test_lin_bus_pullup_example_passes_with_resistor(self, tmp_db, monkeypatch):
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
        lin = Net("LIN")
        Part("power", "PWR_FLAG")[1] += vcc
        Part("power", "PWR_FLAG")[1] += gnd
        for ref, net in (("U_TRX", lin), ("U_MCU", lin)):
            u = Part("Device", "R", value="0", ref=ref)
            u[1] += net
            u[2] += gnd
        pu = Component("R_10k_0805")
        pu["1"] += vcc
        pu["2"] += lin

        board = Board(size_mm=(10, 10))
        board.register_erc_hook(lin_bus_pullup_erc_hook(lin))
        run_erc(board)

    def test_lin_bus_pullup_example_fails_without_pullup(self, tmp_db, monkeypatch):
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
        lin = Net("LIN")
        Part("power", "PWR_FLAG")[1] += vcc
        Part("power", "PWR_FLAG")[1] += gnd
        for ref, net in (("U_TRX", lin), ("U_MCU", lin)):
            u = Part("Device", "R", value="0", ref=ref)
            u[1] += net
            u[2] += gnd

        board = Board(size_mm=(10, 10))
        board.register_erc_hook(lin_bus_pullup_erc_hook(lin))
        with pytest.raises(ERCPluginError, match="LIN bus"):
            run_erc(board)

    def test_power_good_pullup_example_passes_with_resistor(self, tmp_db, monkeypatch):
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
        pg = Net("PGOOD")
        Part("power", "PWR_FLAG")[1] += vcc
        Part("power", "PWR_FLAG")[1] += gnd
        for ref, net in (("U_PMIC", pg), ("U_MCU", pg)):
            u = Part("Device", "R", value="0", ref=ref)
            u[1] += net
            u[2] += gnd
        pu = Component("R_10k_0805")
        pu["1"] += vcc
        pu["2"] += pg

        board = Board(size_mm=(10, 10))
        board.register_erc_hook(power_good_pullup_erc_hook(pg))
        run_erc(board)

    def test_power_good_pullup_example_fails_without_pullup(self, tmp_db, monkeypatch):
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
        pg = Net("PGOOD")
        Part("power", "PWR_FLAG")[1] += vcc
        Part("power", "PWR_FLAG")[1] += gnd
        for ref, net in (("U_PMIC", pg), ("U_MCU", pg)):
            u = Part("Device", "R", value="0", ref=ref)
            u[1] += net
            u[2] += gnd

        board = Board(size_mm=(10, 10))
        board.register_erc_hook(power_good_pullup_erc_hook(pg))
        with pytest.raises(ERCPluginError, match="Power-good"):
            run_erc(board)

    def test_i2s_ws_pullup_example_passes_with_resistor(self, tmp_db, monkeypatch):
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
        ws = Net("I2S_WS")
        Part("power", "PWR_FLAG")[1] += vcc
        Part("power", "PWR_FLAG")[1] += gnd
        for ref, net in (("U_CODEC", ws), ("U_MCU", ws)):
            u = Part("Device", "R", value="0", ref=ref)
            u[1] += net
            u[2] += gnd
        pu = Component("R_10k_0805")
        pu["1"] += vcc
        pu["2"] += ws

        board = Board(size_mm=(10, 10))
        board.register_erc_hook(i2s_ws_pullup_erc_hook(ws))
        run_erc(board)

    def test_i2s_ws_pullup_example_fails_without_pullup(self, tmp_db, monkeypatch):
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
        ws = Net("I2S_WS")
        Part("power", "PWR_FLAG")[1] += vcc
        Part("power", "PWR_FLAG")[1] += gnd
        for ref, net in (("U_CODEC", ws), ("U_MCU", ws)):
            u = Part("Device", "R", value="0", ref=ref)
            u[1] += net
            u[2] += gnd

        board = Board(size_mm=(10, 10))
        board.register_erc_hook(i2s_ws_pullup_erc_hook(ws))
        with pytest.raises(ERCPluginError, match="I2S WS"):
            run_erc(board)

    def test_hdmi_cec_pullup_example_passes_with_resistor(self, tmp_db, monkeypatch):
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
        cec = Net("HDMI_CEC")
        Part("power", "PWR_FLAG")[1] += vcc
        Part("power", "PWR_FLAG")[1] += gnd
        for ref, net in (("J_HDMI", cec), ("U_MCU", cec)):
            u = Part("Device", "R", value="0", ref=ref)
            u[1] += net
            u[2] += gnd
        pu = Component("R_10k_0805")
        pu["1"] += vcc
        pu["2"] += cec

        board = Board(size_mm=(10, 10))
        board.register_erc_hook(hdmi_cec_pullup_erc_hook(cec))
        run_erc(board)

    def test_hdmi_cec_pullup_example_fails_without_pullup(self, tmp_db, monkeypatch):
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
        cec = Net("HDMI_CEC")
        Part("power", "PWR_FLAG")[1] += vcc
        Part("power", "PWR_FLAG")[1] += gnd
        for ref, net in (("J_HDMI", cec), ("U_MCU", cec)):
            u = Part("Device", "R", value="0", ref=ref)
            u[1] += net
            u[2] += gnd

        board = Board(size_mm=(10, 10))
        board.register_erc_hook(hdmi_cec_pullup_erc_hook(cec))
        with pytest.raises(ERCPluginError, match="HDMI CEC"):
            run_erc(board)

    def test_stepper_dir_pullup_example_passes_with_resistor(self, tmp_db, monkeypatch):
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
        d = Net("STEP_DIR")
        Part("power", "PWR_FLAG")[1] += vcc
        Part("power", "PWR_FLAG")[1] += gnd
        for ref, net in (("U_DRV", d), ("J_CONN", d)):
            u = Part("Device", "R", value="0", ref=ref)
            u[1] += net
            u[2] += gnd
        pu = Component("R_10k_0805")
        pu["1"] += vcc
        pu["2"] += d

        board = Board(size_mm=(10, 10))
        board.register_erc_hook(stepper_dir_pullup_erc_hook(d))
        run_erc(board)

    def test_stepper_dir_pullup_example_fails_without_pullup(self, tmp_db, monkeypatch):
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
        d = Net("STEP_DIR")
        Part("power", "PWR_FLAG")[1] += vcc
        Part("power", "PWR_FLAG")[1] += gnd
        for ref, net in (("U_DRV", d), ("J_CONN", d)):
            u = Part("Device", "R", value="0", ref=ref)
            u[1] += net
            u[2] += gnd

        board = Board(size_mm=(10, 10))
        board.register_erc_hook(stepper_dir_pullup_erc_hook(d))
        with pytest.raises(ERCPluginError, match="Stepper DIR"):
            run_erc(board)

    def test_usb_otg_id_pullup_example_passes_with_resistor(self, tmp_db, monkeypatch):
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
        uid = Net("USB_OTG_ID")
        Part("power", "PWR_FLAG")[1] += vcc
        Part("power", "PWR_FLAG")[1] += gnd
        for ref, net in (("J_USB", uid), ("U_MCU", uid)):
            u = Part("Device", "R", value="0", ref=ref)
            u[1] += net
            u[2] += gnd
        pu = Component("R_10k_0805")
        pu["1"] += vcc
        pu["2"] += uid

        board = Board(size_mm=(10, 10))
        board.register_erc_hook(usb_otg_id_pullup_erc_hook(uid))
        run_erc(board)

    def test_usb_otg_id_pullup_example_fails_without_pullup(self, tmp_db, monkeypatch):
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
        uid = Net("USB_OTG_ID")
        Part("power", "PWR_FLAG")[1] += vcc
        Part("power", "PWR_FLAG")[1] += gnd
        for ref, net in (("J_USB", uid), ("U_MCU", uid)):
            u = Part("Device", "R", value="0", ref=ref)
            u[1] += net
            u[2] += gnd

        board = Board(size_mm=(10, 10))
        board.register_erc_hook(usb_otg_id_pullup_erc_hook(uid))
        with pytest.raises(ERCPluginError, match="USB OTG ID"):
            run_erc(board)

    def test_smbus_alert_pullup_example_passes_with_resistor(self, tmp_db, monkeypatch):
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
        alert = Net("SMBUS_ALERT")
        Part("power", "PWR_FLAG")[1] += vcc
        Part("power", "PWR_FLAG")[1] += gnd
        for ref, net in (("U_PMIC", alert), ("U_MCU", alert)):
            u = Part("Device", "R", value="0", ref=ref)
            u[1] += net
            u[2] += gnd
        pu = Component("R_10k_0805")
        pu["1"] += vcc
        pu["2"] += alert

        board = Board(size_mm=(10, 10))
        board.register_erc_hook(smbus_alert_pullup_erc_hook(alert))
        run_erc(board)

    def test_smbus_alert_pullup_example_fails_without_pullup(self, tmp_db, monkeypatch):
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
        alert = Net("SMBUS_ALERT")
        Part("power", "PWR_FLAG")[1] += vcc
        Part("power", "PWR_FLAG")[1] += gnd
        for ref, net in (("U_PMIC", alert), ("U_MCU", alert)):
            u = Part("Device", "R", value="0", ref=ref)
            u[1] += net
            u[2] += gnd

        board = Board(size_mm=(10, 10))
        board.register_erc_hook(smbus_alert_pullup_erc_hook(alert))
        with pytest.raises(ERCPluginError, match="SMBus ALERT"):
            run_erc(board)

    def test_sensor_interrupt_pullup_example_passes_with_resistor(self, tmp_db, monkeypatch):
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
        irq = Net("IMU_INT")
        Part("power", "PWR_FLAG")[1] += vcc
        Part("power", "PWR_FLAG")[1] += gnd
        for ref, net in (("U_IMU", irq), ("U_MCU", irq)):
            u = Part("Device", "R", value="0", ref=ref)
            u[1] += net
            u[2] += gnd
        pu = Component("R_10k_0805")
        pu["1"] += vcc
        pu["2"] += irq

        board = Board(size_mm=(10, 10))
        board.register_erc_hook(sensor_interrupt_pullup_erc_hook(irq))
        run_erc(board)

    def test_sensor_interrupt_pullup_example_fails_without_pullup(self, tmp_db, monkeypatch):
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
        irq = Net("IMU_INT")
        Part("power", "PWR_FLAG")[1] += vcc
        Part("power", "PWR_FLAG")[1] += gnd
        for ref, net in (("U_IMU", irq), ("U_MCU", irq)):
            u = Part("Device", "R", value="0", ref=ref)
            u[1] += net
            u[2] += gnd

        board = Board(size_mm=(10, 10))
        board.register_erc_hook(sensor_interrupt_pullup_erc_hook(irq))
        with pytest.raises(ERCPluginError, match="Sensor interrupt"):
            run_erc(board)

    def test_hdmi_hpd_pullup_example_passes_with_resistor(self, tmp_db, monkeypatch):
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
        hpd = Net("HDMI_HPD")
        Part("power", "PWR_FLAG")[1] += vcc
        Part("power", "PWR_FLAG")[1] += gnd
        for ref, net in (("U_CONN", hpd), ("U_MCU", hpd)):
            u = Part("Device", "R", value="0", ref=ref)
            u[1] += net
            u[2] += gnd
        pu = Component("R_10k_0805")
        pu["1"] += vcc
        pu["2"] += hpd

        board = Board(size_mm=(10, 10))
        board.register_erc_hook(hdmi_hpd_pullup_erc_hook(hpd))
        run_erc(board)

    def test_hdmi_hpd_pullup_example_fails_without_pullup(self, tmp_db, monkeypatch):
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
        hpd = Net("HDMI_HPD")
        Part("power", "PWR_FLAG")[1] += vcc
        Part("power", "PWR_FLAG")[1] += gnd
        for ref, net in (("U_CONN", hpd), ("U_MCU", hpd)):
            u = Part("Device", "R", value="0", ref=ref)
            u[1] += net
            u[2] += gnd

        board = Board(size_mm=(10, 10))
        board.register_erc_hook(hdmi_hpd_pullup_erc_hook(hpd))
        with pytest.raises(ERCPluginError, match="HDMI HPD"):
            run_erc(board)

    def test_sd_cd_pullup_example_passes_with_resistor(self, tmp_db, monkeypatch):
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
        cd = Net("SD_CD")
        Part("power", "PWR_FLAG")[1] += vcc
        Part("power", "PWR_FLAG")[1] += gnd
        for ref, net in (("J_SD", cd), ("U_MCU", cd)):
            u = Part("Device", "R", value="0", ref=ref)
            u[1] += net
            u[2] += gnd
        pu = Component("R_10k_0805")
        pu["1"] += vcc
        pu["2"] += cd

        board = Board(size_mm=(10, 10))
        board.register_erc_hook(sd_cd_pullup_erc_hook(cd))
        run_erc(board)

    def test_sd_cd_pullup_example_fails_without_pullup(self, tmp_db, monkeypatch):
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
        cd = Net("SD_CD")
        Part("power", "PWR_FLAG")[1] += vcc
        Part("power", "PWR_FLAG")[1] += gnd
        for ref, net in (("J_SD", cd), ("U_MCU", cd)):
            u = Part("Device", "R", value="0", ref=ref)
            u[1] += net
            u[2] += gnd

        board = Board(size_mm=(10, 10))
        board.register_erc_hook(sd_cd_pullup_erc_hook(cd))
        with pytest.raises(ERCPluginError, match="SD card CD"):
            run_erc(board)

    def test_jtag_tck_pullup_example_passes_with_resistor(self, tmp_db, monkeypatch):
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
        tck = Net("JTAG_TCK")
        Part("power", "PWR_FLAG")[1] += vcc
        Part("power", "PWR_FLAG")[1] += gnd
        for ref, net in (("J_HDR", tck), ("U_MCU", tck)):
            u = Part("Device", "R", value="0", ref=ref)
            u[1] += net
            u[2] += gnd
        pu = Component("R_10k_0805")
        pu["1"] += vcc
        pu["2"] += tck

        board = Board(size_mm=(10, 10))
        board.register_erc_hook(jtag_tck_pullup_erc_hook(tck))
        run_erc(board)

    def test_jtag_tck_pullup_example_fails_without_pullup(self, tmp_db, monkeypatch):
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
        tck = Net("JTAG_TCK")
        Part("power", "PWR_FLAG")[1] += vcc
        Part("power", "PWR_FLAG")[1] += gnd
        for ref, net in (("J_HDR", tck), ("U_MCU", tck)):
            u = Part("Device", "R", value="0", ref=ref)
            u[1] += net
            u[2] += gnd

        board = Board(size_mm=(10, 10))
        board.register_erc_hook(jtag_tck_pullup_erc_hook(tck))
        with pytest.raises(ERCPluginError, match="JTAG TCK"):
            run_erc(board)

    def test_can_rx_pullup_example_passes_with_resistor(self, tmp_db, monkeypatch):
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
        crx = Net("CAN_RX")
        Part("power", "PWR_FLAG")[1] += vcc
        Part("power", "PWR_FLAG")[1] += gnd
        for ref, net in (("U_CAN", crx), ("U_MCU", crx)):
            u = Part("Device", "R", value="0", ref=ref)
            u[1] += net
            u[2] += gnd
        pu = Component("R_10k_0805")
        pu["1"] += vcc
        pu["2"] += crx

        board = Board(size_mm=(10, 10))
        board.register_erc_hook(can_rx_pullup_erc_hook(crx))
        run_erc(board)

    def test_can_rx_pullup_example_fails_without_pullup(self, tmp_db, monkeypatch):
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
        crx = Net("CAN_RX")
        Part("power", "PWR_FLAG")[1] += vcc
        Part("power", "PWR_FLAG")[1] += gnd
        for ref, net in (("U_CAN", crx), ("U_MCU", crx)):
            u = Part("Device", "R", value="0", ref=ref)
            u[1] += net
            u[2] += gnd

        board = Board(size_mm=(10, 10))
        board.register_erc_hook(can_rx_pullup_erc_hook(crx))
        with pytest.raises(ERCPluginError, match="CAN RX"):
            run_erc(board)

    def test_spi_hold_n_pullup_example_passes_with_resistor(self, tmp_db, monkeypatch):
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
        hold = Net("FLASH_HOLD")
        Part("power", "PWR_FLAG")[1] += vcc
        Part("power", "PWR_FLAG")[1] += gnd
        for ref, net in (("U_FLASH", hold), ("U_MCU", hold)):
            u = Part("Device", "R", value="0", ref=ref)
            u[1] += net
            u[2] += gnd
        pu = Component("R_10k_0805")
        pu["1"] += vcc
        pu["2"] += hold

        board = Board(size_mm=(10, 10))
        board.register_erc_hook(spi_hold_n_pullup_erc_hook(hold))
        run_erc(board)

    def test_spi_hold_n_pullup_example_fails_without_pullup(self, tmp_db, monkeypatch):
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
        hold = Net("FLASH_HOLD")
        Part("power", "PWR_FLAG")[1] += vcc
        Part("power", "PWR_FLAG")[1] += gnd
        for ref, net in (("U_FLASH", hold), ("U_MCU", hold)):
            u = Part("Device", "R", value="0", ref=ref)
            u[1] += net
            u[2] += gnd

        board = Board(size_mm=(10, 10))
        board.register_erc_hook(spi_hold_n_pullup_erc_hook(hold))
        with pytest.raises(ERCPluginError, match="SPI HOLD"):
            run_erc(board)

    def test_eth_phy_int_n_pullup_example_passes_with_resistor(self, tmp_db, monkeypatch):
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
        pint = Net("PHY_INT")
        Part("power", "PWR_FLAG")[1] += vcc
        Part("power", "PWR_FLAG")[1] += gnd
        for ref, net in (("U_PHY", pint), ("U_MCU", pint)):
            u = Part("Device", "R", value="0", ref=ref)
            u[1] += net
            u[2] += gnd
        pu = Component("R_10k_0805")
        pu["1"] += vcc
        pu["2"] += pint

        board = Board(size_mm=(10, 10))
        board.register_erc_hook(eth_phy_int_n_pullup_erc_hook(pint))
        run_erc(board)

    def test_eth_phy_int_n_pullup_example_fails_without_pullup(self, tmp_db, monkeypatch):
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
        pint = Net("PHY_INT")
        Part("power", "PWR_FLAG")[1] += vcc
        Part("power", "PWR_FLAG")[1] += gnd
        for ref, net in (("U_PHY", pint), ("U_MCU", pint)):
            u = Part("Device", "R", value="0", ref=ref)
            u[1] += net
            u[2] += gnd

        board = Board(size_mm=(10, 10))
        board.register_erc_hook(eth_phy_int_n_pullup_erc_hook(pint))
        with pytest.raises(ERCPluginError, match="Ethernet PHY INT"):
            run_erc(board)

    def test_usb_vbus_sense_pullup_example_passes_with_resistor(self, tmp_db, monkeypatch):
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
        vs = Net("USB_VBUS_SENSE")
        Part("power", "PWR_FLAG")[1] += vcc
        Part("power", "PWR_FLAG")[1] += gnd
        for ref, net in (("U_USB", vs), ("U_MCU", vs)):
            u = Part("Device", "R", value="0", ref=ref)
            u[1] += net
            u[2] += gnd
        pu = Component("R_10k_0805")
        pu["1"] += vcc
        pu["2"] += vs

        board = Board(size_mm=(10, 10))
        board.register_erc_hook(usb_vbus_sense_pullup_erc_hook(vs))
        run_erc(board)

    def test_usb_vbus_sense_pullup_example_fails_without_pullup(self, tmp_db, monkeypatch):
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
        vs = Net("USB_VBUS_SENSE")
        Part("power", "PWR_FLAG")[1] += vcc
        Part("power", "PWR_FLAG")[1] += gnd
        for ref, net in (("U_USB", vs), ("U_MCU", vs)):
            u = Part("Device", "R", value="0", ref=ref)
            u[1] += net
            u[2] += gnd

        board = Board(size_mm=(10, 10))
        board.register_erc_hook(usb_vbus_sense_pullup_erc_hook(vs))
        with pytest.raises(ERCPluginError, match="USB VBUS sense"):
            run_erc(board)

    def test_pcie_wake_n_pullup_example_passes_with_resistor(self, tmp_db, monkeypatch):
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
        wake = Net("PCIe_WAKE")
        Part("power", "PWR_FLAG")[1] += vcc
        Part("power", "PWR_FLAG")[1] += gnd
        for ref, net in (("U_SLOT", wake), ("U_MCU", wake)):
            u = Part("Device", "R", value="0", ref=ref)
            u[1] += net
            u[2] += gnd
        pu = Component("R_10k_0805")
        pu["1"] += vcc
        pu["2"] += wake

        board = Board(size_mm=(10, 10))
        board.register_erc_hook(pcie_wake_n_pullup_erc_hook(wake))
        run_erc(board)

    def test_pcie_wake_n_pullup_example_fails_without_pullup(self, tmp_db, monkeypatch):
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
        wake = Net("PCIe_WAKE")
        Part("power", "PWR_FLAG")[1] += vcc
        Part("power", "PWR_FLAG")[1] += gnd
        for ref, net in (("U_SLOT", wake), ("U_MCU", wake)):
            u = Part("Device", "R", value="0", ref=ref)
            u[1] += net
            u[2] += gnd

        board = Board(size_mm=(10, 10))
        board.register_erc_hook(pcie_wake_n_pullup_erc_hook(wake))
        with pytest.raises(ERCPluginError, match="PCIe WAKE"):
            run_erc(board)

    def test_rtc_int_n_pullup_example_passes_with_resistor(self, tmp_db, monkeypatch):
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
        rint = Net("RTC_INT")
        Part("power", "PWR_FLAG")[1] += vcc
        Part("power", "PWR_FLAG")[1] += gnd
        for ref, net in (("U_RTC", rint), ("U_MCU", rint)):
            u = Part("Device", "R", value="0", ref=ref)
            u[1] += net
            u[2] += gnd
        pu = Component("R_10k_0805")
        pu["1"] += vcc
        pu["2"] += rint

        board = Board(size_mm=(10, 10))
        board.register_erc_hook(rtc_int_n_pullup_erc_hook(rint))
        run_erc(board)

    def test_rtc_int_n_pullup_example_fails_without_pullup(self, tmp_db, monkeypatch):
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
        rint = Net("RTC_INT")
        Part("power", "PWR_FLAG")[1] += vcc
        Part("power", "PWR_FLAG")[1] += gnd
        for ref, net in (("U_RTC", rint), ("U_MCU", rint)):
            u = Part("Device", "R", value="0", ref=ref)
            u[1] += net
            u[2] += gnd

        board = Board(size_mm=(10, 10))
        board.register_erc_hook(rtc_int_n_pullup_erc_hook(rint))
        with pytest.raises(ERCPluginError, match="RTC INT"):
            run_erc(board)

    def test_spi_wp_n_pullup_example_passes_with_resistor(self, tmp_db, monkeypatch):
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
        wp = Net("FLASH_WP")
        Part("power", "PWR_FLAG")[1] += vcc
        Part("power", "PWR_FLAG")[1] += gnd
        for ref, net in (("U_FLASH", wp), ("U_MCU", wp)):
            u = Part("Device", "R", value="0", ref=ref)
            u[1] += net
            u[2] += gnd
        pu = Component("R_10k_0805")
        pu["1"] += vcc
        pu["2"] += wp

        board = Board(size_mm=(10, 10))
        board.register_erc_hook(spi_wp_n_pullup_erc_hook(wp))
        run_erc(board)

    def test_spi_wp_n_pullup_example_fails_without_pullup(self, tmp_db, monkeypatch):
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
        wp = Net("FLASH_WP")
        Part("power", "PWR_FLAG")[1] += vcc
        Part("power", "PWR_FLAG")[1] += gnd
        for ref, net in (("U_FLASH", wp), ("U_MCU", wp)):
            u = Part("Device", "R", value="0", ref=ref)
            u[1] += net
            u[2] += gnd

        board = Board(size_mm=(10, 10))
        board.register_erc_hook(spi_wp_n_pullup_erc_hook(wp))
        with pytest.raises(ERCPluginError, match="SPI WP"):
            run_erc(board)

    def test_rs485_re_n_pullup_example_passes_with_resistor(self, tmp_db, monkeypatch):
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
        re_n = Net("RS485_RE")
        Part("power", "PWR_FLAG")[1] += vcc
        Part("power", "PWR_FLAG")[1] += gnd
        for ref, net in (("U_RS485", re_n), ("U_MCU", re_n)):
            u = Part("Device", "R", value="0", ref=ref)
            u[1] += net
            u[2] += gnd
        pu = Component("R_10k_0805")
        pu["1"] += vcc
        pu["2"] += re_n

        board = Board(size_mm=(10, 10))
        board.register_erc_hook(rs485_re_n_pullup_erc_hook(re_n))
        run_erc(board)

    def test_rs485_re_n_pullup_example_fails_without_pullup(self, tmp_db, monkeypatch):
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
        re_n = Net("RS485_RE")
        Part("power", "PWR_FLAG")[1] += vcc
        Part("power", "PWR_FLAG")[1] += gnd
        for ref, net in (("U_RS485", re_n), ("U_MCU", re_n)):
            u = Part("Device", "R", value="0", ref=ref)
            u[1] += net
            u[2] += gnd

        board = Board(size_mm=(10, 10))
        board.register_erc_hook(rs485_re_n_pullup_erc_hook(re_n))
        with pytest.raises(ERCPluginError, match="RS485 RE"):
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

    def test_cap_voltage_temp_derating_raises_required_voltage(self, tmp_db, monkeypatch):
        import openhac.core  # noqa: F401
        from skidl import Net, Part

        from openhac.core.base import Component

        _, dm = tmp_db
        dm.insert_component(
            {
                "generic_name": "C_temp_border",
                "kicad_symbol": "Device:C",
                "kicad_footprint": "Capacitor_SMD:C_0805_2012Metric",
                "manufacturer": "",
                "mpn": "X",
                "supplier_sku": "",
                "description": "",
                "category": "capacitors",
                "voltage_rating": 7.0,
            }
        )
        monkeypatch.setattr(Component, "db", dm)

        vcc, gnd = Net("3V3"), Net("GND")
        Part("power", "PWR_FLAG")[1] += vcc
        Part("power", "PWR_FLAG")[1] += gnd

        class M(Module):
            def __init__(self):
                super().__init__("m")
                c = self.add(Component("C_temp_border"))
                c["1"] += vcc
                c["2"] += gnd

        # 2.0 × 3.3V = 6.6V required; at 105°C vs 85°C ref and 1%/°C → ×1.2 → 7.92V required; 7V fails.
        board = Board(
            size_mm=(20, 20),
            declared_supply_voltages_v={"3V3": 3.3},
            require_cap_voltage_derating_ratio=2.0,
            ambient_operating_temp_c=105.0,
            cap_voltage_rating_reference_temp_c=85.0,
            cap_voltage_temp_derating_percent_per_c=1.0,
        )
        board.add_module(M())
        with pytest.raises(DRCViolationError, match="temp margin"):
            run_drc(board)

    def test_cap_voltage_temp_derating_passes_with_margin(self, tmp_db, monkeypatch):
        import openhac.core  # noqa: F401
        from skidl import Net, Part

        from openhac.core.base import Component

        _, dm = tmp_db
        dm.insert_component(
            {
                "generic_name": "C_temp_ok",
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
        monkeypatch.setattr(Component, "db", dm)

        vcc, gnd = Net("3V3"), Net("GND")
        Part("power", "PWR_FLAG")[1] += vcc
        Part("power", "PWR_FLAG")[1] += gnd

        class M(Module):
            def __init__(self):
                super().__init__("m")
                c = self.add(Component("C_temp_ok"))
                c["1"] += vcc
                c["2"] += gnd

        board = Board(
            size_mm=(20, 20),
            declared_supply_voltages_v={"3V3": 3.3},
            require_cap_voltage_derating_ratio=2.0,
            ambient_operating_temp_c=105.0,
            cap_voltage_rating_reference_temp_c=85.0,
            cap_voltage_temp_derating_percent_per_c=1.0,
        )
        board.add_module(M())
        run_drc(board)

    def test_ambient_without_percent_has_no_temp_margin(self, tmp_db, monkeypatch):
        import openhac.core  # noqa: F401
        from skidl import Net, Part

        from openhac.core.base import Component

        _, dm = tmp_db
        dm.insert_component(
            {
                "generic_name": "C_no_pct",
                "kicad_symbol": "Device:C",
                "kicad_footprint": "Capacitor_SMD:C_0805_2012Metric",
                "manufacturer": "",
                "mpn": "X",
                "supplier_sku": "",
                "description": "",
                "category": "capacitors",
                "voltage_rating": 7.0,
            }
        )
        monkeypatch.setattr(Component, "db", dm)

        vcc, gnd = Net("3V3"), Net("GND")
        Part("power", "PWR_FLAG")[1] += vcc
        Part("power", "PWR_FLAG")[1] += gnd

        class M(Module):
            def __init__(self):
                super().__init__("m")
                c = self.add(Component("C_no_pct"))
                c["1"] += vcc
                c["2"] += gnd

        board = Board(
            size_mm=(20, 20),
            declared_supply_voltages_v={"3V3": 3.3},
            require_cap_voltage_derating_ratio=2.0,
            ambient_operating_temp_c=105.0,
        )
        board.add_module(M())
        run_drc(board)


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


class TestLIB005JlcPerClassLimits:
    def test_per_class_limit_custom_jlc_class(self, tmp_db, monkeypatch):
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
        dm.insert_component({**base, "generic_name": "R_PREF_A", "jlc_class": "Preferred"})
        dm.insert_component({**base, "generic_name": "R_PREF_B", "jlc_class": "Preferred"})
        monkeypatch.setattr(Component, "db", dm)

        vcc, gnd = Net("3V3"), Net("GND")
        Part("power", "PWR_FLAG")[1] += vcc
        Part("power", "PWR_FLAG")[1] += gnd
        for gn in ("R_PREF_A", "R_PREF_B"):
            r = Component(gn)
            r["1"] += vcc
            r["2"] += gnd

        board = Board(size_mm=(10, 10), jlc_class_line_limits={"preferred": 1})
        with pytest.raises(DRCViolationError, match="preferred"):
            run_drc(board)

    def test_unset_class_budget(self, tmp_db, monkeypatch):
        import openhac.core  # noqa: F401
        from skidl import Net, Part

        from openhac.core.base import Component

        _, dm = tmp_db
        dm.insert_component(
            {
                "generic_name": "R_NO_JLC",
                "kicad_symbol": "Device:R",
                "kicad_footprint": "Resistor_SMD:R_0805_2012Metric",
                "manufacturer": "",
                "mpn": "X",
                "supplier_sku": "",
                "description": "",
                "jlc_class": "",
            }
        )
        monkeypatch.setattr(Component, "db", dm)

        vcc, gnd = Net("3V3"), Net("GND")
        Part("power", "PWR_FLAG")[1] += vcc
        Part("power", "PWR_FLAG")[1] += gnd
        r = Component("R_NO_JLC")
        r["1"] += vcc
        r["2"] += gnd

        board = Board(size_mm=(10, 10), jlc_class_line_limits={"unset": 0})
        with pytest.raises(DRCViolationError, match="unset/empty"):
            run_drc(board)

    def test_dict_overrides_scalar_extended_limit(self, tmp_db, monkeypatch):
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
        dm.insert_component({**base, "generic_name": "R_E1", "jlc_class": "Extended"})
        dm.insert_component({**base, "generic_name": "R_E2", "jlc_class": "Extended"})
        monkeypatch.setattr(Component, "db", dm)

        vcc, gnd = Net("3V3"), Net("GND")
        Part("power", "PWR_FLAG")[1] += vcc
        Part("power", "PWR_FLAG")[1] += gnd
        for gn in ("R_E1", "R_E2"):
            r = Component(gn)
            r["1"] += vcc
            r["2"] += gnd

        board = Board(size_mm=(10, 10), max_jlc_extended_parts=10, jlc_class_line_limits={"extended": 1})
        with pytest.raises(DRCViolationError, match="extended"):
            run_drc(board)


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

    def test_board_rejects_non_int_test_point_min_count_by_net(self):
        with pytest.raises(ValueError, match="test_point_min_count_by_net"):
            Board(
                size_mm=(20, 20),
                test_point_min_count_by_net={"3v3": "two"},
            )

    def test_drc_rejects_negative_test_point_min_count_by_net(self):
        board = Board(size_mm=(20, 20), test_point_min_count_by_net={"3v3": -1})
        board.add_module(Module("empty"))
        with pytest.raises(DRCViolationError, match="test_point_min_count_by_net"):
            run_drc(board)

    def test_drc_fails_per_net_min_tp_below_budget(self, tmp_db, monkeypatch):
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

        board = Board(
            size_mm=(20, 20),
            test_point_min_count_by_net={"3V3": 2},
        )
        board.add_module(M())
        with pytest.raises(DRCViolationError, match="requires at least 2 test point"):
            run_drc(board)

    def test_drc_passes_per_net_min_tp_when_budget_met(self, tmp_db, monkeypatch):
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
                for _ in range(2):
                    tp = self.add(Component("TP_Mech_1mm"))
                    tp["1"] += vcc

        board = Board(
            size_mm=(20, 20),
            test_point_min_count_by_net={"3V3": 2},
        )
        board.add_module(M())
        run_drc(board)
