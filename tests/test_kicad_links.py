"""KiCad project membership: schematic UUID ↔ footprint path."""

from __future__ import annotations

from openhac.schematic.ir import SheetBox
from openhac.schematic.kicad_links import (
    ROOT_SHEET_TITLE,
    footprint_schematic_path,
    project_sheet_table,
    root_schematic_uuid,
    sheet_instance_uuid,
    symbol_instance_uuid,
)
from openhac.schematic.util import det_uuid


class _Part:
    def __init__(self, ref, sheet="", part_id=7):
        self.ref = ref
        self.refdes = ref
        self._part_id = part_id
        self.fields = {"OpenHaC_Module": sheet} if sheet else {}


def test_symbol_uuid_matches_layout_key():
    p = _Part("R1")
    assert symbol_instance_uuid(p, 1) == det_uuid("part_id:7:u1")


def test_flat_footprint_path_is_symbol_uuid():
    p = _Part("R1")
    assert footprint_schematic_path(p, parts=[p]) == f"/{symbol_instance_uuid(p)}"


def test_hierarchical_footprint_path_includes_sheet(monkeypatch):
    monkeypatch.setenv("OPENHAC_SCHEMATIC_MULTI_SHEET", "1")
    p = _Part("U1", sheet="COMPUTE")
    path = footprint_schematic_path(p, parts=[p])
    assert path == f"/{sheet_instance_uuid('COMPUTE')}/{symbol_instance_uuid(p)}"


def test_project_sheet_table_root_and_children():
    ir = type("IR", (), {})()
    ir.sheets = [
        SheetBox(name="COMPUTE", filename="x.COMPUTE.kicad_sch", x=0, y=0, w=1, h=1, uuid=sheet_instance_uuid("COMPUTE")),
    ]
    rows = project_sheet_table(ir=ir)
    assert rows[0] == [root_schematic_uuid(), ROOT_SHEET_TITLE]
    assert rows[1] == [sheet_instance_uuid("COMPUTE"), "COMPUTE"]
