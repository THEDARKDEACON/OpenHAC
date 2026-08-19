"""SCH-003: parse KiCad ERC report files."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openhac.compiler.kicad_erc_report import summarize_kicad_erc_report


def test_summarize_json_list_severities(tmp_path):
    p = tmp_path / "erc.json"
    p.write_text(
        json.dumps(
            [
                {"severity": "error", "msg": "a"},
                {"severity": "warning", "msg": "b"},
                {"type": "error", "msg": "c"},
            ]
        ),
        encoding="utf-8",
    )
    s = summarize_kicad_erc_report(p)
    assert s["format"] == "json"
    assert s["error_count"] == 2
    assert s["warning_count"] == 1


def test_summarize_json_violations_wrapper(tmp_path):
    p = tmp_path / "erc.json"
    p.write_text(
        json.dumps({"violations": [{"severity": "error"}, {"severity": "warning"}]}),
        encoding="utf-8",
    )
    s = summarize_kicad_erc_report(p)
    assert s["error_count"] == 1
    assert s["warning_count"] == 1


def test_summarize_json_kicad9_sheets(tmp_path):
    p = tmp_path / "erc.json"
    p.write_text(
        json.dumps(
            {
                "sheets": [
                    {
                        "violations": [
                            {"severity": "error", "type": "pin_not_connected"},
                            {"severity": "warning", "type": "lib_symbol_mismatch"},
                        ]
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    s = summarize_kicad_erc_report(p)
    assert s["error_count"] == 1
    assert s["warning_count"] == 1


def test_summarize_text_heuristic(tmp_path):
    p = tmp_path / "erc.txt"
    p.write_text("ERC report\nError: floating pin\nwarning: minor\n", encoding="utf-8")
    s = summarize_kicad_erc_report(p)
    assert s["format"] == "text"
    assert s["error_count"] >= 1


def test_summarize_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        summarize_kicad_erc_report(tmp_path / "nope.json")
