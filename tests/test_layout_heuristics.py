from __future__ import annotations

from openhac.compiler.layout_heuristics import apply_layout_heuristics
from openhac.core.board import Board
from openhac.core.base import Module


def test_layout_heuristics_adds_edge_constraint_for_connectorish_module() -> None:
    b = Board((60, 40))
    m = Module("USB_CONN")
    b.add_module(m)
    before = len(b.constraints)
    summary = apply_layout_heuristics(b)
    assert summary["applied"] >= 1
    assert len(b.constraints) >= before + 1
    assert any(c.get("type") == "edge" for c in b.constraints)

