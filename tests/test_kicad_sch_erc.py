"""SCH-003: optional KiCad schematic ERC via kicad-cli."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from openhac.compiler.kicad_sch_erc import run_kicad_schematic_erc
from openhac.core.base import KiCadCliNotFoundError, KiCadSchErcError


def test_raises_when_kicad_cli_missing(tmp_path):
    sch = tmp_path / "x.kicad_sch"
    sch.write_text('(kicad_sch (version 20231120) (generator t) (uuid "u") (paper "A4"))\n', encoding="utf-8")
    with patch("openhac.compiler.kicad_sch_erc.shutil.which", return_value=None):
        with pytest.raises(KiCadCliNotFoundError, match="kicad-cli"):
            run_kicad_schematic_erc(sch)


def test_raises_when_schematic_missing(tmp_path):
    with patch("openhac.compiler.kicad_sch_erc.shutil.which", return_value="/bin/kicad-cli"):
        with pytest.raises(KiCadSchErcError, match="not found"):
            run_kicad_schematic_erc(tmp_path / "missing.kicad_sch")


def test_nonstrict_does_not_raise_on_nonzero_exit(tmp_path):
    sch = tmp_path / "x.kicad_sch"
    sch.write_text('(kicad_sch (version 20231120) (generator t) (uuid "u") (paper "A4"))\n', encoding="utf-8")
    proc = MagicMock()
    proc.returncode = 3
    proc.stderr = "ERC errors"
    proc.stdout = ""
    with patch("openhac.compiler.kicad_sch_erc.shutil.which", return_value="/bin/kicad-cli"):
        with patch("openhac.compiler.kicad_sch_erc.subprocess.run", return_value=proc):
            run_kicad_schematic_erc(sch, strict=False)


def test_strict_false_omits_exit_code_violations_flag(tmp_path):
    sch = tmp_path / "x.kicad_sch"
    sch.write_text('(kicad_sch (version 20231120) (generator t) (uuid "u") (paper "A4"))\n', encoding="utf-8")
    rep = tmp_path / "out.json"
    proc = MagicMock()
    proc.returncode = 0
    proc.stderr = ""
    proc.stdout = ""
    with patch("openhac.compiler.kicad_sch_erc.shutil.which", return_value="/bin/kicad-cli"):
        with patch("openhac.compiler.kicad_sch_erc.subprocess.run", return_value=proc) as mock_run:
            run_kicad_schematic_erc(sch, output_report=rep, report_format="json", strict=False)
    cmd = mock_run.call_args[0][0]
    assert "--exit-code-violations" not in cmd


def test_raises_on_nonzero_exit(tmp_path):
    sch = tmp_path / "x.kicad_sch"
    sch.write_text('(kicad_sch (version 20231120) (generator t) (uuid "u") (paper "A4"))\n', encoding="utf-8")
    proc = MagicMock()
    proc.returncode = 3
    proc.stderr = "ERC errors"
    proc.stdout = ""
    with patch("openhac.compiler.kicad_sch_erc.shutil.which", return_value="/bin/kicad-cli"):
        with patch("openhac.compiler.kicad_sch_erc.subprocess.run", return_value=proc):
            with pytest.raises(KiCadSchErcError, match="ERC"):
                run_kicad_schematic_erc(sch)


def test_invokes_json_format_when_requested(tmp_path):
    sch = tmp_path / "x.kicad_sch"
    sch.write_text('(kicad_sch (version 20231120) (generator t) (uuid "u") (paper "A4"))\n', encoding="utf-8")
    rep = tmp_path / "out.json"
    proc = MagicMock()
    proc.returncode = 0
    proc.stderr = ""
    proc.stdout = ""
    with patch("openhac.compiler.kicad_sch_erc.shutil.which", return_value="/bin/kicad-cli"):
        with patch("openhac.compiler.kicad_sch_erc.subprocess.run", return_value=proc) as mock_run:
            run_kicad_schematic_erc(sch, output_report=rep, report_format="json")
    cmd = mock_run.call_args[0][0]
    assert "--format" in cmd
    assert cmd[cmd.index("--format") + 1] == "json"


def test_success_returns_report_path(tmp_path):
    sch = tmp_path / "x.kicad_sch"
    sch.write_text('(kicad_sch (version 20231120) (generator t) (uuid "u") (paper "A4"))\n', encoding="utf-8")
    rep = tmp_path / "out.txt"
    proc = MagicMock()
    proc.returncode = 0
    proc.stderr = ""
    proc.stdout = ""
    with patch("openhac.compiler.kicad_sch_erc.shutil.which", return_value="/bin/kicad-cli"):
        with patch("openhac.compiler.kicad_sch_erc.subprocess.run", return_value=proc):
            out = run_kicad_schematic_erc(sch, output_report=rep)
    assert out == rep


def test_board_compile_kicad_erc_requires_export():
    from openhac.core.board import Board

    b = Board(size_mm=(10, 10))
    with pytest.raises(ValueError, match="export_schematic"):
        b.compile(
            project_name="x",
            generate_bom=False,
            auto_route=False,
            export_schematic=False,
            kicad_sch_erc=True,
        )
