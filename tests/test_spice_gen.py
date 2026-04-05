"""SIM-001 / SIM-002 — SPICE export (.include + analysis lines)."""

from __future__ import annotations

import openhac.core  # noqa: F401
from skidl import Net, Part

from openhac.compiler.spice_gen import generate_spice
from openhac.compiler.spice_presets import preset_analysis_lines


def test_generate_spice_custom_analysis_and_include(tmp_path):
    vcc, gnd = Net("3V3"), Net("GND")
    Part("power", "PWR_FLAG")[1] += vcc
    Part("power", "PWR_FLAG")[1] += gnd
    r = Part("Device", "R", value="1k", ref="R1")
    r[1] += vcc
    r[2] += gnd
    r.fields["Spice_Include"] = "models/vendor.lib"

    out = tmp_path / "t.cir"
    generate_spice(
        str(out),
        analysis_lines=[".op", ".ac dec 10 1 1e6"],
    )
    text = out.read_text(encoding="utf-8")
    assert "SIM-002 analysis directives" in text
    assert ".include models/vendor.lib" in text
    assert ".op" in text
    assert ".ac dec 10 1 1e6" in text
    assert "R1" in text or "1k" in text


def test_generate_spice_subckt_from_part_field(tmp_path):
    vcc, gnd = Net("3V3"), Net("GND")
    Part("power", "PWR_FLAG")[1] += vcc
    Part("power", "PWR_FLAG")[1] += gnd
    r = Part("Device", "R", value="model_cell", ref="R1")
    r[1] += vcc
    r[2] += gnd
    r.fields["Spice_Subckt"] = "MY_SUBCKT"

    out = tmp_path / "sub.cir"
    generate_spice(str(out))
    text = out.read_text(encoding="utf-8")
    assert "MY_SUBCKT" in text
    assert any(
        ln.strip().startswith("X") and "MY_SUBCKT" in ln for ln in text.splitlines()
    )


def test_spice_presets():
    assert ".ac" in preset_analysis_lines("ac")[0]
    assert preset_analysis_lines("op") == [".op"]


def test_spice_analysis_lines_from_json_file(tmp_path):
    """SIM-002: JSON bundle of analysis lines (same shape as CLI --spice-analysis-json)."""
    cfg = tmp_path / "an.json"
    cfg.write_text('{"analysis_lines": [".dc v1 0 3.3 0.1", ".op"]}\n', encoding="utf-8")
    import json

    raw = json.loads(cfg.read_text(encoding="utf-8"))
    lines = list(raw["analysis_lines"])

    vcc, gnd = Net("3V3"), Net("GND")
    Part("power", "PWR_FLAG")[1] += vcc
    Part("power", "PWR_FLAG")[1] += gnd
    r = Part("Device", "R", value="1k", ref="R1")
    r[1] += vcc
    r[2] += gnd
    out = tmp_path / "from_json.cir"
    generate_spice(str(out), analysis_lines=lines)
    text = out.read_text(encoding="utf-8")
    assert ".dc v1 0 3.3 0.1" in text
    assert ".op" in text
