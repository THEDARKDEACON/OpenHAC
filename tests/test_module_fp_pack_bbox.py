"""pcbnew simulated pack → module bbox (two-stage placer, stage 1)."""

from __future__ import annotations

from openhac.core.board import Board
from openhac.core.base import Module
from openhac.compiler.pcb_placement import apply_pcbnew_pack_to_module_bboxes


def test_apply_pcbnew_pack_disabled_returns_zero(monkeypatch) -> None:
    monkeypatch.setenv("OPENHAC_MODULE_BBOX_FROM_FP_PACK", "0")
    b = Board(size_mm=(50, 50))
    m = Module("M")
    m.width = m.height = 10.0
    b.modules = [m]
    b.all_modules = [m]
    assert apply_pcbnew_pack_to_module_bboxes(b) == 0
