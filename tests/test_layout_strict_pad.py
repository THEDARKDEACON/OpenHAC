"""PCB-002: strict footprint pin↔pad parity before pcbnew."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import openhac.core  # noqa: F401
from openhac.compiler.layout_gen import assert_footprint_pin_pad_or_raise
from openhac.core.base import LayoutGenerationError
from openhac.core.board import Board


def test_strict_pad_check_passes_when_no_warnings():
    b = Board(size_mm=(10, 10), strict_footprint_pin_pad_match=True)
    with patch("openhac.circuit.get_default_circuit", return_value=MagicMock()):
        with patch(
            "openhac.compiler.pcb_placement.pin_pad_coverage_warnings",
            return_value=[],
        ):
            assert_footprint_pin_pad_or_raise(b)


def test_strict_pad_check_raises_on_warnings():
    b = Board(size_mm=(10, 10), strict_footprint_pin_pad_match=True)
    with patch("openhac.circuit.get_default_circuit", return_value=MagicMock()):
        with patch(
            "openhac.compiler.pcb_placement.pin_pad_coverage_warnings",
            return_value=["Part R1: footprint 'L:F' has no pad '2'"],
        ):
            with pytest.raises(LayoutGenerationError, match="PCB-002"):
                assert_footprint_pin_pad_or_raise(b)


def test_strict_pad_skipped_when_board_flag_false():
    b = Board(size_mm=(10, 10), strict_footprint_pin_pad_match=False)
    with patch("openhac.circuit.get_default_circuit", return_value=MagicMock()):
        with patch(
            "openhac.compiler.pcb_placement.pin_pad_coverage_warnings",
            return_value=["should be ignored"],
        ):
            assert_footprint_pin_pad_or_raise(b)
