"""Board catalog sidecars load before ``Component()`` (no extra CLI ritual)."""

from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

import pytest

from openhac.compiler.board_sidecars import (
    apply_board_sidecars,
    discover_board_sidecars,
)
from openhac.core.circuit import reset_default_circuit

_REPO = Path(__file__).resolve().parents[1]
_RTU = _REPO / "examples" / "complex_grid_edge_rtu.py"


def _seed_row(generic_name: str) -> dict:
    return {
        "generic_name": generic_name,
        "kicad_symbol": "Connector_Generic:Conn_01x04",
        "kicad_footprint": "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical",
        "category": "connectors",
        "pinout": [
            {"num": "1", "name": "P1", "type": "passive"},
            {"num": "2", "name": "P2", "type": "passive"},
            {"num": "3", "name": "P3", "type": "passive"},
            {"num": "4", "name": "P4", "type": "passive"},
        ],
    }


def test_discover_seed_and_manifest(tmp_path):
    board = tmp_path / "board.py"
    board.write_text("board = None\n", encoding="utf-8")
    seed = tmp_path / "board.openhac-seed.json"
    seed.write_text("[]\n", encoding="utf-8")
    ov = tmp_path / "catalog_overlays"
    ov.mkdir()
    (ov / "x.json").write_text("[]\n", encoding="utf-8")
    man = tmp_path / "board.openhac.json"
    cas = tmp_path / "cassettes"
    cas.mkdir()
    man.write_text(
        json.dumps({"schema": "openhac.board-sidecars.v1", "vendor_cassettes": "cassettes"}),
        encoding="utf-8",
    )
    found = discover_board_sidecars(board)
    assert seed.resolve() in found.seed_files
    assert ov.resolve() in found.overlay_paths
    assert cas.resolve() in found.cassette_dirs


def test_apply_seed_then_component_constructs(tmp_db, tmp_path, monkeypatch):
    db_path, dm = tmp_db
    monkeypatch.setenv("OPENHAC_DB_PATH", db_path)
    monkeypatch.setenv("OPENHAC_NO_NETWORK", "1")
    monkeypatch.delenv("OPENHAC_NO_BOARD_SIDECARS", raising=False)

    board = tmp_path / "board.py"
    board.write_text("board = None\n", encoding="utf-8")
    (tmp_path / "board.openhac-seed.json").write_text(
        json.dumps([_seed_row("HDR_TEST_SIDECAR")]),
        encoding="utf-8",
    )
    apply_board_sidecars(board)
    row = dm.get_component("HDR_TEST_SIDECAR")
    assert row is not None
    reset_default_circuit()
    from openhac.core.base import Component

    c = Component("HDR_TEST_SIDECAR")
    assert c["P1"] is not None


def test_skip_env_does_not_seed(tmp_db, tmp_path, monkeypatch):
    db_path, dm = tmp_db
    monkeypatch.setenv("OPENHAC_DB_PATH", db_path)
    monkeypatch.setenv("OPENHAC_NO_BOARD_SIDECARS", "1")
    board = tmp_path / "board.py"
    board.write_text("board = None\n", encoding="utf-8")
    (tmp_path / "board.openhac-seed.json").write_text(
        json.dumps([_seed_row("HDR_SKIPPED")]),
        encoding="utf-8",
    )
    apply_board_sidecars(board)
    assert dm.get_component("HDR_SKIPPED") is None


def test_rtu_manifest_ingests_hdr(tmp_db, monkeypatch):
    db_path, dm = tmp_db
    monkeypatch.setenv("OPENHAC_DB_PATH", db_path)
    monkeypatch.setenv("OPENHAC_NO_NETWORK", "1")
    monkeypatch.delenv("OPENHAC_NO_BOARD_SIDECARS", raising=False)
    found = discover_board_sidecars(_RTU)
    assert found.cassette_dirs
    apply_board_sidecars(_RTU)
    assert dm.get_component("HDR_1x04") is not None
    usb = dm.get_component("USB_C_HRO_TYPE_C_31_M_12")
    assert usb is not None
    pins = json.loads(usb.get("pinout_json") or "[]")
    names = {str(p.get("name") or "") for p in pins}
    assert "VBUS" in names
    assert "GND" in names


