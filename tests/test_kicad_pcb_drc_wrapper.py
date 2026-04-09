from __future__ import annotations

from pathlib import Path

import pytest

from openhac.compiler.kicad_pcb_drc import KiCadPcbDrcError, run_kicad_pcb_drc


def test_kicad_pcb_drc_raises_when_pcb_missing(tmp_path: Path, monkeypatch) -> None:
    # Force kicad-cli present by patching shutil.which in module scope.
    import openhac.compiler.kicad_pcb_drc as m

    monkeypatch.setattr(m.shutil, "which", lambda _x: "/usr/bin/kicad-cli")
    missing = tmp_path / "nope.kicad_pcb"
    with pytest.raises(KiCadPcbDrcError):
        run_kicad_pcb_drc(missing)

