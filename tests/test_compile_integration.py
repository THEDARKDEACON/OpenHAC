"""Integration-style compile test: netlist + BOM + manifest (SW-006)."""

from __future__ import annotations

import csv
import json
import zipfile
from unittest.mock import patch

import pytest
from skidl import Net, Part

import openhac.core  # noqa: F401
from openhac.compiler.netlist_gen import BOM_PROFILE_PROD_OMITTED_COLUMNS
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
            "jlc_class": "Extended",
        }
    )
    for offer in (
        {
            "generic_name": "R_10k_0805",
            "rank": 1,
            "supplier": "Mouser",
            "supplier_sku": "603-RC0805FR-0710KL",
            "mpn": "RC0805FR-0710KL",
            "note": "",
        },
        {
            "generic_name": "R_10k_0805",
            "rank": 2,
            "supplier": "DigiKey",
            "supplier_sku": "311-10.0KCRCT-ND",
            "mpn": "",
            "note": "",
        },
    ):
        dm.insert_part_offer(offer)
    monkeypatch.setattr(Component, "db", dm)


def test_compile_writes_net_csv_and_manifest(tmp_path, seeded_resistor_db, monkeypatch):
    monkeypatch.chdir(tmp_path)
    design_py = tmp_path / "design.py"
    design_py.write_text("# user design placeholder\n", encoding="utf-8")

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
    board = Board(size_mm=(50.0, 40.0))
    board.add_module(a)
    board.add_module(b)
    board.connect(a.expose_interface("power"), b.expose_interface("power"))

    with patch("openhac.compiler.layout_gen.generate_layout"):
        board.compile(
            project_name="e2e_compile",
            generate_bom=True,
            auto_route=False,
            export_schematic=False,
            source_script_path=design_py,
        )

    assert (tmp_path / "e2e_compile.net").is_file()
    assert (tmp_path / "e2e_compile.csv").is_file()
    mf = tmp_path / "e2e_compile.openhac-manifest.json"
    assert mf.is_file()
    data = json.loads(mf.read_text(encoding="utf-8"))
    assert data.get("manifest_schema_version") == "1.0"
    assert data["project_name"] == "e2e_compile"
    assert data["board_size_mm"] == [50.0, 40.0]
    assert data["openhac_version"]
    paths = {o["path"] for o in data["outputs"]}
    assert "e2e_compile.net" in paths
    assert "e2e_compile.csv" in paths
    # SCH-001: .kicad_pro is deterministic JSON (sorted keys) when exported.
    with (tmp_path / "e2e_compile.csv").open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert rows
    r_rows = [r for r in rows if r.get("Reference", "").startswith("R")]
    assert r_rows
    hdr = r_rows[0]
    for col in (
        "Alternate_SKUs",
        "Alternate_Notes",
        "Ranked_Offers",
        "OpenHaC_Watermark",
        "Alternate_Group_ID",
        "Primary_Offer",
        "Secondary_Offer",
        "OpenHaC_JIT_Score",
        "OpenHaC_JIT_Confidence",
        "Alternate_Count",
        "Offer_Count",
    ):
        assert col in hdr
    assert hdr.get("OpenHaC_JIT_Confidence") == "high"
    assert hdr.get("Alternate_Count") == "0"
    assert hdr.get("Offer_Count") == "2"
    assert "Mouser:" in (hdr.get("Primary_Offer") or "")
    sec = hdr.get("Secondary_Offer") or ""
    assert sec  # second ranked offer from seeded DB
    assert ":" in sec
    assert (tmp_path / "e2e_compile.openhac-autoroute-policy.md").is_file()
    co = data.get("compile_options") or {}
    assert co.get("auto_route") is False
    assert co.get("skip_layout") is False
    assert isinstance(data.get("openhac_env_keys_present"), list)
    assert isinstance(data.get("sch_kicad_symbol_dirs_configured"), bool)
    assert isinstance(data.get("sch_kicad_symbol_search_paths"), list)
    assert any(isinstance(p, str) and p for p in data.get("sch_kicad_symbol_search_paths") or [])
    assert isinstance(data.get("pcb_kicad_footprint_dirs_configured"), bool)
    assert isinstance(data.get("pcb_kicad_footprint_search_paths"), list)
    ph = data.get("pcb_pipeline_handoff") or {}
    assert isinstance(ph, dict) and ph.get("schema_ref") == "openhac.pcb_pipeline_handoff.v1"
    assert int(data.get("outputs_total_bytes") or 0) > 0
    assert int(data.get("outputs_artifact_count") or 0) >= 1
    spc = data.get("spice_presets_catalog") or []
    assert "ac" in spc and "tran" in spc and "op" in spc and "noise" in spc
    assert int(data.get("release_bundle_suffix_count") or 0) >= 1
    assert int(data.get("bom_csv_data_row_count") or 0) >= 1
    assert int(data.get("netlist_line_count") or 0) >= 1
    assert data.get("netlist_suffix") == ".net"
    assert data.get("pcb_pipeline_handoff_key_count") == 3
    assert data.get("str002_compile_pipeline_entry") == "openhac.compiler.compile_pipeline.run_compile_phases"
    assert data.get("sim002_spice_analysis_config_module") == "openhac.compiler.spice_analysis_config"
    assert data.get("str002_openhac_distribution_package") == "openhac"
    assert data.get("sch003_kicad_erc_report_suffixes") == [".kicad_sch.erc.txt", ".kicad_sch.erc.json"]
    assert data.get("mfg005_release_zip_sha256_note")
    assert data.get("str002_manifest_json_sort_keys") is True
    assert data.get("str002_patch_manifest_release_zip_function") == (
        "openhac.compiler.compile_manifest.patch_manifest_release_zip_sha256"
    )
    assert data.get("mfg005_zip_project_outputs_function") == "openhac.compiler.release_bundle.zip_project_outputs"
    assert data.get("sim002_spice_analysis_loader_function") == (
        "openhac.compiler.spice_analysis_config.load_spice_analysis_raw"
    )
    assert data.get("sw003_netlist_gen_module") == "openhac.compiler.netlist_gen"
    assert data.get("spice_presets_module") == "openhac.compiler.spice_presets"
    assert data.get("pcb001_kicad_pcb_suffix") == ".kicad_pcb"
    assert data.get("sch001_kicad_sch_suffix") == ".kicad_sch"
    assert data.get("sch001_kicad_pro_suffix") == ".kicad_pro"
    assert data.get("lib002_bom_csv_suffix") == ".csv"
    assert data.get("str002_rule_check_module") == "openhac.compiler.rule_check"
    assert data.get("str002_layout_gen_module") == "openhac.compiler.layout_gen"
    assert data.get("str002_autoroute_module") == "openhac.compiler.autoroute_cli"
    assert data.get("str002_kicad_sch_erc_module") == "openhac.compiler.kicad_sch_erc"
    assert data.get("str002_schematic_gen_module") == "openhac.compiler.schematic_gen"
    assert data.get("str002_spice_gen_module") == "openhac.compiler.spice_gen"
    assert data.get("str002_project_gen_module") == "openhac.compiler.project_gen"
    assert data.get("str002_compile_state_dataclass") == "openhac.compiler.compile_pipeline.CompileState"
    assert data.get("str002_manifest_json_suffix") == ".openhac-manifest.json"
    assert data.get("str002_manifest_sha256_sidecar_suffix") == ".openhac-manifest.json.sha256"
    assert data.get("sim002_spice_netlist_suffix") == ".cir"
    assert data.get("str002_kicad_erc_report_module") == "openhac.compiler.kicad_erc_report"
    assert data.get("str002_layout_constraints_module") == "openhac.compiler.layout_constraints"
    assert data.get("str002_pcb_placement_module") == "openhac.compiler.pcb_placement"
    assert data.get("mfg001_export_fab_module") == "openhac.compiler.export_fab"
    assert data.get("str002_compile_manifest_module") == "openhac.compiler.compile_manifest"
    assert data.get("str002_version_info_module") == "openhac.version_info"
    assert data.get("sw005_circuit_public_module") == "openhac.circuit"
    assert data.get("sim002_resolve_spice_analysis_function") == (
        "openhac.compiler.spice_analysis_config.resolve_spice_analysis_from_mapping"
    )
    assert data.get("sch001_kicad_sym_pinpos_module") == "openhac.compiler.kicad_sym_pinpos"
    assert data.get("sch001_pinpos_report_schema") == "openhac.sch_pinpos_report.v1"
    assert data.get("sch001_pinpos_report_suffix") == ".openhac-sch-pinpos-report.json"
    assert data.get("sch001_pinpos_report_writer") == "openhac.compiler.schematic_gen.generate_schematic"
    bcat = data.get("pwr002_stdlib_helpers_catalog") or []
    assert "buck_input_current_ma" in bcat
    assert "jlc" in (data.get("fab_profiles_catalog") or [])
    assert len(data.get("fab_profiles_catalog") or []) >= 4
    assert data.get("sim001_spice_database_fields") == ["spice_include", "spice_subckt"]
    assert data.get("sch003_schematic_erc_cli") == "kicad-cli sch erc"
    assert data.get("sig001_stackup_template_reference") == "docs/stackup_template.yaml"
    assert data.get("lib003_jit_bom_columns") == ["OpenHaC_JIT_Confidence", "OpenHaC_JIT_Score"]
    assert isinstance(data.get("release_bundle_suffixes"), list)
    phases = data.get("compile_pipeline_phases") or []
    assert phases and phases[0] == "phase_warn_multilayer_stackup"
    assert phases[-1] == "phase_release_zip"
    assert data.get("compile_pipeline_phase_count") == len(phases)
    assert data.get("sch_pin_sort_mode") == "alphanumeric_natural"
    cef = data.get("compile_env_flags") or {}
    assert isinstance(cef, dict) and "openhac_skip_layout" in cef
    assert "openhac_require_verified_parts" in cef
    assert data.get("pcb_routing_handoff_schema") == "openhac.pcb_routing_handoff.v1"
    assert any(s.endswith(".net") for s in data["release_bundle_suffixes"])
    assert all(r["JLC_Class"] == "Extended" for r in r_rows)
    for o in data["outputs"]:
        assert len(o["sha256"]) == 64
        assert int(o["bytes"]) >= 1
    assert data.get("git_commit") is None or len(data["git_commit"]) == 40
    be = data.get("build_environment") or {}
    assert be.get("python_version")
    assert be.get("platform")
    assert be.get("python_executable")
    src = data["source_input"]
    assert src["path"] == str(design_py.resolve())
    assert len(src["sha256"]) == 64
    assert int(src["bytes"]) >= 1
    assert src.get("line_count") == 1
    cs = data.get("compile_strictness") or {}
    assert cs.get("strict_jit_lookups") is False
    jlc = data.get("jlc_assembly_line_summary") or {}
    assert jlc.get("extended_line_items") == 2
    assert jlc.get("unset_line_items") == 2  # e.g. PWR_FLAG symbols without JLC_Class
    assert jlc.get("total_line_items") == 4
    assert jlc.get("by_class") == {"extended": 2, "unset": 2}
    sch = data.get("schematic_hierarchy_handoff") or {}
    assert sch.get("logical_module_count") == 2
    assert "flat .kicad_sch" in sch.get("note", "")
    assert data.get("logical_module_reference_total") == 2
    assert data.get("compile_manifest_emitter") == "openhac.compiler.compile_manifest.write_compile_manifest"
    assert data.get("compile_pipeline_module") == "openhac.compiler.compile_pipeline"
    assert data.get("str002_cli_module") == "openhac.cli"
    assert data.get("sch005_erc_rules_module") == "openhac.stdlib.erc_rules"
    assert data.get("sw006_skip_layout_env_key") == "OPENHAC_SKIP_LAYOUT"
    assert data.get("lib001_bom_offer_column_names") == [
        "Ranked_Offers",
        "Primary_Offer",
        "Secondary_Offer",
        "Offer_Count",
    ]
    assert data.get("lib004_bom_prod_omitted_column_count") == len(BOM_PROFILE_PROD_OMITTED_COLUMNS)
    bcols = data.get("bom_csv_column_names") or []
    assert "Reference" in bcols and "Offer_Count" in bcols
    assert data.get("pcb_routing_handoff_writer") == (
        "openhac.compiler.compile_manifest._write_pcb_routing_handoff_json"
    )
    assert data.get("sig005_length_match_constraints_writer") == (
        "openhac.compiler.compile_manifest._write_length_match_constraints_json"
    )
    assert data.get("sig006_mixed_signal_handoff_writer") == (
        "openhac.compiler.compile_manifest._write_mixed_signal_constraints_json"
    )
    assert data.get("sig002_diff_pair_constraints_writer") == (
        "openhac.compiler.compile_manifest._write_diff_pair_constraints_json"
    )
    assert data.get("pcb007_no_autoroute_constraints_writer") == (
        "openhac.compiler.compile_manifest._write_no_autoroute_constraints_json"
    )
    assert data.get("pcb_auxiliary_handoff_writer") == (
        "openhac.compiler.compile_manifest._write_pcb_auxiliary_constraints_json"
    )
    assert data.get("sch004_power_rail_handoff_writer") == (
        "openhac.compiler.compile_manifest._write_power_rail_handoff_json"
    )
    assert data.get("mfg003_fab_handoff_markdown_suffix") == ".openhac-fab-handoff.md"
    assert "netclasses" in (data.get("sig002_diff_pair_intent_disclaimer") or "").lower()
    assert "PCB-009" in (data.get("pcb009_copper_pour_handoff_note") or "")
    assert "PCB-010" in (data.get("pcb010_mounting_hole_handoff_note") or "")
    relcat = data.get("rel001_reliability_policy_key_catalog") or []
    assert "require_passive_voltage_ratings" in relcat
    assert "ambient_operating_temp_c" in relcat
    assert "cap_voltage_rating_reference_temp_c" in relcat
    assert "cap_voltage_temp_derating_percent_per_c" in relcat
    assert "test_point_min_count_by_net" in relcat
    assert "default transient" in (data.get("sim002_default_analysis_note") or "").lower()
    assert data.get("sch005_erc_rule_packs_module") == "openhac.stdlib.erc_rule_packs"
    assert data.get("sim002_spice_config_file_suffixes") == [".json", ".yaml", ".yml"]
    assert data.get("str002_core_board_module") == "openhac.core.board"
    assert data.get("str002_core_base_module") == "openhac.core.base"
    assert data.get("str002_core_compile_context_module") == "openhac.core.compile_context"
    assert data.get("pwr002_stdlib_power_module") == "openhac.stdlib.power"
    assert data.get("lib003_database_api_fallback_module") == "openhac.database.api_fallback"
    assert data.get("str002_compile_pipeline_default_phases_symbol") == (
        "openhac.compiler.compile_pipeline.DEFAULT_COMPILE_PHASES"
    )
    assert data.get("str002_openhac_version_info_function") == "openhac.version_info.get_version"
    assert data.get("str002_openhac_user_agent_function") == "openhac.version_info.user_agent"
    assert data.get("str002_stdlib_erc_rules_module") == "openhac.stdlib.erc_rules"
    assert data.get("str002_release_bundle_module") == "openhac.compiler.release_bundle"
    assert data.get("str002_stdlib_passives_module") == "openhac.stdlib.passives"
    assert data.get("lib003_db_manager_module") == "openhac.database.db_manager"
    assert data.get("lib003_sync_jlc_module") == "openhac.database.sync_jlc"
    assert data.get("str002_netlist_gen_generate_function") == (
        "openhac.compiler.netlist_gen.generate_logic_and_bom"
    )
    assert data.get("str002_rule_check_run_erc_function") == "openhac.compiler.rule_check.run_erc"
    assert data.get("str002_rule_check_run_drc_function") == "openhac.compiler.rule_check.run_drc"
    assert data.get("sim002_spice_presets_preset_analysis_lines_function") == (
        "openhac.compiler.spice_presets.preset_analysis_lines"
    )