def test_missing_component_mentions_sidecar(tmp_db, monkeypatch):
    db_path, _dm = tmp_db
    monkeypatch.setenv("OPENHAC_DB_PATH", db_path)
    monkeypatch.setenv("OPENHAC_NO_NETWORK", "1")
    reset_default_circuit()
    from openhac.core.base import Component

    with pytest.raises(ValueError, match=r"openhac-seed\.json"):
        Component("NO_SUCH_PART_XYZ")


def test_cmd_compile_loads_sidecar_before_import(tmp_db, tmp_path, monkeypatch):
    from openhac import cli
    from openhac.core.board import Board

    db_path, _dm = tmp_db
    monkeypatch.setenv("OPENHAC_DB_PATH", db_path)
    monkeypatch.setenv("OPENHAC_NO_NETWORK", "1")
    monkeypatch.setenv("OPENHAC_SKIP_LAYOUT", "1")
    monkeypatch.delenv("OPENHAC_NO_BOARD_SIDECARS", raising=False)

    board_py = tmp_path / "design.py"
    board_py.write_text(
        "from openhac.core.board import Board\n"
        "from openhac.core.base import Component, Module\n"
        "class M(Module):\n"
        "    def __init__(self):\n"
        "        super().__init__('M')\n"
        "        self.add(Component('HDR_CLI_SIDECAR'))\n"
        "board = Board(size_mm=(20.0, 20.0))\n"
        "board.add_module(M())\n",
        encoding="utf-8",
    )
    (tmp_path / "design.openhac-seed.json").write_text(
        json.dumps([_seed_row("HDR_CLI_SIDECAR")]),
        encoding="utf-8",
    )

    called = {"ok": False}

    def _fake_compile(self, **kwargs):
        called["ok"] = True

    monkeypatch.setattr(Board, "compile", _fake_compile, raising=True)
    args = Namespace(
        script=str(board_py),
        name="t",
        no_route=True,
        skip_layout=True,
        no_schematic=True,
        allow_risky_parts=False,
        production=False,
        db_path=db_path,
        output_dir=str(tmp_path / "out"),
    )
    cli.cmd_compile(args)
    assert called["ok"] is True


def test_cassette_ingest_overwrites_easyeda_usb_footprint(tmp_db, monkeypatch):
    db_path, dm = tmp_db
    monkeypatch.setenv("OPENHAC_DB_PATH", db_path)
    monkeypatch.setenv("OPENHAC_NO_NETWORK", "1")
    monkeypatch.setenv("OPENHAC_NO_BUNDLED_CATALOG_OVERLAYS", "1")
    from openhac.database.catalog_overlay import reset_catalog_overlay_caches
    from openhac.database.vendor_cassettes import ingest_cassette_directory

    reset_catalog_overlay_caches()
    dm.insert_component(
        {
            "generic_name": "USB_C_HRO_TYPE_C_31_M_12",
            "kicad_symbol": "Device:R",
            "kicad_footprint": "easyeda_generated:USB-C_SMD-TYPE-C-31-M-12_1",
            "mpn": "POISON",
            "category": "connectors",
        }
    )
    ingest_cassette_directory(dm, _REPO / "tests" / "fixtures" / "vendor")
    row = dm.get_component("USB_C_HRO_TYPE_C_31_M_12")
    assert row is not None
    assert "Connector_USB:USB_C_Receptacle_HRO" in str(row["kicad_footprint"])
    assert "easyeda" not in str(row["kicad_footprint"]).lower()


def test_stamp_does_not_prefer_easyeda_over_stock_kicad():
    from openhac.core.base import Component

    c = Component.__new__(Component)

    class _Part:
        footprint = "Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12"
        fields: dict = {}

    c.part = _Part()
    c.generic_name = "USB_C_HRO_TYPE_C_31_M_12"
    c._stamp_catalog_fields(
        {
            "kicad_footprint": "easyeda_generated:USB-C_SMD-TYPE-C-31-M-12_1",
            "kicad_symbol": "easyeda_generated:X",
            "manufacturer": "",
            "mpn": "X",
            "supplier_sku": "",
            "jlc_class": "",
            "mouser_sku": "",
            "digikey_sku": "",
            "model_3d_local": "",
        }
    )
    assert "Connector_USB" in c.part.footprint

