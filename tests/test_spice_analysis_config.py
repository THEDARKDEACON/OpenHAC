"""SIM-002: JSON/YAML spice analysis config loading."""

from __future__ import annotations

import json

import pytest


def test_load_json_analysis_lines(tmp_path):
    from openhac.compiler.spice_analysis_config import load_spice_analysis_raw, resolve_spice_analysis_from_mapping

    p = tmp_path / "a.json"
    p.write_text(json.dumps({"analysis_lines": [".op"]}), encoding="utf-8")
    raw = load_spice_analysis_raw(p)
    al, pr = resolve_spice_analysis_from_mapping(raw)
    assert al == [".op"]
    assert pr is None


def test_load_yaml_preset(tmp_path):
    from openhac.compiler.spice_analysis_config import load_spice_analysis_raw, resolve_spice_analysis_from_mapping

    p = tmp_path / "a.yaml"
    p.write_text("preset: dc\n", encoding="utf-8")
    raw = load_spice_analysis_raw(p)
    al, pr = resolve_spice_analysis_from_mapping(raw)
    assert al is None
    assert pr == "dc"


def test_mutually_exclusive_raises(tmp_path):
    from openhac.compiler.spice_analysis_config import load_spice_analysis_raw, resolve_spice_analysis_from_mapping

    p = tmp_path / "bad.json"
    p.write_text(json.dumps({"analysis_lines": [".op"], "preset": "tran"}), encoding="utf-8")
    raw = load_spice_analysis_raw(p)
    with pytest.raises(ValueError, match="only one"):
        resolve_spice_analysis_from_mapping(raw)
