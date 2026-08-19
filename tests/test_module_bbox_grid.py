"""Module bbox heuristics: grid packing vs legacy area (PCB placement density)."""

from __future__ import annotations

import pytest

from openhac.core.base import Module


class _FP:
    __slots__ = ("footprint",)

    def __init__(self, footprint: str) -> None:
        self.footprint = footprint


class _Leaf:
    __slots__ = ("part",)

    def __init__(self, footprint: str) -> None:
        self.part = _FP(footprint)


def test_recalculate_bbox_grid_exceeds_legacy_for_many_passives(monkeypatch) -> None:
    monkeypatch.setenv("OPENHAC_MODULE_PACK_INFLATE", "1.0")
    monkeypatch.setenv("OPENHAC_PLACEMENT_FP_GAP_MM", "1.0")
    m = Module("pack")
    m.width = 0.0
    m.height = 0.0
    # 16× 0603 → 4×4 grid: W = 4*1.6 + 3*1 = 9.4, H = 4*0.8 + 3*1 = 6.2 (legacy area box is smaller).
    for _ in range(16):
        m.components.append(_Leaf("Resistor_SMD:R_0603_1608Metric"))
    m.recalculate_bbox_from_components()
    assert m.width >= 9.4 - 1e-6
    assert m.height >= 6.2 - 1e-6


def test_z3_module_clearance_requires_separation(monkeypatch) -> None:
    pytest.importorskip("z3")
    monkeypatch.setenv("OPENHAC_PLACEMENT_ENGINE", "z3")
    from openhac.core.board import Board
    from openhac.compiler.layout_gen import solve_placement

    b = Board(size_mm=(40, 20))
    a, c = Module("left"), Module("right")
    a.width = a.height = 10
    c.width = c.height = 10
    b.modules = [a, c]
    b.all_modules = [a, c]
    b.constraints = []
    b.module_clearance_mm = 3.0
    assert solve_placement(b)
    # 10 + 3 + 10 = 23 mm horizontal span — positions must not share the same x band.
    assert abs(a.placed_x - c.placed_x) >= 13 or abs(a.placed_y - c.placed_y) >= 13


def test_z3_compacts_modules_instead_of_filling_outline(monkeypatch) -> None:
    pytest.importorskip("z3")
    from openhac.core.board import Board
    from openhac.compiler.layout_gen import solve_placement

    monkeypatch.setenv("OPENHAC_Z3_COMPACT", "1")
    monkeypatch.setenv("OPENHAC_PLACEMENT_ENGINE", "z3")
    monkeypatch.setenv("OPENHAC_AUTO_BOARD_MIN_EDGE_MARGIN_MM", "2")
    b = Board(size_mm=(200, 200))
    a, c = Module("A"), Module("B")
    a.width = a.height = 10
    c.width = c.height = 10
    b.modules = [a, c]
    b.all_modules = [a, c]
    b.constraints = []
    b.module_clearance_mm = 2.0
    assert solve_placement(b)
    max_r = max(a.placed_x + a.width, c.placed_x + c.width)
    max_b = max(a.placed_y + a.height, c.placed_y + c.height)
    assert max_r <= 30
    assert max_b <= 30
    assert b.size_mm[0] <= 40
    assert b.size_mm[1] <= 40
