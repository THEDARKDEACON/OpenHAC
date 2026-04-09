from __future__ import annotations

from pathlib import Path

from skidl import Net, Part

from openhac.compiler.schematic_gen import generate_schematic
from openhac.core.board import Board
from openhac.core.base import Module


class _M(Module):
    def __init__(self, name: str, net: Net):
        super().__init__(name)
        self.r = self.add(Part("Device", "R", value="10k", footprint="Resistor_SMD:R_0603_1608Metric"))
        net += self.r[1]
        self.declare_interface("io", net)


def test_multisheet_emits_sheet_pins_and_child_hier_labels(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("OPENHAC_SCHEMATIC_MULTI_SHEET", "1")
    monkeypatch.setenv("OPENHAC_SCHEMATIC_STUB_ONLY", "1")

    n = Net("SIG_A")
    b = Board((10, 10))
    m1 = _M("MOD1", n)
    b.add_module(m1)

    out = tmp_path / "p.kicad_sch"
    generate_schematic(str(out), b)

    root = out.read_text(encoding="utf-8")
    assert "(sheet" in root
    assert '(pin "SIG_A" passive' in root

    child = tmp_path / "p.MOD1.kicad_sch"
    txt = child.read_text(encoding="utf-8")
    assert '(hierarchical_label "SIG_A" (shape passive)' in txt