def test_compile_manifest_sha256_sidecar_matches_manifest_bytes(tmp_path, seeded_resistor_db, monkeypatch):
    import hashlib

    monkeypatch.chdir(tmp_path)
    design_py = tmp_path / "design.py"
    design_py.write_text("# sidecar\n", encoding="utf-8")

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
    board = Board(size_mm=(50.0, 40.0), write_manifest_sha256_sidecar=True)
    board.add_module(a)
    board.add_module(b)
    board.connect(a.expose_interface("power"), b.expose_interface("power"))

    with patch("openhac.compiler.layout_gen.generate_layout"):
        board.compile(
            project_name="sidecar_prj",
            generate_bom=True,
            auto_route=False,
            export_schematic=False,
            source_script_path=design_py,
        )

    mf = tmp_path / "sidecar_prj.openhac-manifest.json"
    sc = tmp_path / "sidecar_prj.openhac-manifest.json.sha256"
    assert mf.is_file() and sc.is_file()
    body = mf.read_bytes()
    want = hashlib.sha256(body).hexdigest()
    assert sc.read_text(encoding="utf-8").strip() == want


def test_compile_output_dir_bundles_artifacts(tmp_path, seeded_resistor_db, monkeypatch):
    monkeypatch.chdir(tmp_path)
    design_py = tmp_path / "design.py"
    design_py.write_text("# out dir test\n", encoding="utf-8")

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
    board = Board(size_mm=(50.0, 40.0))
    board.add_module(a)
    board.add_module(b)
    board.connect(a.expose_interface("power"), b.expose_interface("power"))

    out = tmp_path / "release"
    with patch("openhac.compiler.layout_gen.generate_layout"):
        board.compile(
            project_name="bundled",
            generate_bom=True,
            auto_route=False,
            export_schematic=False,
            source_script_path=design_py,
            output_dir=out,
        )

    assert (out / "bundled.net").is_file()
    assert (out / "bundled.csv").is_file()
    mf = json.loads((out / "bundled.openhac-manifest.json").read_text(encoding="utf-8"))
    assert mf["output_directory"] == str(out.resolve())
    with (out / "bundled.csv").open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert rows
    assert "Mouser_SKU" in rows[0] and "DigiKey_SKU" in rows[0]


