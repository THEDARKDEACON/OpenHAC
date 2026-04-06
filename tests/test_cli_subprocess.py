"""SW-006: subprocess invocation of the CLI (real interpreter, no in-process mocks)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]

_SUBPROCESS_BOARD = '''
import openhac.core  # noqa: F401
from skidl import Net, Part
from openhac.core import Board
from openhac.core.base import Module

vcc, gnd = Net("3V3"), Net("GND")
Part("power", "PWR_FLAG")[1] += vcc
Part("power", "PWR_FLAG")[1] += gnd


class Node(Module):
    def __init__(self, name: str):
        super().__init__(name)
        r = Part("Device", "R", value="10k", footprint="Resistor_SMD:R_0805_2012Metric")
        r[1] += vcc
        r[2] += gnd
        self.declare_interface("power", vcc, gnd)


a, b = Node("A"), Node("B")
board = Board(size_mm=(48.0, 36.0))
board.add_module(a)
board.add_module(b)
board.connect(a.expose_interface("power"), b.expose_interface("power"))
'''


@pytest.mark.parametrize(
    "args",
    [
        ["--help"],
        ["compile", "--help"],
        ["export", "--help"],
    ],
)
def test_openhac_cli_subprocess_help(args):
    env = {**os.environ, "PYTHONPATH": str(_REPO_ROOT)}
    r = subprocess.run(
        [sys.executable, "-m", "openhac.cli", *args],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )
    assert r.returncode == 0, r.stderr
    out = (r.stdout + r.stderr).lower()
    assert "openhac" in out or "compile" in out or "export" in out


def test_openhac_cli_subprocess_compile_logic_only(tmp_path):
    """E2E: fresh interpreter → netlist + BOM + manifest, exit 0 (no KiCad pcbnew)."""
    script = tmp_path / "subprocess_board.py"
    script.write_text(_SUBPROCESS_BOARD, encoding="utf-8")
    env = {
        **os.environ,
        "PYTHONPATH": str(_REPO_ROOT),
        "OPENHAC_SKIP_LAYOUT": "1",
    }
    r = subprocess.run(
        [
            sys.executable,
            "-m",
            "openhac.cli",
            "compile",
            str(script),
            "--name",
            "sub_e2e",
            "--no-route",
            "--no-schematic",
        ],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert (tmp_path / "sub_e2e.net").is_file()
    assert (tmp_path / "sub_e2e.csv").is_file()
    mf = tmp_path / "sub_e2e.openhac-manifest.json"
    assert mf.is_file()
    data = json.loads(mf.read_text(encoding="utf-8"))
    assert data["project_name"] == "sub_e2e"
    paths = {o["path"] for o in data["outputs"]}
    assert "sub_e2e.net" in paths
    assert "sub_e2e.csv" in paths


def test_openhac_cli_subprocess_simulate_spice_preset(tmp_path):
    """SW-006 / SIM-002: subprocess ``simulate --spice-preset ac`` writes analysis into .cir."""
    script = tmp_path / "subprocess_sim.py"
    script.write_text(_SUBPROCESS_BOARD, encoding="utf-8")
    env = {
        **os.environ,
        "PYTHONPATH": str(_REPO_ROOT),
    }
    r = subprocess.run(
        [
            sys.executable,
            "-m",
            "openhac.cli",
            "simulate",
            str(script),
            "--name",
            "sub_sim_ac",
            "--spice-preset",
            "ac",
        ],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    assert r.returncode == 0, (r.stdout, r.stderr)
    cir = tmp_path / "sub_sim_ac.cir"
    assert cir.is_file()
    text = cir.read_text(encoding="utf-8")
    assert ".ac dec" in text


def test_openhac_cli_subprocess_simulate_spice_preset_tran(tmp_path):
    """SIM-002 / SW-006: subprocess ``simulate --spice-preset tran`` writes transient analysis into .cir."""
    script = tmp_path / "subprocess_sim_tran.py"
    script.write_text(_SUBPROCESS_BOARD, encoding="utf-8")
    env = {
        **os.environ,
        "PYTHONPATH": str(_REPO_ROOT),
    }
    r = subprocess.run(
        [
            sys.executable,
            "-m",
            "openhac.cli",
            "simulate",
            str(script),
            "--name",
            "sub_sim_tran",
            "--spice-preset",
            "tran",
        ],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    assert r.returncode == 0, (r.stdout, r.stderr)
    cir = tmp_path / "sub_sim_tran.cir"
    assert cir.is_file()
    text = cir.read_text(encoding="utf-8")
    assert ".tran" in text.lower()


def _run_simulate_preset(tmp_path, preset: str, out_name: str):
    script = tmp_path / f"subprocess_sim_{preset}.py"
    script.write_text(_SUBPROCESS_BOARD, encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(_REPO_ROOT)}
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "openhac.cli",
            "simulate",
            str(script),
            "--name",
            out_name,
            "--spice-preset",
            preset,
        ],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )


def test_openhac_cli_subprocess_simulate_spice_preset_op(tmp_path):
    """SIM-002 / SW-006: ``--spice-preset op`` emits operating-point analysis."""
    r = _run_simulate_preset(tmp_path, "op", "sub_sim_op")
    assert r.returncode == 0, (r.stdout, r.stderr)
    cir = tmp_path / "sub_sim_op.cir"
    assert cir.is_file()
    assert ".op" in cir.read_text(encoding="utf-8").lower()


def test_openhac_cli_subprocess_simulate_spice_preset_dc(tmp_path):
    """SIM-002 / SW-006: ``--spice-preset dc`` emits DC sweep directive."""
    r = _run_simulate_preset(tmp_path, "dc", "sub_sim_dc")
    assert r.returncode == 0, (r.stdout, r.stderr)
    cir = tmp_path / "sub_sim_dc.cir"
    assert cir.is_file()
    assert ".dc" in cir.read_text(encoding="utf-8").lower()


def test_openhac_cli_subprocess_simulate_spice_preset_noise(tmp_path):
    """SIM-002 / SW-006: ``--spice-preset noise`` emits noise analysis directive."""
    r = _run_simulate_preset(tmp_path, "noise", "sub_sim_noise")
    assert r.returncode == 0, (r.stdout, r.stderr)
    cir = tmp_path / "sub_sim_noise.cir"
    assert cir.is_file()
    assert ".noise" in cir.read_text(encoding="utf-8").lower()


def test_openhac_cli_subprocess_simulate_spice_analysis_yaml(tmp_path):
    """SIM-002: --spice-analysis-json accepts YAML with preset."""
    script = tmp_path / "subprocess_sim_yaml.py"
    script.write_text(_SUBPROCESS_BOARD, encoding="utf-8")
    yml = tmp_path / "sim.yaml"
    yml.write_text("preset: op\n", encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(_REPO_ROOT)}
    r = subprocess.run(
        [
            sys.executable,
            "-m",
            "openhac.cli",
            "simulate",
            str(script),
            "--name",
            "sub_sim_yaml",
            "--spice-analysis-json",
            str(yml),
        ],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    assert r.returncode == 0, (r.stdout, r.stderr)
    cir = tmp_path / "sub_sim_yaml.cir"
    assert cir.is_file()
    assert ".op" in cir.read_text(encoding="utf-8").lower()


def test_openhac_cli_subprocess_simulate_spice_line(tmp_path):
    """SIM-002 / SW-006: ``--spice-line`` overrides preset and writes the directive into .cir."""
    script = tmp_path / "subprocess_sim_line.py"
    script.write_text(_SUBPROCESS_BOARD, encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(_REPO_ROOT)}
    r = subprocess.run(
        [
            sys.executable,
            "-m",
            "openhac.cli",
            "simulate",
            str(script),
            "--name",
            "sub_sim_line",
            "--spice-line",
            ".op",
        ],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    assert r.returncode == 0, (r.stdout, r.stderr)
    cir = tmp_path / "sub_sim_line.cir"
    assert cir.is_file()
    assert ".op" in cir.read_text(encoding="utf-8").lower()
