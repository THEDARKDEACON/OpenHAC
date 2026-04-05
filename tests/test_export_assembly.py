"""MFG-002: assembly (pos CSV) export."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from openhac.compiler.export_fab import export_assembly_csv
from openhac.core.base import FabExportError


def test_export_assembly_calls_kicad_pos(tmp_path):
    pcb = tmp_path / "b.kicad_pcb"
    pcb.write_text("(kicad_pcb)\n", encoding="utf-8")
    out = tmp_path / "posout"
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        m = MagicMock()
        m.returncode = 0
        m.stderr = ""
        m.stdout = ""
        return m

    with patch("openhac.compiler.export_fab.shutil.which", return_value="/bin/kicad-cli"):
        with patch("openhac.compiler.export_fab.subprocess.run", side_effect=fake_run):
            export_assembly_csv(pcb, out)

    assert len(calls) == 2
    assert all("pos" in c for c in calls)
    assert any("front" in c for c in calls)
    assert any("back" in c for c in calls)


def test_export_assembly_missing_pcb_raises(tmp_path):
    with patch("openhac.compiler.export_fab.shutil.which", return_value="/x"):
        with pytest.raises(FabExportError, match="not found"):
            export_assembly_csv(tmp_path / "missing.kicad_pcb", tmp_path / "o")
