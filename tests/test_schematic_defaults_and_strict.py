from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]


def test_schematic_default_multisheet_threshold(monkeypatch, tmp_path: Path) -> None:
    """When large enough, multi-sheet should auto-enable without explicit env."""
    # Force threshold low so the test stays small.
    monkeypatch.setenv("OPENHAC_SCHEMATIC_MULTI_SHEET_MIN_PARTS", "2")
    monkeypatch.delenv("OPENHAC_SCHEMATIC_MULTI_SHEET", raising=False)
    monkeypatch.delenv("OPENHAC_SCHEMATIC_SINGLE_SHEET", raising=False)

    script = tmp_path / "two_modules.py"
    script.write_text(
        """
import openhac.core  # noqa: F401
from skidl import Net, Part
from openhac.core import Board
from openhac.core.base import Module

n = Net("N")
g = Net("G")

class A(Module):
    def __init__(self):
        super().__init__("A")
        r = Part("Device", "R", value="10k", footprint="Resistor_SMD:R_0603_1608Metric")
        r.fields["OpenHaC_Module"] = "A"
        self._n = n
        self._n += r[1]
        self._g = g
        self._g += r[2]

class B(Module):
    def __init__(self):
        super().__init__("B")
        r = Part("Device", "R", value="10k", footprint="Resistor_SMD:R_0603_1608Metric")
        r.fields["OpenHaC_Module"] = "B"
        self._n = n
        self._n += r[1]
        self._g = g
        self._g += r[2]

board = Board((20, 20))
board.add_module(A())
board.add_module(B())
""".lstrip(),
        encoding="utf-8",
    )

    env = {**os.environ, "PYTHONPATH": str(_REPO_ROOT)}
    r = subprocess.run(
        [
            sys.executable,
            "-m",
            "openhac.cli",
            "compile",
            str(script),
            "--name",
            "t",
            "-o",
            str(tmp_path),
            "--no-route",
            "--skip-layout",
        ],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=180,
        env=env,
    )
    assert r.returncode == 0, (r.stdout, r.stderr)
    root = tmp_path / "t.kicad_sch"
    assert root.is_file()
    # Auto multi-sheet => subsheets exist.
    assert (tmp_path / "t.A.kicad_sch").is_file()
    assert (tmp_path / "t.B.kicad_sch").is_file()


def test_schematic_strict_blocks_implicit_pins(tmp_path: Path) -> None:
    """--schematic-strict should block implicit pins when a component lacks pinout."""
    script = tmp_path / "implicit.py"
    script.write_text(
        """
from openhac.core.net import Net
from openhac.core import Board
from openhac.core.base import Module, Component

class M(Module):
    def __init__(self):
        super().__init__("M")
        c = self.add(Component("NO_PINOUT_PART"))
        c["VCC"] += Net("VCC")  # would create an implicit pin without strict mode

board = Board((20, 20))
board.add_module(M())
""".lstrip(),
        encoding="utf-8",
    )

    env = {
        **os.environ,
        "PYTHONPATH": str(_REPO_ROOT),
        "OPENHAC_SKIP_LAYOUT": "1",
        # Prevent any online attempt from masking the missing pinout row.
        "OPENHAC_NO_NETWORK": "1",
    }
    r = subprocess.run(
        [
            sys.executable,
            "-m",
            "openhac.cli",
            "compile",
            str(script),
            "--name",
            "t_strict",
            "-o",
            str(tmp_path),
            "--no-route",
            "--schematic-strict",
        ],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=180,
        env=env,
    )
    assert r.returncode != 0
    out = (r.stdout + r.stderr).lower()
    assert "implicit pin" not in out  # should not fall back to implicit creation
