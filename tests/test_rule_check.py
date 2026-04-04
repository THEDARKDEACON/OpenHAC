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
    DRCViolationError,
    calculate_ipc2152_trace_width,
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
