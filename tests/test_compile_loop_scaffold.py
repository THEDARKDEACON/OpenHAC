from __future__ import annotations

import pytest

from openhac.compiler.compile_pipeline import CompileState, run_compile_loop
from openhac.core.board import Board


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

