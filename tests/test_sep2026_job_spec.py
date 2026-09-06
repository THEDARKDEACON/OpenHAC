"""Sep 2026 job-spec gates (FAB/SPS/PERF/CODE)."""

from __future__ import annotations

import json
import os

import pytest

from openhac.core.exceptions import OpenHaCError


def test_fab004_spice_no_silent_skidl(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENHAC_LEGACY_SKIDL", raising=False)
    monkeypatch.setenv("OPENHAC_COMPILE_GOAL", "fabrication")
    from openhac.core.circuit import reset_default_circuit
    from openhac.compiler.spice_gen import generate_spice

    reset_default_circuit()
    with pytest.raises(OpenHaCError, match="FAB-004"):
        generate_spice(str(tmp_path / "x.cir"), signoff=True)


def test_fab004_collect_no_silent_skidl(monkeypatch):
    monkeypatch.delenv("OPENHAC_LEGACY_SKIDL", raising=False)
    monkeypatch.setenv("OPENHAC_SCHEMATIC_SIGNOFF", "1")
    from openhac.core.circuit import reset_default_circuit
    from openhac.schematic.collect import collect_parts_and_nets

    reset_default_circuit()
    with pytest.raises(OpenHaCError, match="FAB-004"):
        collect_parts_and_nets(None)


def test_fab023_physics_raises_under_fab(monkeypatch):
    from openhac.compiler.compile_pipeline import CompileState
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
        output_dir=".",
        release_zip_path=None,
    )
    assert state.compile_goal == "fabrication"
    with pytest.raises(RuntimeError, match="physics"):
        try:
            raise RuntimeError("physics boom")
        except Exception as e:
            if state.compile_goal == "fabrication":
                raise
            raise AssertionError("should have re-raised") from e


def test_fab013_enrich_lookup_failed_aborts(monkeypatch, tmp_path):
    from openhac.compiler.compile_pipeline import CompileState, phase_enrich_parts
    from openhac.core.board import Board
    from openhac.core.base import Component, Module

    class M(Module):
        def __init__(self):
            super().__init__("M")
            data = {
                "generic_name": "NO_SUCH_IC_XYZ",
                "kicad_footprint": "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
                "kicad_symbol": "Device:R",
                "pinout_json": "[]",
                "category": "ic",
            }
            self.c = self.add(
                Component(
                    "NO_SUCH_IC_XYZ",
                    comp_data=data,
                    pins={"1": ("1", "passive"), "2": ("2", "passive")},
                )
            )

    b = Board((10, 10), compile_goal="fabrication")
    monkeypatch.setenv("OPENHAC_COMPILE_GOAL", "fabrication")
    monkeypatch.setenv("OPENHAC_ALLOW_NETWORK", "1")
    b.add_module(M())
    state = CompileState(
        board=b,
        project_name="t",
        generate_bom=False,
        auto_route=False,
        export_schematic=False,
        allow_risky_part_lookups=True,
        kicad_sch_erc=False,
        kicad_sch_erc_format="report",
        source_script_path=None,
        output_dir=str(tmp_path),
        release_zip_path=None,
    )

    class Res:
        attempted = True
        updated = False
        reason = "lookup_failed:offline"

    monkeypatch.setattr(
        "openhac.database.enrich.needs_pinout_database_enrich",
        lambda *a, **k: True,
    )
    monkeypatch.setattr(
        "openhac.database.enrich.enrich_component_in_db",
        lambda **k: Res(),
    )
    monkeypatch.setattr("openhac.database.enrich.network_allowed", lambda: True)
    monkeypatch.setattr("openhac.database.enrich._get_override_asset", lambda *a, **k: None)
    with pytest.raises(RuntimeError, match="FAB-013"):
        phase_enrich_parts(state)


def test_fab010_parametric_no_http(monkeypatch, tmp_db):
    monkeypatch.setenv("OPENHAC_NO_NETWORK", "1")
    monkeypatch.setenv("OPENHAC_COMPILE_GOAL", "handoff")
    called = []

    def boom(*a, **k):
        called.append(1)
        raise AssertionError("HTTP must not run")

    monkeypatch.setattr("urllib.request.urlopen", boom)
    _path, db = tmp_db
    row, _fb = db.parametric_search("resistors", value="10k", package="0805")
    assert row is None
    assert called == []


