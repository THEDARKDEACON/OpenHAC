"""Tests for openhac.compiler.export_fab."""

from unittest.mock import MagicMock, patch

import pytest

from openhac.compiler.export_fab import export_fabrication_bundle
from openhac.core.base import FabExportError


def test_export_raises_when_pcb_missing(tmp_path):
    with pytest.raises(FabExportError, match="not found"):
        export_fabrication_bundle(tmp_path / "missing.kicad_pcb", tmp_path / "out")


@patch("openhac.compiler.export_fab._which_kicad_cli", return_value=None)
def test_export_raises_when_kicad_cli_missing(mock_which, tmp_path):
    pcb = tmp_path / "b.kicad_pcb"
    pcb.write_text("(kicad_pcb)\n")
    with pytest.raises(FabExportError, match="kicad-cli not found"):
        export_fabrication_bundle(pcb, tmp_path / "out")


@patch("openhac.compiler.export_fab.subprocess.run")
@patch("openhac.compiler.export_fab._which_kicad_cli", return_value="/bin/kicad-cli")
def test_export_runs_gerbers_drill_and_pos(mock_which, mock_run, tmp_path):
    pcb = tmp_path / "b.kicad_pcb"
    pcb.write_text("(kicad_pcb)\n")
    mock_run.return_value = MagicMock(returncode=0, stderr="", stdout="")

    out = tmp_path / "gerbers"
    export_fabrication_bundle(pcb, out, include_pos=True)

    assert mock_run.call_count == 4  # gerbers, drill, pos front, pos back
    cmds = [c.args[0] for c in mock_run.call_args_list]
    assert any("gerbers" in cmd for cmd in cmds)
    assert any("drill" in cmd for cmd in cmds)
    pos_cmds = [cmd for cmd in cmds if "pos" in cmd]
    assert len(pos_cmds) == 2


@patch("openhac.compiler.export_fab.subprocess.run")
@patch("openhac.compiler.export_fab._which_kicad_cli", return_value="/bin/kicad-cli")
def test_export_raises_on_gerber_failure(mock_which, mock_run, tmp_path):
    pcb = tmp_path / "b.kicad_pcb"
    pcb.write_text("(kicad_pcb)\n")
    mock_run.return_value = MagicMock(returncode=1, stderr="plot failed", stdout="")

    with pytest.raises(FabExportError, match="gerbers"):
        export_fabrication_bundle(pcb, tmp_path / "out", include_pos=False)


@patch("openhac.compiler.export_fab.subprocess.run")
@patch("openhac.compiler.export_fab._which_kicad_cli", return_value="/bin/kicad-cli")
def test_export_skips_pos_when_disabled(mock_which, mock_run, tmp_path):
    pcb = tmp_path / "b.kicad_pcb"
    pcb.write_text("(kicad_pcb)\n")
    mock_run.return_value = MagicMock(returncode=0, stderr="", stdout="")

    export_fabrication_bundle(pcb, tmp_path / "out", include_pos=False)
    assert mock_run.call_count == 2


@patch("openhac.compiler.export_fab.subprocess.run")
@patch("openhac.compiler.export_fab._which_kicad_cli", return_value="/bin/kicad-cli")
def test_export_ipc2581_when_requested(mock_which, mock_run, tmp_path):
    pcb = tmp_path / "b.kicad_pcb"
    pcb.write_text("(kicad_pcb)\n")
    mock_run.return_value = MagicMock(returncode=0, stderr="", stdout="")

    export_fabrication_bundle(pcb, tmp_path / "out", include_pos=True, include_ipc2581=True)

    assert mock_run.call_count == 5
    cmds = [c.args[0] for c in mock_run.call_args_list]
    assert any("ipc2581" in cmd for cmd in cmds)
