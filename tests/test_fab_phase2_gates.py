"""Phase-2 FAB gate unit tests (no pcbnew required)."""

from __future__ import annotations

import json
import os

import pytest

from openhac.core.exceptions import OpenHaCError
from openhac.core.pin_resolution import get_pins_from_data
from openhac.database.enrich import network_allowed


def test_fab001_refuses_invented_pins(monkeypatch):
    monkeypatch.setenv("OPENHAC_COMPILE_GOAL", "fabrication")
    with pytest.raises(OpenHaCError, match="FAB-001"):
        get_pins_from_data({"generic_name": "UNKNOWN_IC", "package": "QFN-48"})


def test_fab001_refuses_corrupt_pinout_json(monkeypatch):
    monkeypatch.setenv("OPENHAC_COMPILE_GOAL", "fabrication")
    with pytest.raises(OpenHaCError, match="FAB-001"):
        get_pins_from_data({"generic_name": "X", "pinout_json": "{not-json"})


def test_fab001_handoff_allows_invented_pins(monkeypatch):
    monkeypatch.setenv("OPENHAC_COMPILE_GOAL", "handoff")
    pins = get_pins_from_data({"generic_name": "UNKNOWN_IC", "package": "WEIRD-PKG"})
    assert len(pins) >= 2
    assert any(str(p.name).startswith("Pin_") for p in pins)


def test_fab001_explicit_pinout_ok_in_fab(monkeypatch):
    monkeypatch.setenv("OPENHAC_COMPILE_GOAL", "fabrication")
    pinout = json.dumps([{"num": "1", "name": "VIN", "type": "power_in"}, {"num": "2", "name": "GND", "type": "power_in"}])
    pins = get_pins_from_data({"generic_name": "REG", "pinout_json": pinout})
    assert [p.name for p in pins] == ["VIN", "GND"]


def test_fab010_network_denied_in_fabrication(monkeypatch):
    monkeypatch.delenv("OPENHAC_NO_NETWORK", raising=False)
    monkeypatch.delenv("OPENHAC_ALLOW_NETWORK", raising=False)
    monkeypatch.delenv("OPENHAC_DETERMINISTIC", raising=False)
    monkeypatch.setenv("OPENHAC_COMPILE_GOAL", "fabrication")
    assert network_allowed() is False


def test_fab010_break_glass_allows_network(monkeypatch):
    monkeypatch.delenv("OPENHAC_NO_NETWORK", raising=False)
    monkeypatch.setenv("OPENHAC_COMPILE_GOAL", "fabrication")
    monkeypatch.setenv("OPENHAC_ALLOW_NETWORK", "1")
    assert network_allowed() is True


def test_fab010_handoff_allows_network_by_default(monkeypatch):
    monkeypatch.delenv("OPENHAC_NO_NETWORK", raising=False)
    monkeypatch.delenv("OPENHAC_ALLOW_NETWORK", raising=False)
    monkeypatch.delenv("OPENHAC_DETERMINISTIC", raising=False)
    monkeypatch.setenv("OPENHAC_COMPILE_GOAL", "handoff")
    assert network_allowed() is True


def test_fab002_layout_gen_strict_under_fab(monkeypatch):
    from openhac.compiler.layout_gen import assert_footprint_pin_pad_or_raise
    from openhac.core.base import LayoutGenerationError
    from openhac.core.board import Board

    b = Board((10, 10), compile_goal="fabrication")
    monkeypatch.setattr(
        "openhac.compiler.pcb_placement.pin_pad_coverage_warnings_for_board",
        lambda _board: ["R1 pin 1 has no matching pad"],
    )
    with pytest.raises(LayoutGenerationError, match="PCB-002"):
        assert_footprint_pin_pad_or_raise(b)


def test_fab003_release_zip_refuses_omitted(tmp_path, monkeypatch):
    from openhac.compiler.compile_pipeline import CompileState, phase_release_zip
    from openhac.core.board import Board

    b = Board((10, 10), compile_goal="fabrication")
    state = CompileState(
        board=b,
        project_name="t",
        generate_bom=False,
        auto_route=False,
        export_schematic=False,
        allow_risky_part_lookups=False,
        kicad_sch_erc=False,
        kicad_sch_erc_format="report",
        source_script_path=None,
        output_dir=str(tmp_path),
        release_zip_path=str(tmp_path / "out.zip"),
    )
    state.omitted_footprint_refs = ["U1"]
    with pytest.raises(RuntimeError, match="FAB-003"):
        phase_release_zip(state)


def test_fab012_cache_path_not_in_tree_by_default(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENHAC_API_CACHE_PATH", str(tmp_path / "cache" / "api_cache.db"))
    # Re-import path resolution by constructing APICache
    from openhac.database.vendor_apis import APICache

    c = APICache(db_path=str(tmp_path / "cache" / "api_cache.db"))
    assert os.path.isfile(c.db_path)
    assert "openhac/database/api_cache.db" not in c.db_path.replace("\\", "/")


def test_fab032_fab_audit_keys_on_manifest(tmp_path, monkeypatch):
    from openhac.compiler.compile_manifest import write_compile_manifest
    from openhac.core.board import Board

    monkeypatch.chdir(tmp_path)
    b = Board((10, 10), compile_goal="handoff")
    b._last_omitted_footprint_refs = ["R99"]
    b._last_enrich_failures = [{"generic_name": "X", "reason": "lookup_failed"}]
    b._last_pad_pin_warnings = ["warn"]
    b._last_network_allowed = False
    b._last_pcb_metrics = {"track_count": 1, "unrouted_net_count": 0, "footprint_count": 2}
    write_compile_manifest(
        "proj",
        b,
        generate_bom=False,
        export_schematic=False,
        output_dir=str(tmp_path),
        auto_route=False,
        skip_layout=True,
    )
    man = json.loads((tmp_path / "proj.openhac-manifest.json").read_text(encoding="utf-8"))
    assert man["fab_audit"]["schema_ref"] == "openhac.fab_audit.v1"
    assert man["fab_audit"]["omitted_footprint_refs"] == ["R99"]
    assert man["fab_audit"]["enrich_failures"][0]["generic_name"] == "X"
    assert man["fab032_fab_audit_schema"] == "openhac.fab_audit.v1"