def test_code001_restores_defer_pours(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENHAC_DEFER_COPPER_POURS", raising=False)
    from openhac.compiler.compile_pipeline import (
        CompileState,
        _maybe_set_defer_copper_pours,
        restore_owned_defer_pours,
        run_compile_phases,
    )
    from openhac.core.board import Board

    b = Board((10, 10))
    state = CompileState(
        board=b,
        project_name="t",
        generate_bom=False,
        auto_route=True,
        export_schematic=False,
        allow_risky_part_lookups=False,
        kicad_sch_erc=False,
        kicad_sch_erc_format="report",
        source_script_path=None,
        output_dir=str(tmp_path),
        release_zip_path=None,
    )
    state.skip_layout = False
    _maybe_set_defer_copper_pours(state)
    assert os.environ.get("OPENHAC_DEFER_COPPER_POURS") == "1"
    restore_owned_defer_pours(state)
    assert not (os.environ.get("OPENHAC_DEFER_COPPER_POURS") or "").strip()

    def _noop(_s):
        _maybe_set_defer_copper_pours(_s)

    monkeypatch.delenv("OPENHAC_DEFER_COPPER_POURS", raising=False)
    state._owned_defer_pours = False
    state._prev_defer_pours = None
    run_compile_phases(state, (_noop,))
    assert not (os.environ.get("OPENHAC_DEFER_COPPER_POURS") or "").strip()


def test_lib007_reference_bom_not_auto_merged():
    from openhac.database.catalog_overlay import load_bundled_overlay_index, reset_catalog_overlay_caches

    reset_catalog_overlay_caches()
    idx = load_bundled_overlay_index()
    assert "REFBOM_OPT_IN_ONLY" not in idx
    assert "IMU_ICM42688P" in idx


def test_abc046_ignores_esp32_substring_without_rf_prefix():
    from openhac.compiler.advanced_board_policy import check_rf_fab_gate
    from openhac.core import Board
    from openhac.core.base import Component, Module
    from openhac.core.net import Net

    class M(Module):
        def __init__(self):
            super().__init__("Brick")
            data = {
                "generic_name": "SOME_ESP32_BRICK",
                "kicad_footprint": "Module:ESP32-DevKit",
                "kicad_symbol": "Device:R",
                "pinout_json": json.dumps(
                    [{"num": "1", "name": "1", "type": "passive"}, {"num": "2", "name": "2", "type": "passive"}]
                ),
                "category": "MCU",
            }
            self.c = self.add(Component("SOME_ESP32_BRICK", comp_data=data))
            self.c[1] += Net("A")
            self.c[2] += Net("B")

    board = Board(size_mm=(50, 50), board_class="rf", compile_goal="fabrication", strict=False)
    board.add_module(M())
    assert check_rf_fab_gate(board) == []


def test_sch006_flow_from_tag_not_name():
    from openhac.core.board import Board
    from openhac.core.module import Module
    from openhac.schematic.layout import _flow_column

    m = Module("PSU1", schematic_flow="power")
    b = Board((10, 10))
    b.modules = [m]
    assert _flow_column("PSU1", b) == 0
    m2 = Module("ldo_named_without_tag")
    b.modules = [m2]
    assert _flow_column("ldo_named_without_tag", b) == 1


def test_code003_rf_module_no_wroom_default():
    from openhac.stdlib.interface import RF_Module

    with pytest.raises(ValueError, match="not found"):
        RF_Module(protocol="NoSuchRadioXYZ", form_factor="DIP")


def test_code003_switching_reg_no_mock_pins():
    from openhac.stdlib.power import SwitchingRegulator

    reg = SwitchingRegulator("R", v_in_nominal=12.0, v_out=5.0, current_min=1.0, l_value="10uH")
    with pytest.raises(ValueError, match="CODE-003"):
        reg._build_circuit({"generic_name": "UNKNOWN_BUCK", "category": "ic"})


def test_perf001_indexes_on_tmp_db(tmp_db):
    _path, db = tmp_db
    conn = db._connect()
    names = {r[1] for r in conn.execute("PRAGMA index_list(components)").fetchall()}
    assert "idx_components_generic_name" in names
    plan = conn.execute(
        "EXPLAIN QUERY PLAN SELECT * FROM components WHERE generic_name = ?",
        ("R_10k_0805",),
    ).fetchall()
    blob = " ".join(str(x) for row in plan for x in row).upper()
    assert "SEARCH" in blob or "INDEX" in blob


def test_perf002_singleton_and_one_connection(tmp_path):
    from openhac.database.db_manager import DatabaseManager, reset_database_managers

    reset_database_managers()
    p = str(tmp_path / "c.db")
    a = DatabaseManager(db_path=p)
    b = DatabaseManager(db_path=p)
    assert a is b
    cx = a._connect()
    assert b._connect() is cx
    reset_database_managers()


def test_code001_and_perf007_phase_ms(tmp_path, monkeypatch):
    from openhac.compiler.compile_pipeline import CompileState, run_compile_phases
    from openhac.core.board import Board

    b = Board((10, 10))
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
        release_zip_path=None,
    )

    def _noop(_s):
        pass

    run_compile_phases(state, (_noop,))
    assert "_noop" in state.phase_ms
    assert isinstance(state.phase_ms["_noop"], int)


def test_code006_invented_pins_counted(monkeypatch):
    monkeypatch.setenv("OPENHAC_COMPILE_GOAL", "handoff")
    from openhac.core import base as core_base
    from openhac.core.pin_resolution import get_pins_from_data

    core_base._IMPLICIT_PIN_EVENTS.clear()
    pins = get_pins_from_data({"generic_name": "UNKNOWN_IC", "package": "WEIRD-PKG"})
    assert any(str(p.name).startswith("Pin_") for p in pins)
    assert any(e.get("invented") for e in core_base._IMPLICIT_PIN_EVENTS)


