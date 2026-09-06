"""Enrichment: KiCad symbol pinout merge + offline persistence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openhac.database.db_manager import DatabaseManager
from openhac.database.enrich import enrich_component_in_db

_FIXTURE_SYM_DIR = Path(__file__).resolve().parent / "fixtures" / "kicad_symbols"


def test_enrich_offline_writes_pinout_from_kicad_symbol(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("OPENHAC_NO_NETWORK", "1")
    monkeypatch.setenv("OPENHAC_KICAD_SYMBOL_DIRS", str(_FIXTURE_SYM_DIR))

    db = DatabaseManager(db_path=str(tmp_path / "e.db"))
    db.insert_component(
        {
            "generic_name": "ENR_R_FIX",
            "kicad_symbol": "Device:R",
            "kicad_footprint": "Resistor_SMD:R_0805_2012Metric",
            "manufacturer": "",
            "mpn": "RC0805-10K",
            "supplier_sku": "C17513",
            "description": "test",
            "category": "resistors",
        }
    )

    res = enrich_component_in_db(db=db, generic_name="ENR_R_FIX")
    assert res.updated is True
    assert res.reason == "kicad_symbol"
    row = db.get_component("ENR_R_FIX")
    assert row
    po = json.loads(row["pinout_json"])
    assert len(po) == 2
    assert row.get("pinout_source") == "kicad_symbol"


def test_enrich_does_not_replace_stock_usb_footprint(monkeypatch, tmp_path) -> None:
    from unittest.mock import patch

    from openhac.database.catalog_overlay import reset_catalog_overlay_caches

    monkeypatch.setenv("OPENHAC_NO_BUNDLED_CATALOG_OVERLAYS", "1")
    reset_catalog_overlay_caches()
    dummy = tmp_path / "u.step"
    dummy.write_text("x", encoding="utf-8")
    db = DatabaseManager(db_path=str(tmp_path / "usb.db"))
    db.insert_component(
        {
            "generic_name": "USB_C_HRO_TYPE_C_31_M_12",
            "kicad_symbol": "Connector:USB_C_Receptacle_USB2.0_16P",
            "kicad_footprint": "Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12",
            "manufacturer": "HRO",
            "mpn": "TYPE-C-31-M-12",
            "supplier_sku": "C99999",
            "description": "usb",
            "category": "connectors",
            "pinout_json": json.dumps(
                [{"num": "A1", "name": "GND", "type": "power_in"}, {"num": "A4", "name": "VBUS", "type": "power_in"}]
            ),
            "model_3d_local": str(dummy),
        }
    )
    with patch(
        "openhac.database.easyeda_integration.generate_footprint_from_lcsc",
        return_value=("easyeda_generated:USB-C_SMD-TYPE-C-31-M-12_1", None),
    ) as gen:
        res = enrich_component_in_db(
            db=db, generic_name="USB_C_HRO_TYPE_C_31_M_12", allow_network=True
        )
    row = db.get_component("USB_C_HRO_TYPE_C_31_M_12")
    assert "Connector_USB:USB_C_Receptacle_HRO" in str(row["kicad_footprint"])
    assert "easyeda" not in str(row["kicad_footprint"]).lower()
    gen.assert_not_called()
    assert res.reason in ("already_has_pinout_and_3d", "already_has_pinout", "ok")


def test_enrich_pref_vendor_skips_kicad_when_offline(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("OPENHAC_NO_NETWORK", "1")
    monkeypatch.setenv("OPENHAC_ENRICH_PINOUT_PREFERENCE", "vendor")
    monkeypatch.setenv("OPENHAC_KICAD_SYMBOL_DIRS", str(_FIXTURE_SYM_DIR))

    db = DatabaseManager(db_path=str(tmp_path / "e.db"))
    db.insert_component(
        {
            "generic_name": "ENR_PREF_V",
            "kicad_symbol": "Device:R",
            "kicad_footprint": "Resistor_SMD:R_0805_2012Metric",
            "manufacturer": "",
            "mpn": "RC0805-10K",
            "supplier_sku": "C17513",
            "description": "test",
            "category": "resistors",
        }
    )

    res = enrich_component_in_db(db=db, generic_name="ENR_PREF_V")
    assert res.updated is False
    assert res.reason == "network_disallowed"
