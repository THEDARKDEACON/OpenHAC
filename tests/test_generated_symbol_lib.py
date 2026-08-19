from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from skidl import Net, Part, Pin

from openhac.core import Board
from openhac.core.base import Module


def test_compile_writes_generated_kicad_sym_and_sym_lib_table(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    design_py = tmp_path / "design.py"
    design_py.write_text("# gen sym\n", encoding="utf-8")

    vcc, gnd = Net("3V3"), Net("GND")
    import skidl

    pfv = Part(
        tool=skidl.SKIDL,
        name="PWR_FLAG",
        ref_prefix="PWR",
        pins=[Pin(num="1", name="1")],
        footprint="TestPoint:TestPoint_Pad_D1.0mm",
    )
    pfg = Part(
        tool=skidl.SKIDL,
        name="PWR_FLAG",
        ref_prefix="PWR",
        pins=[Pin(num="1", name="1")],
        footprint="TestPoint:TestPoint_Pad_D1.0mm",
    )
    pfv[1] += vcc
    pfg[1] += gnd

    class M(Module):
        def __init__(self):
            super().__init__("M")
            # SKiDL-native part (tool=SKIDL) with footprint.
            import skidl

            p = Part(
                tool=skidl.SKIDL,
                name="MY_NATIVE_IC",
                ref_prefix="U",
                pins=[Pin(num="1", name="VCC"), Pin(num="2", name="GND")],
                footprint="Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
            )
            p["VCC"] += vcc
            p["GND"] += gnd
            self.add(p)
            self.power = self.declare_interface("power", vcc, gnd)

    b = Board(size_mm=(20, 20))
    m = M()
    b.add_module(m)

    # Avoid needing pcbnew in this unit test.
    with patch("openhac.compiler.layout_gen.generate_layout"):
        b.compile(
            project_name="gen",
            generate_bom=True,
            auto_route=False,
            export_schematic=True,
            source_script_path=str(design_py),
            output_dir=str(tmp_path),
        )

    sch = (tmp_path / "gen.kicad_sch").read_text(encoding="utf-8")
    sub_path = tmp_path / "gen.M.kicad_sch"
    sub = sub_path.read_text(encoding="utf-8") if sub_path.is_file() else ""
    assert 'lib_id "OpenHaC:MY_NATIVE_IC"' in sch or 'lib_id "OpenHaC:MY_NATIVE_IC"' in sub

    sym = tmp_path / "gen.openhac-generated.kicad_sym"
    assert sym.is_file()
    text = sym.read_text(encoding="utf-8")
    assert '(symbol "MY_NATIVE_IC"' in text
    assert '(number "1"' in text and '(number "2"' in text

    slt = tmp_path / "sym-lib-table"
    assert slt.is_file()
    assert "OpenHaC" in slt.read_text(encoding="utf-8")

    mf = json.loads((tmp_path / "gen.openhac-manifest.json").read_text(encoding="utf-8"))
    assert mf.get("sch001_kicad_sch_suffix") == ".kicad_sch"