def test_compile_manifest_net_roles_and_length_match(tmp_path, seeded_resistor_db, monkeypatch):
    monkeypatch.chdir(tmp_path)
    design_py = tmp_path / "design.py"
    design_py.write_text("# sig metadata\n", encoding="utf-8")

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
    board = Board(size_mm=(50.0, 40.0))
    board.declare_net_role(gnd, "digital_ground")
    # Use nets that already have pins (metadata-only group for manifest handoff).
    board.register_length_match_group("demo_ddr", [vcc, gnd])
    board.add_module(a)
    board.add_module(b)
    board.connect(a.expose_interface("power"), b.expose_interface("power"))

    with patch("openhac.compiler.layout_gen.generate_layout"):
        board.compile(
            project_name="sig_meta",
            generate_bom=True,
            auto_route=False,
            export_schematic=False,
            source_script_path=design_py,
        )

    data = json.loads((tmp_path / "sig_meta.openhac-manifest.json").read_text(encoding="utf-8"))
    assert data.get("net_role_count") == 1
    assert data.get("length_match_group_names") == ["demo_ddr"]
    assert len(data.get("pcb_routing_handoff_json_sha256") or "") == 64
    assert any(x.get("role") == "digital_ground" for x in data.get("net_roles", []))
    assert any(x.get("name") == "demo_ddr" for x in data.get("length_match_groups", []))
    hint = tmp_path / "sig_meta.openhac-length-match-hint.md"
    assert hint.is_file() and "demo_ddr" in hint.read_text(encoding="utf-8")
    lmj = tmp_path / "sig_meta.openhac-length-match-constraints.json"
    assert lmj.is_file()
    lm_payload = json.loads(lmj.read_text(encoding="utf-8"))
    assert lm_payload.get("schema") == "openhac.length_match_constraints.v1"
    assert any(g.get("name") == "demo_ddr" for g in (lm_payload.get("groups") or []))
    assert data.get("sig005_length_match_constraints_schema") == "openhac.length_match_constraints.v1"
    assert data.get("sig005_length_match_constraints_suffix") == ".openhac-length-match-constraints.json"
    nc = tmp_path / "sig_meta.openhac-netclass-hint.md"
    assert nc.is_file() and "OHAC_LM_demo_ddr" in nc.read_text(encoding="utf-8")
    assert data.get("pcb007_netclass_suggestion_count") == 2
    assert data.get("pcb007_netclass_hint_markdown_suffix") == ".openhac-netclass-hint.md"
    ms = tmp_path / "sig_meta.openhac-mixed-signal-hint.md"
    assert ms.is_file() and "digital_ground" in ms.read_text(encoding="utf-8")
    msc = tmp_path / "sig_meta.openhac-mixed-signal-constraints.json"
    assert msc.is_file()
    ms_payload = json.loads(msc.read_text(encoding="utf-8"))
    assert ms_payload.get("schema") == "openhac.mixed_signal_handoff.v1"
    assert any(x.get("role") == "digital_ground" for x in (ms_payload.get("net_roles") or []))
    assert data.get("sig006_mixed_signal_handoff_schema") == "openhac.mixed_signal_handoff.v1"
    assert data.get("sig006_mixed_signal_handoff_suffix") == ".openhac-mixed-signal-constraints.json"
    rj = json.loads((tmp_path / "sig_meta.openhac-pcb-routing-handoff.json").read_text(encoding="utf-8"))
    assert rj.get("schema") == "openhac.pcb_routing_handoff.v1"
    assert rj.get("length_match_groups")
    assert any(x.get("role") == "digital_ground" for x in (rj.get("net_roles") or []))
    ncs = rj.get("netclass_suggestions") or []
    assert len(ncs) == 2
    assert any(x.get("suggested_netclass") == "OHAC_LM_demo_ddr" for x in ncs)
    assert any(x.get("suggested_netclass") == "OHAC_ROLE_digital_ground" for x in ncs)
    assert data.get("pcb007_netclass_hint_writer") == (
        "openhac.compiler.compile_manifest._write_netclass_hint_md"
    )


