from __future__ import annotations

import pytest

from openhac.compiler.compile_pipeline import CompileState, run_compile_loop
from openhac.compiler.rule_check import DRCViolationError, run_drc
from openhac.core.board import Board
from openhac.core.base import Module


def test_run_compile_loop_retries_when_max_attempts_gt_1(tmp_path, monkeypatch) -> None:
    b = Board((10, 10), quality_gates={"max_attempts": 2})
    state = CompileState(
        board=b,
        project_name="t",
        generate_bom=False,
        auto_route=False,
        export_schematic=False,
        allow_risky_part_lookups=False,
        kicad_sch_erc=False,
        kicad_sch_erc_format="report",
        source_script_path=None,
        output_dir=str(tmp_path),
        release_zip_path=None,
    )

    calls = {"n": 0}

    def phase_fail_once(_state):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("fail once")

    run_compile_loop(state, generate_phases=(phase_fail_once,), max_attempts=2)
    assert calls["n"] == 2


def test_run_compile_loop_raises_after_exhausting_attempts(tmp_path) -> None:
    b = Board((10, 10), quality_gates={"max_attempts": 2})
    state = CompileState(
        board=b,
        project_name="t",
        generate_bom=False,
        auto_route=False,
        export_schematic=False,
        allow_risky_part_lookups=False,
        kicad_sch_erc=False,
        kicad_sch_erc_format="report",
        source_script_path=None,
        output_dir=str(tmp_path),
        release_zip_path=None,
    )

    def phase_always_fail(_state):
        raise RuntimeError("nope")

    with pytest.raises(RuntimeError):
        run_compile_loop(state, generate_phases=(phase_always_fail,), max_attempts=2)


def test_retry_clears_leftover_placement_before_prelayout_drc(tmp_path) -> None:
    """Attempt-1 layout coords must not DRC-fail attempt-2 before autoroute/DSN."""
    b = Board(size_mm=None, compile_goal="fabrication", quality_gates={"max_attempts": 2})
    mod = Module("UsbJack")
    mod.width = 30.0
    mod.height = 10.0
    b.add_module(mod)
    state = CompileState(
        board=b,
        project_name="t",
        generate_bom=False,
        auto_route=False,
        export_schematic=False,
        allow_risky_part_lookups=False,
        kicad_sch_erc=False,
        kicad_sch_erc_format="report",
        source_script_path=None,
        output_dir=str(tmp_path),
        release_zip_path=None,
    )
    assert state.started_with_autosize is True

    calls = {"n": 0}

    def phase(_state):
        calls["n"] += 1
        if calls["n"] == 1:
            mod.placed_x = 159.454
            mod.placed_y = 10.0
            b.size_mm = (187.0, 243.0)
            b._size_mm_unspecified = False
            raise RuntimeError("layout leftover")
        run_drc(_state.board)

    run_compile_loop(state, generate_phases=(phase,), max_attempts=2)
    assert calls["n"] == 2
    assert mod.placed_x is None
    assert b._size_mm_unspecified is True

