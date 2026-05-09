from __future__ import annotations

import math

from openhac.compiler.autosize_board import _pack_extents, maybe_autosize_board
from openhac.core.base import Module
from openhac.core.board import Board


def test_pack_extents_basic_gap_zero() -> None:
    # 2 columns: [ (10x5), (3x7) ] in first row, then (4x2) on second row.
    w, h = _pack_extents([(10, 5), (3, 7), (4, 2)], cols=2, gap_mm=0.0)
    assert w == 13.0
    assert h == 9.0


def test_pack_extents_with_gap() -> None:
    # Same case but with 1mm gap between items and rows.
    w, h = _pack_extents([(10, 5), (3, 7), (4, 2)], cols=2, gap_mm=1.0)
    # Row1 width: 10 + 1 + 3 = 14. Height: max(5,7)=7
    # Row2 starts at y=8 (7+gap), ext height: 8 + 2 = 10
    assert w == 14.0
    assert h == 10.0


def test_autosize_fallback_module_area(monkeypatch) -> None:
    # Force pack path off so this test is deterministic in headless CI.
    monkeypatch.setenv("OPENHAC_PLACEMENT_USE_FP_BBOX", "0")
    monkeypatch.setenv("OPENHAC_AUTO_BOARD_MARGIN_FACTOR", "1.0")
    monkeypatch.setenv("OPENHAC_AUTO_BOARD_ASPECT_RATIO", "1.0")
    monkeypatch.setenv("OPENHAC_AUTO_BOARD_UTILIZATION", "1.0")
    monkeypatch.setenv("OPENHAC_AUTO_BOARD_MIN_EDGE_MARGIN_MM", "0.0")

    b = Board(size_mm=None)
    m1 = Module("A")
    m1.width = 10.0
    m1.height = 20.0
    m2 = Module("B")
    m2.width = 5.0
    m2.height = 5.0
    b.modules = [m1, m2]
    b.all_modules = [m1, m2]

    assert maybe_autosize_board(b) is True
    assert b.size_mm is not None
    # total_area = 200 + 25 = 225 mm²; util=1; ar=1 => sqrt(225)=15, then clamped to max module height (20).
    w_mm, h_mm = b.size_mm
    assert h_mm == 20.0
    assert w_mm >= math.ceil(15.0)

