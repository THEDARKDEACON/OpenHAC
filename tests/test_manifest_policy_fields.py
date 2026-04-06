"""STR-002 / REL-001 / LIB-005 / LIB-006: manifest policy snapshots."""

from __future__ import annotations

import json
from unittest.mock import patch

import openhac.core  # noqa: F401
from skidl import Net, Part

from openhac.core import Board
from openhac.core.base import Component, Module


def test_manifest_includes_reliability_and_jlc_and_lib006_policy(tmp_path, tmp_db, monkeypatch):
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
            "category": "Resistor",
            "tolerance": "1%",
        }
    )
    monkeypatch.setattr(Component, "db", dm)
    monkeypatch.chdir(tmp_path)
    design_py = tmp_path / "design.py"
    design_py.write_text("# policy manifest\n", encoding="utf-8")

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
    board = Board(
        size_mm=(40.0, 40.0),
        require_passive_voltage_ratings=True,
        max_jlc_extended_parts=99,
        warn_jlc_extended_parts=True,
        strict_passive_catalog_fields=True,
    )
    board.add_module(a)
    board.add_module(b)
    board.connect(a.expose_interface("power"), b.expose_interface("power"))

    with patch("openhac.compiler.layout_gen.generate_layout"):
        board.compile(
            project_name="polmf",
            generate_bom=True,
            auto_route=False,
            export_schematic=False,
            source_script_path=design_py,
        )

    data = json.loads((tmp_path / "polmf.openhac-manifest.json").read_text(encoding="utf-8"))
    rp = data.get("reliability_policy") or {}
    assert rp.get("require_passive_voltage_ratings") is True
    jlc = data.get("jlc_line_policy") or {}
    assert jlc.get("max_jlc_extended_parts") == 99
    assert jlc.get("warn_jlc_extended_parts") is True
    lib6 = data.get("lib006_passive_catalog_policy") or {}
    assert lib6.get("strict_passive_catalog_fields") is True


def test_manifest_round4_traceability_fields(tmp_path, tmp_db, monkeypatch):
    """STR-002 / REL-003 / LIB-002 / MFG-001 / MFG-002 / SIM-002: hooks, nets, alternates schema, CLI hints."""
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
            "category": "Resistor",
            "tolerance": "1%",
        }
    )
    dm.insert_part_alternate(
        {
            "primary_generic": "R_10k_0805",
            "rank": 1,
            "alternate_mpn": "ALT-R-10k",
            "alternate_supplier_sku": "ALT-SKU",
            "note": "",
        }
    )
    dm.insert_component(
        {
            "generic_name": "TP_Mech_1mm",
            "kicad_symbol": "Device:R",
            "kicad_footprint": "TestPoint:TestPoint_Pad_D1.0mm",
            "manufacturer": "",
            "mpn": "TP",
            "supplier_sku": "",
            "description": "",
            "category": "testability",
        }
    )
    monkeypatch.setattr(Component, "db", dm)
    monkeypatch.chdir(tmp_path)
    design_py = tmp_path / "design.py"
    design_py.write_text("# round4 manifest\n", encoding="utf-8")

    vcc, gnd = Net("3V3"), Net("GND")
    Part("power", "PWR_FLAG")[1] += vcc
    Part("power", "PWR_FLAG")[1] += gnd

    class Leaf(Module):
        def __init__(self):
            super().__init__("leaf")
            r = self.add(Component("R_10k_0805"))
            r["1"] += vcc
            r["2"] += gnd
            tp = self.add(Component("TP_Mech_1mm"))
            tp["1"] += vcc
            tp["2"] += vcc
            self.declare_interface("power", vcc, gnd)

    class Peer(Module):
        def __init__(self):
            super().__init__("peer")
            r = self.add(Component("R_10k_0805"))
            r["1"] += vcc
            r["2"] += gnd
            self.declare_interface("power", vcc, gnd)

    a, b = Leaf(), Peer()

    def _noop_erc(_board):
        return []

    board = Board(
        size_mm=(40.0, 40.0),
        strict_passive_catalog_fields=True,
        require_test_point_on_nets=("3V3",),
        test_point_min_count_by_net={"3V3": 1},
    )
    board.register_erc_hook(_noop_erc)
    board.register_erc_hook(_noop_erc)
    board.add_module(a)
    board.add_module(b)
    board.connect(a.expose_interface("power"), b.expose_interface("power"))

    with patch("openhac.compiler.layout_gen.generate_layout"):
        board.compile(
            project_name="r4mf",
            generate_bom=True,
            auto_route=False,
            export_schematic=False,
            source_script_path=design_py,
        )

    data = json.loads((tmp_path / "r4mf.openhac-manifest.json").read_text(encoding="utf-8"))
    assert data.get("erc_plugin_hook_count") == 2
    assert data.get("rel003_test_point_net_names") == ["3v3"]
    assert data.get("rel003_test_point_min_count_by_net") == {"3v3": 1}
    assert (data.get("reliability_policy") or {}).get("test_point_min_count_by_net") == {"3v3": 1}
    assert data.get("bom_alternates_schema") == "openhac.bom_alternates.v1"
    assert data.get("mfg001_fab_export_cli") == "kicad-cli pcb export gerbers"
    assert data.get("mfg002_assembly_export_cli") == "kicad-cli pcb export pos"
    sf = data.get("sim002_spice_cli_flags") or {}
    assert sf.get("spice_line") == "--spice-line"
    assert sf.get("spice_preset") == "--spice-preset"
    assert sf.get("spice_analysis_json") == "--spice-analysis-json"


def test_manifest_jlc_line_policy_includes_per_class_limits(tmp_path, tmp_db, monkeypatch):
    _, dm = tmp_db
    dm.insert_component(
        {
            "generic_name": "R_10k_0805",
            "kicad_symbol": "Device:R",
            "kicad_footprint": "Resistor_SMD:R_0805_2012Metric",
            "manufacturer": "",
            "mpn": "X",
            "description": "",
            "jlc_class": "Basic",
            "category": "Resistor",
            "tolerance": "1%",
        }
    )
    monkeypatch.setattr(Component, "db", dm)
    monkeypatch.chdir(tmp_path)
    design_py = tmp_path / "design.py"
    design_py.write_text("# jlc per-class policy\n", encoding="utf-8")

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
    board = Board(
        size_mm=(40.0, 40.0),
        jlc_class_line_limits={"extended": 5, "unset": 10},
    )
    board.add_module(a)
    board.add_module(b)
    board.connect(a.expose_interface("power"), b.expose_interface("power"))

    with patch("openhac.compiler.layout_gen.generate_layout"):
        board.compile(
            project_name="jlc_perclass",
            generate_bom=True,
            auto_route=False,
            export_schematic=False,
            source_script_path=design_py,
        )

    data = json.loads((tmp_path / "jlc_perclass.openhac-manifest.json").read_text(encoding="utf-8"))
    jlc = data.get("jlc_line_policy") or {}
    assert jlc.get("jlc_class_line_limits") == {"extended": 5, "unset": 10}
