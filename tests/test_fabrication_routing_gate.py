from __future__ import annotations

from pathlib import Path

import pytest

from openhac.compiler.compile_pipeline import CompileState, phase_autoroute
from openhac.core.base import AutorouterFailedError, FreeRoutingNotFoundError
from openhac.core.board import Board


def test_fabrication_mode_raises_if_freerouting_missing(monkeypatch, tmp_path: Path) -> None:
    b = Board((10, 10), compile_goal="fabrication")
    state = CompileState(
        board=b,
        project_name="t",
        generate_bom=False,
        auto_route=True,
        export_schematic=False,
        allow_risky_part_lookups=False,
        kicad_sch_erc=False,
        kicad_sch_erc_format="report",
        source_script_path=None,
        output_dir=str(tmp_path),
        release_zip_path=None,
    )
    Path(state.pcb_path).write_text("dummy")

    import openhac.compiler.autoroute_cli as ar

    def _no_freerouting(_pcb_path: str) -> None:
        raise FreeRoutingNotFoundError("no jar")

    monkeypatch.setattr(ar, "run_freerouting", _no_freerouting)
    monkeypatch.setattr(ar, "fallback_route_with_pcbnew", lambda *_a, **_k: None)

    with pytest.raises(AutorouterFailedError):
        phase_autoroute(state)


def test_handoff_mode_falls_back_if_freerouting_missing(monkeypatch, tmp_path: Path) -> None:
    b = Board((10, 10), compile_goal="handoff")
    state = CompileState(
        board=b,
        project_name="t",
        generate_bom=False,
        auto_route=True,
        export_schematic=False,
        allow_risky_part_lookups=False,
        kicad_sch_erc=False,
        kicad_sch_erc_format="report",
        source_script_path=None,
        output_dir=str(tmp_path),
        release_zip_path=None,
    )
    Path(state.pcb_path).write_text("dummy")

    import openhac.compiler.autoroute_cli as ar

    def _no_freerouting(_pcb_path: str) -> None:
        raise FreeRoutingNotFoundError("no jar")

    called = {"fallback": 0}

    def _fallback(*_a, **_k) -> None:
        called["fallback"] += 1

    monkeypatch.setattr(ar, "run_freerouting", _no_freerouting)
    monkeypatch.setattr(ar, "fallback_route_with_pcbnew", _fallback)

    phase_autoroute(state)
    assert called["fallback"] == 1

