from __future__ import annotations

import json
from pathlib import Path

from skidl import Net

from openhac.compiler.sipi_handoff import write_sipi_handoff_json
from openhac.core.board import Board


def test_write_sipi_handoff_json_writes_when_intent_present(tmp_path: Path) -> None:
    b = Board((10, 10), board_class="highspeed")
    # Create one diff pair intent.
    b.route_differential_pair(Net("DP"), Net("DN"), target_impedance_ohms=90)
    out = write_sipi_handoff_json(tmp_path, "p", b)
    assert out is not None and out.is_file()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["schema"] == "openhac.sipi_handoff.v1"
    assert data["board_class"] == "highspeed"
    assert data["diff_pair_intent"]

