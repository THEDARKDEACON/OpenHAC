"""Production validation stages (logic-level; KiCad optional)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_SCRIPT = _REPO / "scripts" / "ci_validate_production.py"
_GOLDEN = _REPO / "tests" / "fixtures" / "fab_golden_board.py"


def _env(**extra: str) -> dict[str, str]:
    env = os.environ.copy()
    env["OPENHAC_NO_NETWORK"] = "1"
    env["PYTHONPATH"] = str(_REPO) + os.pathsep + env.get("PYTHONPATH", "")
    env.update(extra)
    return env


@pytest.mark.skipif(not _SCRIPT.is_file(), reason="production validator missing")
def test_production_validator_logic_only():
    r = subprocess.run(
        [sys.executable, str(_SCRIPT), "--logic-only"],
        cwd=str(_REPO),
        env=_env(),
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, (r.stdout or "") + "\n" + (r.stderr or "")


def test_golden_production_compile_skip_layout(tmp_path):
    """V1/V2: --production compile runs native ERC+DRC without pcbnew."""
    out = tmp_path / "out"
    out.mkdir()
    r = subprocess.run(
        [
            sys.executable,
            "-m",
            "openhac.cli",
            "compile",
            str(_GOLDEN),
            "--name",
            "prod_logic",
            "--production",
            "--compile-goal",
            "fabrication",
            "--strict-footprint-pads",
            "--require-verified-parts",
            "--no-schematic",
            "--skip-layout",
            "-o",
            str(out),
        ],
        cwd=str(_REPO),
        env=_env(),
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, (r.stdout or "") + "\n" + (r.stderr or "")
    assert (out / "prod_logic.openhac-manifest.json").is_file()
    assert (out / "prod_logic.net").is_file()


def test_production_validation_doc_exists():
    doc = _REPO / "docs" / "internal" / "PRODUCTION_VALIDATION.md"
    assert doc.is_file()
    text = doc.read_text(encoding="utf-8")
    assert "V6 Route + PCB DRC" in text
    assert "software fabrication readiness" in text.lower() or "software" in text.lower()
