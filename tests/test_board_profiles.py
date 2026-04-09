from __future__ import annotations

from openhac.compiler.board_profiles import resolve_board_profile
from openhac.core.board import Board


def test_resolve_board_profile_defaults() -> None:
    p = resolve_board_profile("highspeed")
    assert p.name == "highspeed"
    assert "min_track_count" in p.default_quality_gates


def test_board_merges_profile_quality_gates() -> None:
    b = Board((10, 10), board_class="highspeed")
    assert int(b.quality_gates.get("min_track_count", 0) or 0) >= 1
    # Explicit override wins
    b2 = Board((10, 10), board_class="highspeed", quality_gates={"min_track_count": 123})
    assert b2.quality_gates["min_track_count"] == 123

