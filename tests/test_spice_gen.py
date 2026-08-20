"""SIM-001 / SIM-002 — SPICE export (.include + analysis lines)."""

from __future__ import annotations

import re

import openhac.core  # noqa: F401
from skidl import Net, Part

from openhac.compiler.spice_gen import extract_passive_spice_value, generate_spice
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


def test_extract_passive_spice_value_from_generic_names():
    assert extract_passive_spice_value("1k", kind="R") == "1k"
    assert extract_passive_spice_value("C_VBUS_10U", kind="C") == "10u"
    assert extract_passive_spice_value("C_24V_100U", kind="C") == "100u"
    assert extract_passive_spice_value("R_CC1_5K1", kind="R") == "5.1k"
    assert extract_passive_spice_value("R_24V_HI_100K", kind="R") == "100k"
    assert extract_passive_spice_value("R_FET_G_100", kind="R") == "100"
    assert extract_passive_spice_value("R_CAN_120", kind="R") == "120"
    assert extract_passive_spice_value("C_XTAL_18PF_A", kind="C") == "18p"
    assert extract_passive_spice_value("Capacitor 10uF 0805", kind="C") == "10u"
    assert extract_passive_spice_value("Resistor 4.7k 0805", kind="R") == "4.7k"
    assert extract_passive_spice_value("Inductor 10uH 0805", kind="L") == "10u"
    assert extract_passive_spice_value("R_PUTRUNK_SDA", kind="R") is None


def test_generate_spice_passive_generic_name_and_skips_ics(tmp_path):
    vcc, gnd = Net("3V3"), Net("GND")
    Part("power", "PWR_FLAG")[1] += vcc
    Part("power", "PWR_FLAG")[1] += gnd
    r = Part("Device", "R", value="R_CC1_5K1", ref="R1")
    r[1] += vcc
    r[2] += gnd
    c = Part("Device", "R", value="C_VBUS_10U", ref="C1")
    c[1] += vcc
    c[2] += gnd
    u = Part("Device", "R", value="ESP32_S3", ref="U1")
    u[1] += vcc
    u[2] += gnd
    fuse = Part("Device", "R", value="F_24V", ref="F1")
    fuse[1] += vcc
    fuse[2] += gnd
    j = Part("Device", "R", value="Conn_01x08", ref="J1")
    j[1] += vcc
    j[2] += gnd
    out = tmp_path / "p.cir"
    generate_spice(str(out), analysis_lines=[".op"])
    text = out.read_text(encoding="utf-8")
    assert re.search(r"^R1\s+\S+\s+\S+\s+5\.1k\s*$", text, re.M)
    assert re.search(r"^C1\s+\S+\s+\S+\s+10u\s*$", text, re.M)
    assert not re.search(r"^U1\s+", text, re.M)
    assert any("skipped U1" in ln for ln in text.splitlines())
    assert not re.search(r"^J1\s+", text, re.M)
    assert any("skipped J1: connector/mechanical" in ln for ln in text.splitlines())
    assert re.search(r"^RF1\s+\S+\s+\S+\s+10m\s*$", text, re.M)
    assert not re.search(r"^F1\s+", text, re.M)
