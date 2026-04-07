"""SW-002 / STR-002: module entrypoint exists (`python -m openhac`)."""

from __future__ import annotations

import subprocess
import sys


def test_python_m_openhac_help_runs():
    proc = subprocess.run(
        [sys.executable, "-m", "openhac", "--help"],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert proc.returncode == 0
    assert "Available commands" in (proc.stdout + proc.stderr)

