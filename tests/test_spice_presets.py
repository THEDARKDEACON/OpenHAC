"""SIM-002 named SPICE presets."""

from openhac.compiler.spice_presets import PRESETS, preset_analysis_lines


def test_preset_dc_and_noise_exist():
    assert ".dc" in " ".join(PRESETS["dc"])
    assert ".noise" in " ".join(PRESETS["noise"])


def test_preset_analysis_lines_roundtrip():
    assert preset_analysis_lines("tran")[0].startswith(".tran")
