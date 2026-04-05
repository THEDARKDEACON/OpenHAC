"""Architecture: no global Component stomp from Board; compile context (contextvars)."""

from __future__ import annotations

from openhac.core.base import Component
from openhac.core.board import Board


def test_sequential_board_constructors_do_not_mutate_component_class_flags():
    prev_k = Component.require_kicad_symbols
    prev_j = Component.strict_jit_lookups
    _ = Board(size_mm=(10, 10), strict_kicad=True, strict_jit_lookups=True)
    _ = Board(size_mm=(10, 10), strict_kicad=False, strict_jit_lookups=False)
    assert Component.require_kicad_symbols is prev_k
    assert Component.strict_jit_lookups is prev_j
