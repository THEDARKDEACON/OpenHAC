"""SW-004: installed package version matches static pyproject version."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_verify_openhac_version_script_exits_zero():
    root = Path(__file__).resolve().parents[1]
    script = root / "scripts" / "verify_openhac_version.py"
    r = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr
