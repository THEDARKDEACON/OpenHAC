"""Stress compile: multi-module board, multi-sheet schematic, no implicit pins."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_EXAMPLE = _REPO_ROOT / "examples" / "stress_satcom_node_documented.py"
_SEED = _REPO_ROOT / "seeds" / "stress_satcom_seed.json"


@pytest.mark.skipif(not _EXAMPLE.is_file(), reason="stress example missing")
def test_stress_satcom_docs_compile_offline(tmp_path: Path) -> None:
    db_path = tmp_path / "stress_satcom.db"
    env = {
        **os.environ,
        "PYTHONPATH": str(_REPO_ROOT),
        "OPENHAC_DB_PATH": str(db_path),
        "OPENHAC_SKIP_LAYOUT": "1",
        "OPENHAC_NO_NETWORK": "1",
        # Force multi-sheet so this stays stable even if default threshold changes.
        "OPENHAC_SCHEMATIC_MULTI_SHEET": "1",
    }
    r = subprocess.run(
        [
            sys.executable,
            "-m",
            "openhac.cli",
            "compile",
            str(_EXAMPLE),
            "--name",
            "stress_satcom_test",
            "-o",
            str(tmp_path),
            "--no-route",
            "--schematic-strict",
            "--pre-seed-file",
            str(_SEED),
        ],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=240,
        env=env,
    )
    assert r.returncode == 0, (r.stdout, r.stderr)

    root = tmp_path / "stress_satcom_test.kicad_sch"
    assert root.is_file()
    # Multi-sheet subsheets should be present.
    for mod in ("PowerTree", "HostMCU_A", "HostMCU_B", "CANPhy_A", "CANPhy_B", "StatusLED_A", "StatusLED_B"):
        assert (tmp_path / f"stress_satcom_test.{mod}.kicad_sch").is_file()

    # No implicit-pin warnings should appear in strict mode.
    out = (r.stdout + r.stderr).lower()
    assert "implicit pin" not in out