def test_manifest_includes_power_rails_handoff(tmp_path, seeded_resistor_db, monkeypatch):
    monkeypatch.chdir(tmp_path)
    design_py = tmp_path / "design.py"
    design_py.write_text("# power rails handoff\n", encoding="utf-8")

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
    board = Board(size_mm=(40.0, 40.0))
    board.declare_power_rail("VPP", vcc)
    board.add_module(a)
    board.add_module(b)
    board.connect(a.expose_interface("power"), b.expose_interface("power"))

    with patch("openhac.compiler.layout_gen.generate_layout"):
        board.compile(
            project_name="pwr_rails",
            generate_bom=True,
            auto_route=False,
            export_schematic=False,
            source_script_path=design_py,
        )

    mf = json.loads((tmp_path / "pwr_rails.openhac-manifest.json").read_text(encoding="utf-8"))
    assert mf.get("power_rail_count") == 1
    assert any(r.get("rail_name") == "VPP" and r.get("net") == "3V3" for r in (mf.get("power_rails") or []))
    assert mf.get("sch004_power_rail_handoff_schema") == "openhac.power_rail_handoff.v1"
    assert mf.get("sch004_power_rail_handoff_suffix") == ".openhac-power-rails.json"
    hp = tmp_path / "pwr_rails.openhac-power-rails.json"
    assert hp.is_file()
    payload = json.loads(hp.read_text(encoding="utf-8"))
    assert payload.get("schema") == "openhac.power_rail_handoff.v1"
    assert any(r.get("rail_name") == "VPP" and r.get("net") == "3V3" for r in (payload.get("power_rails") or []))


def test_manifest_includes_rail_conversions_handoff(tmp_path, seeded_resistor_db, monkeypatch):
    monkeypatch.chdir(tmp_path)
    design_py = tmp_path / "design.py"
    design_py.write_text("# rail conversions handoff\n", encoding="utf-8")

    vin, vout, gnd = Net("12V"), Net("3V3"), Net("GND")
    Part("power", "PWR_FLAG")[1] += vin
    Part("power", "PWR_FLAG")[1] += vout
    Part("power", "PWR_FLAG")[1] += gnd

    class Node(Module):
        def __init__(self, name: str):
            super().__init__(name)
            r0 = self.add(Component("R_10k_0805"))
            r0["1"] += vin
            r0["2"] += gnd
            r = self.add(Component("R_10k_0805"))
            r["1"] += vout
            r["2"] += gnd
            self.declare_interface("power", vout, gnd)

    a, b = Node("A"), Node("B")
    board = Board(size_mm=(40.0, 40.0), declared_supply_voltages_v={"12V": 12.0, "3V3": 3.3})
    board.declare_rail_conversion("12V", "3V3", efficiency=0.9)
    board.add_module(a)
    board.add_module(b)
    board.connect(a.expose_interface("power"), b.expose_interface("power"))

    with patch("openhac.compiler.layout_gen.generate_layout"):
        board.compile(
            project_name="rail_conv",
            generate_bom=True,
            auto_route=False,
            export_schematic=False,
            source_script_path=design_py,
        )

    mf = json.loads((tmp_path / "rail_conv.openhac-manifest.json").read_text(encoding="utf-8"))
    assert mf.get("pwr002_rail_conversions_handoff_schema") == "openhac.rail_conversions_handoff.v1"
    assert mf.get("pwr002_rail_conversions_handoff_suffix") == ".openhac-rail-conversions.json"
    assert mf.get("pwr002_rail_conversions_handoff_writer") == (
        "openhac.compiler.compile_manifest._write_rail_conversion_handoff_json"
    )

    hp = tmp_path / "rail_conv.openhac-rail-conversions.json"
    assert hp.is_file()
    payload = json.loads(hp.read_text(encoding="utf-8"))
    assert payload.get("schema") == "openhac.rail_conversions_handoff.v1"
    assert any(
        c.get("input_rail") == "12V" and c.get("output_rail") == "3V3" and float(c.get("efficiency")) == 0.9
        for c in (payload.get("rail_conversions") or [])
    )
    dsv = payload.get("declared_supply_voltages_v") or {}
    assert float(dsv.get("12V")) == 12.0
    assert float(dsv.get("3V3")) == 3.3


def test_manifest_includes_unverified_parts_handoff_when_present(tmp_path, seeded_resistor_db, monkeypatch):
    monkeypatch.chdir(tmp_path)
    design_py = tmp_path / "design.py"
    design_py.write_text("# unverified parts handoff\n", encoding="utf-8")

    vcc, gnd = Net("3V3"), Net("GND")
    Part("power", "PWR_FLAG")[1] += vcc
    Part("power", "PWR_FLAG")[1] += gnd

    from openhac.core.base import Component
    from openhac.core.board import Board
    from openhac.database.lookup_meta import CONFIDENCE_MEDIUM, LOOKUP_CONFIDENCE_KEY

    data = {
        "generic_name": "JIT_MED2",
        "kicad_symbol": "Device:R",
        "kicad_footprint": "Resistor_SMD:R_0805_2012Metric",
        "manufacturer": "",
        "mpn": "X",
        "supplier_sku": "",
        "description": "",
        "category": "resistors",
        LOOKUP_CONFIDENCE_KEY: CONFIDENCE_MEDIUM,
    }
    r = Component("JIT_MED2", comp_data=data)
    r["1"] += vcc
    r["2"] += gnd

    board = Board(size_mm=(10.0, 10.0))
    with patch("openhac.compiler.layout_gen.generate_layout"):
        board.compile(
            project_name="uvp",
            generate_bom=True,
            auto_route=False,
            export_schematic=False,
            source_script_path=design_py,
        )

    mf = json.loads((tmp_path / "uvp.openhac-manifest.json").read_text(encoding="utf-8"))
    assert mf.get("lib003_unverified_parts_schema") == "openhac.unverified_parts.v1"
    assert mf.get("lib003_unverified_parts_suffix") == ".openhac-unverified-parts.json"
    hp = tmp_path / "uvp.openhac-unverified-parts.json"
    assert hp.is_file()
    payload = json.loads(hp.read_text(encoding="utf-8"))
    assert payload.get("schema_ref") == "openhac.unverified_parts.v1"
    assert any(p.get("jit_confidence") == "medium" for p in (payload.get("unverified_parts") or []))


