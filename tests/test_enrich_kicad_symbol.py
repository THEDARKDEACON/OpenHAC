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
