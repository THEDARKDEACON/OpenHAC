"""SCH-001: deterministic KiCad .kicad_pro generation."""

from __future__ import annotations

import json

from openhac.compiler.project_gen import generate_project_file, restore_kicad_pro_net_settings
from openhac.core.board import Board


def test_generate_project_file_is_deterministic(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    p = tmp_path / "proj.kicad_pro"
    generate_project_file(str(p))
    t1 = p.read_text(encoding="utf-8")
    generate_project_file(str(p))
    t2 = p.read_text(encoding="utf-8")
    assert t1 == t2
    data = json.loads(t1)
    assert data.get("meta", {}).get("version") == 3
    ns = data["net_settings"]
    assert ns["netclass_assignments"] is None
    assert ns["meta"]["version"] == 4
    names = [c["name"] for c in ns["classes"]]
    assert names[0] == "Default"
    assert "priority" in ns["classes"][0]
    assert "bus_width" in ns["classes"][0]
    from openhac.schematic.kicad_links import ROOT_SHEET_TITLE, root_schematic_uuid

    assert data["sheets"] == [[root_schematic_uuid(), ROOT_SHEET_TITLE]]


def test_generate_project_file_kicad9_net_settings_from_board(tmp_path):
    p = tmp_path / "board.kicad_pro"
    b = Board((40, 30))
    b.set_net_current("GND", 2.0)
    b.set_net_current("VIN_24V", 2.0)
    b._diff_pair_intents.append({"net_p": "USB_DP", "net_n": "USB_DM", "z0_ohm": 90})
    b.declare_length_match_intent("usb", "USB_DP", "USB_DM", tolerance_mm=0.15)
    generate_project_file(str(p), board=b)

    data = json.loads(p.read_text(encoding="utf-8"))
    ns = data["net_settings"]
    assert ns["netclass_assignments"] is None
    names = {c["name"] for c in ns["classes"]}
    assert "Power_2A" in names
    assert "DiffPair_90ohm" in names
    patterns = {(r["pattern"], r["netclass"]) for r in ns["netclass_patterns"]}
    assert ("GND", "Power_2A") in patterns
    assert ("VIN_24V", "Power_2A") in patterns
    assert ("USB_DP", "DiffPair_90ohm") in patterns
    gnd_cls = next(c for c in ns["classes"] if c["name"] == "Power_2A")
    assert gnd_cls["track_width"] > 0.2
    assert 0.0 in data["board"]["design_settings"]["track_widths"]
    assert gnd_cls["track_width"] in data["board"]["design_settings"]["track_widths"]

    sidecar = tmp_path / "board.openhac-netclasses.json"
    side = json.loads(sidecar.read_text(encoding="utf-8"))
    assert side["widths_mm"]["GND"] == gnd_cls["track_width"]

    dru = (tmp_path / "board.kicad_dru").read_text(encoding="utf-8")
    assert "A.NetClass == 'Power_2A'" in dru
    assert "constraint skew" in dru


def test_generate_project_file_writes_sheet_uuids_from_ir(tmp_path):
    from openhac.schematic.ir import SheetBox
    from openhac.schematic.kicad_links import ROOT_SHEET_TITLE, root_schematic_uuid, sheet_instance_uuid

    p = tmp_path / "board.kicad_pro"
    ir = type("IR", (), {})()
    ir.sheets = [
        SheetBox(
            name="COMPUTE",
            filename="board.COMPUTE.kicad_sch",
            x=0,
            y=0,
            w=10,
            h=10,
            uuid=sheet_instance_uuid("COMPUTE"),
        )
    ]
    generate_project_file(str(p), schematic_ir=ir)
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["sheets"][0] == [root_schematic_uuid(), ROOT_SHEET_TITLE]
    assert data["sheets"][1] == [sheet_instance_uuid("COMPUTE"), "COMPUTE"]


def test_restore_net_settings_after_kicad_flatten(tmp_path):
    p = tmp_path / "board.kicad_pro"
    b = Board((40, 30))
    b.set_net_current("GND", 2.0)
    generate_project_file(str(p), board=b)
    # Simulate KiCad 9 File → Save rewriting Default-only net_settings.
    p.write_text(
        json.dumps(
            {
                "meta": {"filename": "board.kicad_pro", "version": 3},
                "net_settings": {
                    "classes": [
                        {
                            "name": "Default",
                            "track_width": 0.2,
                            "priority": 2147483647,
                            "clearance": 0.2,
                        }
                    ],
                    "meta": {"version": 4},
                    "netclass_assignments": None,
                    "netclass_patterns": [],
                },
                "pcbnew": {"last_paths": {"specctra_dsn": "board.dsn"}},
                "sheets": [["uuid", "board.kicad_sch"]],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    assert restore_kicad_pro_net_settings(p) is True
    data = json.loads(p.read_text(encoding="utf-8"))
    names = {c["name"] for c in data["net_settings"]["classes"]}
    assert "Power_2A" in names
    assert data["net_settings"]["netclass_assignments"] is None
    assert any(r["pattern"] == "GND" for r in data["net_settings"]["netclass_patterns"])
    assert data["sheets"] == [["uuid", "board.kicad_sch"]]
    assert data["pcbnew"]["last_paths"]["specctra_dsn"] == "board.dsn"