def test_manifest_includes_diff_pair_intent(tmp_path, seeded_resistor_db, monkeypatch):
    monkeypatch.chdir(tmp_path)
    design_py = tmp_path / "design.py"
    design_py.write_text("# diff pair manifest\n", encoding="utf-8")

    vcc, gnd = Net("3V3"), Net("GND")
    Part("power", "PWR_FLAG")[1] += vcc
    Part("power", "PWR_FLAG")[1] += gnd

    class Node(Module):
        def __init__(self, name: str):
            super().__init__(name)
            self.dp_p = Net("DP_P")
            self.dp_n = Net("DP_N")
            for n in (self.dp_p, self.dp_n):
                r = self.add(Component("R_10k_0805"))
                r["1"] += n
                r["2"] += gnd
                r2 = self.add(Component("R_10k_0805"))
                r2["1"] += n
                r2["2"] += vcc
            r0 = self.add(Component("R_10k_0805"))
            r0["1"] += vcc
            r0["2"] += gnd
            self.declare_interface("power", vcc, gnd)

    a, b = Node("A"), Node("B")
    board = Board(size_mm=(50.0, 40.0))
    board.route_differential_pair(a.dp_p, a.dp_n, 95.0)
    board.add_module(a)
    board.add_module(b)
    board.connect(a.expose_interface("power"), b.expose_interface("power"))

    with patch("openhac.compiler.layout_gen.generate_layout"):
        board.compile(
            project_name="dp_manifest",
            generate_bom=False,
            auto_route=False,
            export_schematic=False,
            source_script_path=design_py,
        )

    data = json.loads((tmp_path / "dp_manifest.openhac-manifest.json").read_text(encoding="utf-8"))
    assert data.get("diff_pair_intent_count") == 1
    dps = data.get("diff_pair_intent") or []
    assert len(dps) == 1
    assert dps[0]["p_net"].startswith("DP_P")
    assert dps[0]["n_net"].startswith("DP_N")
    assert dps[0]["target_z0_ohms"] == 95.0
    dpc = tmp_path / "dp_manifest.openhac-diff-pair-constraints.json"
    assert dpc.is_file()
    dp_payload = json.loads(dpc.read_text(encoding="utf-8"))
    assert dp_payload.get("schema") == "openhac.diff_pair_handoff.v1"
    assert (dp_payload.get("pairs") or []) == dps
    assert data.get("sig002_diff_pair_constraints_schema") == "openhac.diff_pair_handoff.v1"
    assert data.get("sig002_diff_pair_constraints_suffix") == ".openhac-diff-pair-constraints.json"
    si = tmp_path / "dp_manifest.openhac-si-stackup-reminder.md"
    assert si.is_file() and "differential" in si.read_text(encoding="utf-8").lower()
    nc = tmp_path / "dp_manifest.openhac-netclass-hint.md"
    assert nc.is_file() and "OHAC_DP_" in nc.read_text(encoding="utf-8")
    rj = json.loads((tmp_path / "dp_manifest.openhac-pcb-routing-handoff.json").read_text(encoding="utf-8"))
    dps_nc = [x for x in (rj.get("netclass_suggestions") or []) if x.get("source") == "diff_pair"]
    assert len(dps_nc) == 1
    assert dps_nc[0].get("nets") and "DP_P" in dps_nc[0]["nets"][0]


def test_compile_skips_freerouting_when_no_autoroute_net_declared(
    tmp_path, seeded_resistor_db, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    design_py = tmp_path / "design.py"
    design_py.write_text("# pcb007 skip autoroute\n", encoding="utf-8")

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
    board = Board(size_mm=(50.0, 40.0))
    board.declare_no_autoroute_net(vcc)
    board.add_module(a)
    board.add_module(b)
    board.connect(a.expose_interface("power"), b.expose_interface("power"))

    with patch("openhac.compiler.layout_gen.generate_layout"):
        with patch("openhac.compiler.autoroute_cli.run_freerouting") as mock_ar:
            board.compile(
                project_name="skip_ar",
                generate_bom=True,
                auto_route=True,
                export_schematic=False,
                source_script_path=design_py,
            )
    mock_ar.assert_not_called()
    mf = json.loads((tmp_path / "skip_ar.openhac-manifest.json").read_text(encoding="utf-8"))
    assert mf.get("no_autoroute_net_count") == 1
    nar_path = tmp_path / "skip_ar.openhac-no-autoroute-constraints.json"
    assert nar_path.is_file()
    nar_payload = json.loads(nar_path.read_text(encoding="utf-8"))
    assert nar_payload.get("schema") == "openhac.no_autoroute_handoff.v1"
    assert nar_payload.get("nets") == ["3V3"]
    assert mf.get("pcb007_no_autoroute_constraints_schema") == "openhac.no_autoroute_handoff.v1"
    assert mf.get("pcb007_no_autoroute_constraints_suffix") == ".openhac-no-autoroute-constraints.json"


def test_bom_lists_alternate_skus_from_db(tmp_path, tmp_db, monkeypatch):
    _, dm = tmp_db
    dm.insert_component(
        {
            "generic_name": "R_10k_0805",
            "kicad_symbol": "Device:R",
            "kicad_footprint": "Resistor_SMD:R_0805_2012Metric",
            "manufacturer": "Yageo",
            "mpn": "RC0805FR-0710KL",
            "supplier_sku": "C17513",
            "description": "",
            "jlc_class": "Basic",
        }
    )
    dm.insert_part_alternate(
        {
            "primary_generic": "R_10k_0805",
            "rank": 1,
            "alternate_mpn": "ALTMPN",
            "alternate_supplier_sku": "C99999",
            "note": "approved alternate",
            "alternate_group_id": "ALTGRP1",
        }
    )
    monkeypatch.setattr(Component, "db", dm)
    monkeypatch.chdir(tmp_path)
    design_py = tmp_path / "design.py"
    design_py.write_text("# alt bom\n", encoding="utf-8")

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
    board = Board(size_mm=(40.0, 40.0))
    board.add_module(a)
    board.add_module(b)
    board.connect(a.expose_interface("power"), b.expose_interface("power"))

    with patch("openhac.compiler.layout_gen.generate_layout"):
        board.compile(
            project_name="alt_bom",
            generate_bom=True,
            auto_route=False,
            export_schematic=False,
            source_script_path=design_py,
        )

    with (tmp_path / "alt_bom.csv").open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    r_rows = [r for r in rows if r.get("Reference", "").startswith("R")]
    assert r_rows
    assert "C99999" in r_rows[0].get("Alternate_SKUs", "")
    assert "approved alternate" in r_rows[0].get("Alternate_Notes", "")
    assert r_rows[0].get("Alternate_Group_ID") == "ALTGRP1"
    assert r_rows[0].get("Alternate_Count") == "1"
    altj = tmp_path / "alt_bom.openhac-bom-alternates.json"
    assert altj.is_file()
    aj = json.loads(altj.read_text(encoding="utf-8"))
    assert aj.get("schema") == "openhac.bom_alternates.v1"
    assert "R_10k_0805" in (aj.get("by_generic") or {})
    mf = json.loads((tmp_path / "alt_bom.openhac-manifest.json").read_text(encoding="utf-8"))
    assert mf.get("bom_alternates_generic_count") >= 1
    assert mf.get("bom_alternates_total_rows") >= 1
    bah = mf.get("bom_alternates_handoff") or {}
    assert bah.get("alternates_json") == "alt_bom.openhac-bom-alternates.json"
    assert bah.get("expand_hint_markdown") == "alt_bom.openhac-bom-expand-hint.md"
    hint_md = (tmp_path / "alt_bom.openhac-bom-expand-hint.md").read_text(encoding="utf-8")
    assert "CM workflows" in hint_md


def test_manifest_includes_fab_profile_geometry_keys(tmp_path, seeded_resistor_db, monkeypatch):
    """MFG-004: manifest lists top-level keys from fab profile JSON when fab_profile is set."""
    monkeypatch.chdir(tmp_path)
    design_py = tmp_path / "design.py"
    design_py.write_text("# fab prof manifest\n", encoding="utf-8")

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
    board = Board(size_mm=(40.0, 40.0), fab_profile="jlc")
    board.add_module(a)
    board.add_module(b)
    board.connect(a.expose_interface("power"), b.expose_interface("power"))

    with patch("openhac.compiler.layout_gen.generate_layout"):
        board.compile(
            project_name="fabmf",
            generate_bom=True,
            auto_route=False,
            export_schematic=False,
            source_script_path=design_py,
        )

    data = json.loads((tmp_path / "fabmf.openhac-manifest.json").read_text(encoding="utf-8"))
    keys = data.get("fab_profile_geometry_keys") or []
    assert "min_trace_width_mm" in keys
    assert "comment" in keys
    fpjp = data.get("fab_profile_json_path") or ""
    assert "jlc.json" in fpjp


def test_manifest_includes_git_describe_when_git_reports(tmp_path, seeded_resistor_db, monkeypatch):
    """STR-002: optional git_describe from git describe --always --dirty."""
    monkeypatch.chdir(tmp_path)
    design_py = tmp_path / "design.py"
    design_py.write_text("# git describe manifest\n", encoding="utf-8")

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
    board = Board(size_mm=(40.0, 40.0))
    board.add_module(a)
    board.add_module(b)
    board.connect(a.expose_interface("power"), b.expose_interface("power"))

    with patch("openhac.compiler.layout_gen.generate_layout"):
        with patch(
            "openhac.compiler.compile_manifest._try_git_describe",
            return_value="v0.0-test-1-gabc1234-dirty",
        ):
            board.compile(
                project_name="gdesc",
                generate_bom=True,
                auto_route=False,
                export_schematic=False,
                source_script_path=design_py,
            )

    data = json.loads((tmp_path / "gdesc.openhac-manifest.json").read_text(encoding="utf-8"))
    assert data.get("git_describe") == "v0.0-test-1-gabc1234-dirty"


def test_bom_profile_prod_omits_internal_columns(tmp_path, tmp_db, monkeypatch):
    """LIB-004: prod BOM profile strips OpenHaC / alternate-expansion columns."""
    from openhac.compiler.netlist_gen import BOM_PROFILE_PROD_OMITTED_COLUMNS

    _, dm = tmp_db
    dm.insert_component(
        {
            "generic_name": "R_10k_0805",
            "kicad_symbol": "Device:R",
            "kicad_footprint": "Resistor_SMD:R_0805_2012Metric",
            "manufacturer": "Yageo",
            "mpn": "RC0805FR-0710KL",
            "supplier_sku": "C17513",
            "description": "",
            "jlc_class": "Basic",
        }
    )
    monkeypatch.setattr(Component, "db", dm)
    monkeypatch.chdir(tmp_path)
    design_py = tmp_path / "design.py"
    design_py.write_text("# prod bom\n", encoding="utf-8")

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
    board = Board(size_mm=(40.0, 40.0), bom_profile="prod")
    board.add_module(a)
    board.add_module(b)
    board.connect(a.expose_interface("power"), b.expose_interface("power"))

    with patch("openhac.compiler.layout_gen.generate_layout"):
        board.compile(
            project_name="prod_bom",
            generate_bom=True,
            auto_route=False,
            export_schematic=False,
            source_script_path=design_py,
        )

    with (tmp_path / "prod_bom.csv").open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    hdr = rows[0]
    for col in BOM_PROFILE_PROD_OMITTED_COLUMNS:
        assert col not in hdr
    assert "Reference" in hdr and "MPN" in hdr and "Footprint" in hdr
    mf = json.loads((tmp_path / "prod_bom.openhac-manifest.json").read_text(encoding="utf-8"))
    assert mf.get("bom_profile") == "prod"
    assert mf.get("lib004_prod_bom_profile_active") is True
    assert set(mf.get("bom_prod_omitted_columns") or []) == set(BOM_PROFILE_PROD_OMITTED_COLUMNS)


def test_manifest_includes_pcb_pour_mount_and_dfm_refs(tmp_path, seeded_resistor_db, monkeypatch):
    """PCB-009/010 + MFG-004 dfm refs appear in manifest + routing handoff JSON."""
    monkeypatch.chdir(tmp_path)
    design_py = tmp_path / "design.py"
    design_py.write_text("# pour mount dfm\n", encoding="utf-8")

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
    board = Board(size_mm=(40.0, 40.0))
    board.declare_copper_pour_intent(gnd, layer="B.Cu", purpose="ground")
    board.declare_mounting_hole(2.5, 2.5, 2.2, note="M2.5")
    dfm = tmp_path / "dfm.txt"
    dfm.write_text("checklist\n", encoding="utf-8")
    board.declare_dfm_reference(dfm, role="cm_dfm", documentation_note="run before fab")
    board.add_module(a)
    board.add_module(b)
    board.connect(a.expose_interface("power"), b.expose_interface("power"))

    with patch("openhac.compiler.layout_gen.generate_layout"):
        board.compile(
            project_name="mech_meta",
            generate_bom=True,
            auto_route=False,
            export_schematic=False,
            source_script_path=design_py,
        )

    mf = json.loads((tmp_path / "mech_meta.openhac-manifest.json").read_text(encoding="utf-8"))
    assert len(mf.get("copper_pour_intents") or []) == 1
    assert len(mf.get("mounting_hole_intents") or []) == 1
    assert (mf.get("dfm_references") or [{}])[0].get("role") == "cm_dfm"
    aux = tmp_path / "mech_meta.openhac-pcb-auxiliary-constraints.json"
    assert aux.is_file()
    aux_payload = json.loads(aux.read_text(encoding="utf-8"))
    assert aux_payload.get("schema") == "openhac.pcb_auxiliary_handoff.v1"
    assert len(aux_payload.get("copper_pour_intents") or []) == 1
    assert len(aux_payload.get("mounting_hole_intents") or []) == 1
    assert mf.get("pcb_auxiliary_handoff_schema") == "openhac.pcb_auxiliary_handoff.v1"
    assert mf.get("pcb_auxiliary_handoff_suffix") == ".openhac-pcb-auxiliary-constraints.json"
    rj = json.loads((tmp_path / "mech_meta.openhac-pcb-routing-handoff.json").read_text(encoding="utf-8"))
    assert rj.get("copper_pour_intents")
    assert rj.get("mounting_hole_intents")


def test_compile_release_zip_contains_artifacts(tmp_path, seeded_resistor_db, monkeypatch):
    monkeypatch.chdir(tmp_path)
    design_py = tmp_path / "design.py"
    design_py.write_text("# zip release\n", encoding="utf-8")

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
    board = Board(size_mm=(44.0, 44.0))
    stack_json = tmp_path / "zprj_stack.json"
    stack_json.write_text("{}", encoding="utf-8")
    board.declare_stackup_reference(stack_json, role="ci_fixture")
    board.register_length_match_group("zip_lmg", [vcc, gnd])
    board.add_module(a)
    board.add_module(b)
    board.connect(a.expose_interface("power"), b.expose_interface("power"))

    zpath = tmp_path / "rel.zip"
    board.write_manifest_sha256_sidecar = True
    with patch("openhac.compiler.layout_gen.generate_layout"):
        board.compile(
            project_name="zprj",
            generate_bom=True,
            auto_route=False,
            export_schematic=False,
            source_script_path=design_py,
            release_zip_path=str(zpath),
        )

    assert zpath.is_file()
    zmf = json.loads((tmp_path / "zprj.openhac-manifest.json").read_text(encoding="utf-8"))
    assert len(zmf.get("release_zip_sha256") or "") == 64
    with zipfile.ZipFile(zpath, "r") as zf:
        names = set(zf.namelist())
    assert "zprj.net" in names and "zprj.csv" in names
    assert any(n.endswith("openhac-manifest.json") for n in names)
    assert "zprj.openhac-manifest.json.sha256" in names
    assert "zprj.openhac-fab-handoff.md" in names
    assert "zprj.openhac-netclass-hint.md" in names
    assert "zprj.openhac-length-match-hint.md" in names
    assert "zprj.openhac-length-match-constraints.json" in names
    assert "zprj.openhac-mixed-signal-hint.md" not in names
    assert "zprj.openhac-si-stackup-reminder.md" in names
    assert "zprj.openhac-pcb-routing-handoff.json" in names


def test_compile_release_zip_is_deterministic_under_openhac_deterministic(tmp_path, seeded_resistor_db, monkeypatch):
    """MFG-005 stretch: with OPENHAC_DETERMINISTIC=1, release zip bytes are stable across runs."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENHAC_DETERMINISTIC", "1")
    design_py = tmp_path / "design.py"
    design_py.write_text("# zip deterministic\n", encoding="utf-8")

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
    board = Board(size_mm=(44.0, 44.0))
    board.add_module(a)
    board.add_module(b)
    board.connect(a.expose_interface("power"), b.expose_interface("power"))

    zpath = tmp_path / "rel_det.zip"
    with patch("openhac.compiler.layout_gen.generate_layout"):
        board.compile(
            project_name="zdet",
            generate_bom=True,
            auto_route=False,
            export_schematic=False,
            source_script_path=design_py,
            release_zip_path=str(zpath),
        )
    b1 = zpath.read_bytes()

    # Run again to same paths; deterministic mode should yield identical zip bytes.
    with patch("openhac.compiler.layout_gen.generate_layout"):
        board.compile(
            project_name="zdet",
            generate_bom=True,
            auto_route=False,
            export_schematic=False,
            source_script_path=design_py,
            release_zip_path=str(zpath),
        )
    b2 = zpath.read_bytes()
    assert b1 == b2

    mf = json.loads((tmp_path / "zdet.openhac-manifest.json").read_text(encoding="utf-8"))
    # In deterministic mode we skip the manifest patch + second zip pass; no self-referential digest is written.
    assert mf.get("release_zip_sha256") in (None, "")


def test_manifest_release_tag_sorted_keys(tmp_path, seeded_resistor_db, monkeypatch):
    monkeypatch.chdir(tmp_path)
    design_py = tmp_path / "design.py"
    design_py.write_text("# manifest meta\n", encoding="utf-8")

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
    board = Board(size_mm=(40.0, 40.0), release_tag="v9.9.9", build_profile="test", bom_profile="prod")
    board.add_module(a)
    board.add_module(b)
    board.connect(a.expose_interface("power"), b.expose_interface("power"))

    with patch("openhac.compiler.layout_gen.generate_layout"):
        board.compile(
            project_name="mtag",
            generate_bom=True,
            auto_route=False,
            export_schematic=False,
            source_script_path=design_py,
        )

    raw = (tmp_path / "mtag.openhac-manifest.json").read_text(encoding="utf-8")
    data = json.loads(raw)
    assert data["release_tag"] == "v9.9.9"
    assert data["build_profile"] == "test"
    assert data["bom_profile"] == "prod"
    assert list(data.keys()) == sorted(data.keys())


def test_manifest_git_worktree_dirty_and_stackup_refs(tmp_path, seeded_resistor_db, monkeypatch):
    monkeypatch.chdir(tmp_path)
    design_py = tmp_path / "design.py"
    design_py.write_text("# manifest git + stackup\n", encoding="utf-8")

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
    board = Board(size_mm=(40.0, 40.0))
    board.declare_stackup_reference(
        "docs/stackup_template.yaml",
        role="sig001_handoff",
        documentation_note="Replace with CM stackup before fab",
    )
    board.add_module(a)
    board.add_module(b)
    board.connect(a.expose_interface("power"), b.expose_interface("power"))

    with patch("openhac.compiler.layout_gen.generate_layout"):
        with patch(
            "openhac.compiler.compile_manifest._try_git_worktree_dirty",
            return_value=True,
        ):
            board.compile(
                project_name="mgit",
                generate_bom=True,
                auto_route=False,
                export_schematic=False,
                source_script_path=design_py,
            )

    data = json.loads((tmp_path / "mgit.openhac-manifest.json").read_text(encoding="utf-8"))
    assert data.get("git_worktree_dirty") is True
    refs = data.get("stackup_references") or []
    assert len(refs) == 1
    assert refs[0]["path"].endswith("docs/stackup_template.yaml")
    assert refs[0]["role"] == "sig001_handoff"
    assert "CM stackup" in (refs[0].get("documentation_note") or "")
    assert data.get("pcb004_stackup_handoff_schema") == "openhac.stackup_handoff.v1"
    assert data.get("pcb004_stackup_handoff_suffix") == ".openhac-stackup-handoff.json"
    sh = tmp_path / "mgit.openhac-stackup-handoff.json"
    assert sh.is_file()
    payload = json.loads(sh.read_text(encoding="utf-8"))
    assert payload.get("schema") == "openhac.stackup_handoff.v1"
    assert payload.get("stackup_references")
    handoff = tmp_path / "mgit.openhac-fab-handoff.md"
    assert handoff.is_file()
    assert "fab_stackup_table" in handoff.read_text(encoding="utf-8")
    assert "CM stackup" in handoff.read_text(encoding="utf-8")
    assert (tmp_path / "mgit.openhac-si-stackup-reminder.md").is_file()


def test_manifest_includes_net_merge_hints(tmp_path, seeded_resistor_db, monkeypatch):
    monkeypatch.chdir(tmp_path)
    design_py = tmp_path / "design.py"
    design_py.write_text("# merge hints\n", encoding="utf-8")

    vcc, gnd = Net("3V3"), Net("GND")
    agnd, dgnd = Net("AGND"), Net("DGND")
    Part("power", "PWR_FLAG")[1] += vcc
    Part("power", "PWR_FLAG")[1] += gnd
    # Anchor AGND/DGND (≥2 pins each) so ERC passes; merge hint is manifest-only.
    for net in (agnd, dgnd):
        b1 = Component("R_10k_0805")
        b1["1"] += net
        b1["2"] += gnd
        b2 = Component("R_10k_0805")
        b2["1"] += net
        b2["2"] += vcc

    class Node(Module):
        def __init__(self, name: str):
            super().__init__(name)
            r = self.add(Component("R_10k_0805"))
            r["1"] += vcc
            r["2"] += gnd
            self.declare_interface("power", vcc, gnd)

    a, b = Node("A"), Node("B")
    board = Board(size_mm=(40.0, 40.0))
    board.declare_net_merge_hint(agnd, dgnd, "ferrite_bead_at_FB1")
    board.add_module(a)
    board.add_module(b)
    board.connect(a.expose_interface("power"), b.expose_interface("power"))

    with patch("openhac.compiler.layout_gen.generate_layout"):
        board.compile(
            project_name="merge_hint",
            generate_bom=True,
            auto_route=False,
            export_schematic=False,
            source_script_path=design_py,
        )

    data = json.loads((tmp_path / "merge_hint.openhac-manifest.json").read_text(encoding="utf-8"))
    hints = data.get("net_merge_hints") or []
    assert len(hints) == 1
    assert hints[0]["net_a"] == "AGND"
    assert hints[0]["net_b"] == "DGND"
    assert "ferrite" in hints[0]["via"]
    ms = tmp_path / "merge_hint.openhac-mixed-signal-hint.md"
    assert ms.is_file() and "AGND" in ms.read_text(encoding="utf-8")
    msc = tmp_path / "merge_hint.openhac-mixed-signal-constraints.json"
    assert msc.is_file()
    ms_payload = json.loads(msc.read_text(encoding="utf-8"))
    assert ms_payload.get("schema") == "openhac.mixed_signal_handoff.v1"
    assert (ms_payload.get("net_merge_hints") or []) == hints
    assert (ms_payload.get("net_roles") or []) == []
    assert data.get("sig006_mixed_signal_handoff_schema") == "openhac.mixed_signal_handoff.v1"
    rj = json.loads((tmp_path / "merge_hint.openhac-pcb-routing-handoff.json").read_text(encoding="utf-8"))
    assert (rj.get("net_merge_hints") or []) == hints


def test_bom_ranked_offers_from_part_offers(tmp_path, tmp_db, monkeypatch):
    _, dm = tmp_db
    dm.insert_component(
        {
            "generic_name": "R_offer_test",
            "kicad_symbol": "Device:R",
            "kicad_footprint": "Resistor_SMD:R_0805_2012Metric",
            "manufacturer": "",
            "mpn": "X",
            "supplier_sku": "C1",
            "description": "",
            "jlc_class": "Basic",
        }
    )
    dm.insert_part_offer(
        {
            "generic_name": "R_offer_test",
            "rank": 1,
            "supplier": "Mouser",
            "supplier_sku": "MOU-1",
            "mpn": "",
            "note": "",
        }
    )
    dm.insert_part_offer(
        {
            "generic_name": "R_offer_test",
            "rank": 2,
            "supplier": "DigiKey",
            "supplier_sku": "DK-2",
            "mpn": "",
            "note": "",
        }
    )
    monkeypatch.setattr(Component, "db", dm)
    monkeypatch.chdir(tmp_path)
    design_py = tmp_path / "design.py"
    design_py.write_text("# ranked offers\n", encoding="utf-8")

    vcc, gnd = Net("3V3"), Net("GND")
    Part("power", "PWR_FLAG")[1] += vcc
    Part("power", "PWR_FLAG")[1] += gnd

    class Node(Module):
        def __init__(self, name: str):
            super().__init__(name)
            r = self.add(Component("R_offer_test"))
            r["1"] += vcc
            r["2"] += gnd
            self.declare_interface("power", vcc, gnd)

    a, b = Node("A"), Node("B")
    board = Board(size_mm=(40.0, 40.0))
    board.add_module(a)
    board.add_module(b)
    board.connect(a.expose_interface("power"), b.expose_interface("power"))

    with patch("openhac.compiler.layout_gen.generate_layout"):
        board.compile(
            project_name="rank_off",
            generate_bom=True,
            auto_route=False,
            export_schematic=False,
            source_script_path=design_py,
        )

    with (tmp_path / "rank_off.csv").open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    r_rows = [r for r in rows if r.get("Reference", "").startswith("R")]
    assert r_rows
    ro = r_rows[0].get("Ranked_Offers", "")
    assert "Mouser:MOU-1" in ro and "DigiKey:DK-2" in ro
    assert r_rows[0].get("Primary_Offer") == "Mouser:MOU-1"
    assert r_rows[0].get("Secondary_Offer") == "DigiKey:DK-2"
    assert r_rows[0].get("Offer_Count") == "2"
    assert r_rows[0].get("Alternate_Count") == "0"

    mf = json.loads((tmp_path / "rank_off.openhac-manifest.json").read_text(encoding="utf-8"))
    lm = mf.get("logical_modules") or []
    assert len(lm) == 2
    names = {x["name"] for x in lm}
    assert names == {"A", "B"}
    for block in lm:
        assert any(ref.startswith("R") for ref in block.get("references", []))


def test_manifest_pcb_stackup_note_when_multilayer(tmp_path, seeded_resistor_db, monkeypatch):
    monkeypatch.chdir(tmp_path)
    design_py = tmp_path / "design.py"
    design_py.write_text("# 4L stackup note\n", encoding="utf-8")

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
    board = Board(size_mm=(40.0, 40.0), layers=4)
    board.declare_no_autoroute_net(vcc)
    board.add_module(a)
    board.add_module(b)
    board.connect(a.expose_interface("power"), b.expose_interface("power"))

    with patch("openhac.compiler.layout_gen.generate_layout"):
        board.compile(
            project_name="mlay",
            generate_bom=True,
            auto_route=False,
            export_schematic=False,
            source_script_path=design_py,
        )

    data = json.loads((tmp_path / "mlay.openhac-manifest.json").read_text(encoding="utf-8"))
    assert "pcb_stackup_layer_note" in data
    assert data["layers"] == 4
    assert data.get("no_autoroute_nets") == ["3V3"]
    si = tmp_path / "mlay.openhac-si-stackup-reminder.md"
    assert si.is_file() and "PCB-003" in si.read_text(encoding="utf-8")