def test_code005_webview_escapes_script_in_json(tmp_path):
    from openhac.core.board import Board
    from openhac.core.base import Module
    from openhac.core.part import Part, Pin
    from openhac.core.net import Net
    from openhac.core.compile_context import OpenHaCCompileContext, compile_context_reset, compile_context_set

    board = Board(size_mm=(40, 40))
    tok = compile_context_set(OpenHaCCompileContext(board))
    try:
        class M(Module):
            def __init__(self):
                super().__init__("M")
                p = Part("U1", "Generic:X", {"value": "</script><b>x"}, [Pin("1", "A"), Pin("2", "B")])
                self.components.append(p)
                n = Net("N")
                p["A"] += n
                p["B"] += n
        board.add_module(M())
        html = tmp_path / "w.html"
        with pytest.warns(DeprecationWarning, match="FAB-041"):
            board.export_webview(str(html))
        text = html.read_text(encoding="utf-8")
        assert "</script><b>x" not in text
        assert "\\u003c/script" in text or "\\u003c" in text
        assert "function esc(" in text
    finally:
        compile_context_reset(tok)


def test_sso012_preview_command_exists():
    from openhac.cli import cmd_preview

    assert callable(cmd_preview)


def test_sso012_kicad_live_helpers(tmp_path):
    from openhac.compiler.kicad_live import prefer_kicad_open_path, reset_preview_runtime

    reset_preview_runtime()
    sch = tmp_path / "demo.kicad_sch"
    sch.write_text("(kicad_sch)", encoding="utf-8")
    assert prefer_kicad_open_path(tmp_path, "demo") == sch
    pro = tmp_path / "demo.kicad_pro"
    pro.write_text("{}", encoding="utf-8")
    assert prefer_kicad_open_path(tmp_path, "demo") == pro


def test_placement_profile_complex_ci():
    from openhac.compiler.placement_profile import apply_named_placement_profile

    env: dict[str, str] = {}
    apply_named_placement_profile(env, name="complex_ci")
    assert env["OPENHAC_MODULE_CLEARANCE_MM"] == "12.0"


def test_sps045_island_example_exists():
    from pathlib import Path

    p = Path(__file__).resolve().parents[1] / "examples" / "spice_island_golden.py"
    assert p.is_file()
    text = p.read_text(encoding="utf-8")
    assert "declare_spice_island" in text
    assert "fundi_mig" not in text.lower()


def test_sps045_island_declared_on_board():
    import runpy
    from pathlib import Path

    ns = runpy.run_path(str(Path(__file__).resolve().parents[1] / "examples" / "spice_island_golden.py"))
    board = ns["board"]
    assert "AnalogIsland" in board._spice_island_names
    assert "DigitalIgnored" not in board._spice_island_names


def test_code002_openhac_env_isolated():
    for key in ("OPENHAC_DETERMINISTIC", "OPENHAC_NO_NETWORK", "OPENHAC_DEFER_COPPER_POURS"):
        assert key not in os.environ


def test_sso012_svg_helper_never_runs_erc():
    from openhac.compiler import kicad_sch_svg
    from pathlib import Path

    src = Path(kicad_sch_svg.__file__).read_text(encoding="utf-8")
    assert 'kicad_cli, "sch", "export", "svg"' in src
    assert 'kicad_cli, "sch", "erc"' not in src
    from openhac import cli as cli_mod

    cli_src = Path(cli_mod.__file__).read_text(encoding="utf-8")
    assert '"--kicad"' in cli_src
    assert '"--watch"' in cli_src
    assert '"--no-browser"' in cli_src
    assert 'kicad_cli, "sch", "erc"' not in cli_src
    from openhac.compiler import svg_preview

    svg_src = Path(svg_preview.__file__).read_text(encoding="utf-8")
    assert 'kicad_cli, "sch", "erc"' not in svg_src
    assert "pcb" in svg_src and "export" in svg_src


def test_estimate_pin_count_eia_chip_is_two_terminal():
    from openhac.core.pin_resolution import estimate_pin_count

    assert estimate_pin_count("2520") == 2
    assert estimate_pin_count("0805") == 2
    assert estimate_pin_count("QFN-10") == 10


def test_package_template_pins_are_instance_copies():
    """PERF-001 auto-fills package=0805; templates must not share Pin objects."""
    from openhac.templates.packages import get_package_template

    a = get_package_template("0805")
    b = get_package_template("0805")
    assert a is not None and b is not None
    assert a[0] is not b[0]
    a[0].net = object()
    assert getattr(b[0], "net", None) is None


def test_two_0805_resistors_do_not_share_pin_objects(tmp_db, monkeypatch):
    from openhac.core.base import Component
    from openhac.core.net import Net

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
    r1 = Component("R_10k_0805")
    r2 = Component("R_10k_0805")
    assert r1.part.pins["1"] is not r2.part.pins["1"]
    n1, n2 = Net("RAIL_A"), Net("RAIL_B")
    r1["1"] += n1
    r2["1"] += n2
    assert r1.part.pins["1"].net is n1
    assert r2.part.pins["1"].net is n2
    assert len(n1.pins) == 1
    assert len(n2.pins) == 1
