"""SW-006: smoke-test ``openhac.cli.main`` compile path (in-process)."""

from __future__ import annotations

import json
import sys
from unittest.mock import patch

import pytest
from skidl import Net, Part

import openhac.core  # noqa: F401
from openhac.core import Board
from openhac.core.base import Component, Module


@pytest.fixture()
def seeded_resistor_db(tmp_db, monkeypatch):
    _, dm = tmp_db
    dm.insert_component(
        {
            "generic_name": "R_10k_0805",
            "kicad_symbol": "Device:R",
            "kicad_footprint": "Resistor_SMD:R_0805_2012Metric",
            "manufacturer": "",
            "mpn": "X",
            "description": "",
        }
    )
    monkeypatch.setattr(Component, "db", dm)


def test_cli_main_compile_smoke(tmp_path, seeded_resistor_db, monkeypatch):
    script = tmp_path / "cli_board.py"
    script.write_text(
        """
import openhac.core
from skidl import Net, Part
from openhac.core import Board
from openhac.core.base import Component, Module

vcc, gnd = Net("3V3"), Net("GND")
Part("power", "PWR_FLAG")[1] += vcc
Part("power", "PWR_FLAG")[1] += gnd

class Node(Module):
    def __init__(self, name: str):
        super().__init__(name)
        r = self.add(Component("R_10k_0805"))
        r["1"] += vcc
        r["2"] += gnd
        self.declare_interface("power", vcc, gnd)

a, b = Node("A"), Node("B")
board = Board(size_mm=(44.0, 33.0))
board.add_module(a)
board.add_module(b)
board.connect(a.expose_interface("power"), b.expose_interface("power"))
""",
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "openhac",
            "compile",
            str(script),
            "--name",
            "from_cli",
            "--no-route",
            "--no-schematic",
        ],
    )

    with patch("openhac.compiler.layout_gen.generate_layout"):
        import openhac.cli as cli

        cli.main()

    assert (tmp_path / "from_cli.net").is_file()
    mf = json.loads((tmp_path / "from_cli.openhac-manifest.json").read_text(encoding="utf-8"))
    assert mf["project_name"] == "from_cli"
    assert mf["source_input"]["path"] == str(script.resolve())
    assert len(mf["source_input"]["sha256"]) == 64


def test_cli_main_help_exits_zero(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["openhac", "--help"])
    import openhac.cli as cli

    with pytest.raises(SystemExit) as exc_info:
        cli.main()
    assert exc_info.value.code == 0


def test_cli_compile_strict_jit_flag_smoke(tmp_path, seeded_resistor_db, monkeypatch):
    script = tmp_path / "cli_strict.py"
    script.write_text(
        """
import openhac.core
from skidl import Net, Part
from openhac.core import Board
from openhac.core.base import Component, Module

vcc, gnd = Net("3V3"), Net("GND")
Part("power", "PWR_FLAG")[1] += vcc
Part("power", "PWR_FLAG")[1] += gnd

class Node(Module):
    def __init__(self, name: str):
        super().__init__(name)
        r = self.add(Component("R_10k_0805"))
        r["1"] += vcc
        r["2"] += gnd
        self.declare_interface("power", vcc, gnd)

a, b = Node("A"), Node("B")
board = Board(size_mm=(40.0, 30.0))
board.add_module(a)
board.add_module(b)
board.connect(a.expose_interface("power"), b.expose_interface("power"))
""",
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "openhac",
            "compile",
            str(script),
            "--name",
            "strict_jit_cli",
            "--no-route",
            "--no-schematic",
            "--strict-jit",
        ],
    )

    with patch("openhac.compiler.layout_gen.generate_layout"):
        import openhac.cli as cli

        cli.main()

    assert (tmp_path / "strict_jit_cli.net").is_file()
