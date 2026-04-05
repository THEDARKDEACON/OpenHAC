"""SW-004: scripts/check_release_strings.py exits 0 on clean tree."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_check_release_strings_script_exits_zero():
    root = Path(__file__).resolve().parents[1]
    script = root / "scripts" / "check_release_strings.py"
    r = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr
