"""Integration-style compile test: netlist + BOM + manifest (SW-006)."""

from __future__ import annotations

import csv
import json
import zipfile
from unittest.mock import patch

import pytest
from skidl import Net, Part

import openhac.core  # noqa: F401
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
    assert isinstance(data.get("pcb_pipeline_handoff"), dict)
    assert isinstance(data.get("release_bundle_suffixes"), list)
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
    cs = data.get("compile_strictness") or {}
    assert cs.get("strict_jit_lookups") is False
    jlc = data.get("jlc_assembly_line_summary") or {}
    assert jlc.get("extended_line_items") == 2
    sch = data.get("schematic_hierarchy_handoff") or {}
    assert sch.get("logical_module_count") == 2
    assert "flat .kicad_sch" in sch.get("note", "")


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
    assert any(x.get("role") == "digital_ground" for x in data.get("net_roles", []))
    assert any(x.get("name") == "demo_ddr" for x in data.get("length_match_groups", []))
    hint = tmp_path / "sig_meta.openhac-length-match-hint.md"
    assert hint.is_file() and "demo_ddr" in hint.read_text(encoding="utf-8")
    ms = tmp_path / "sig_meta.openhac-mixed-signal-hint.md"
    assert ms.is_file() and "digital_ground" in ms.read_text(encoding="utf-8")
    rj = json.loads((tmp_path / "sig_meta.openhac-pcb-routing-handoff.json").read_text(encoding="utf-8"))
    assert rj.get("schema") == "openhac.pcb_routing_handoff.v1"
    assert rj.get("length_match_groups")
    assert any(x.get("role") == "digital_ground" for x in (rj.get("net_roles") or []))


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
    dps = data.get("diff_pair_intent") or []
    assert len(dps) == 1
    assert dps[0]["p_net"].startswith("DP_P")
    assert dps[0]["n_net"].startswith("DP_N")
    assert dps[0]["target_z0_ohms"] == 95.0
    si = tmp_path / "dp_manifest.openhac-si-stackup-reminder.md"
    assert si.is_file() and "differential" in si.read_text(encoding="utf-8").lower()


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
    with zipfile.ZipFile(zpath, "r") as zf:
        names = set(zf.namelist())
    assert "zprj.net" in names and "zprj.csv" in names
    assert any(n.endswith("openhac-manifest.json") for n in names)
    assert "zprj.openhac-manifest.json.sha256" in names
    assert "zprj.openhac-fab-handoff.md" in names
    assert "zprj.openhac-length-match-hint.md" in names
    assert "zprj.openhac-mixed-signal-hint.md" not in names
    assert "zprj.openhac-si-stackup-reminder.md" in names
    assert "zprj.openhac-pcb-routing-handoff.json" in names


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
