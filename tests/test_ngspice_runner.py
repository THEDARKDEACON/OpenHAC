from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from openhac.compiler.ngspice_runner import run_ngspice_headless


@pytest.mark.skipif(shutil.which("ngspice") is None, reason="ngspice not installed")
def test_run_ngspice_headless_smoke(tmp_path: Path) -> None:
    cir = tmp_path / "t.cir"
    cir.write_text(
        "\n".join(
            [
                "* openhac ngspice smoke",
                "V1 in 0 DC 1",
                "R1 in out 1k",
                "C1 out 0 1u",
                ".op",
                ".end",
                "",
            ]
        ),
        encoding="utf-8",
    )
    logp = Path(run_ngspice_headless(cir, log_path=tmp_path / "ng.log", timeout_s=20))
    assert logp.is_file()
    assert logp.read_text(encoding="utf-8").strip()

