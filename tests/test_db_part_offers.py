"""LIB-001: part_offers table and DatabaseManager API."""

from __future__ import annotations

import sqlite3

from openhac.database.db_manager import DatabaseManager


def test_list_part_offers_empty(tmp_db):
    _, dm = tmp_db
    assert dm.list_part_offers("missing") == []


def test_insert_and_list_part_offers(tmp_db):
    _, dm = tmp_db
    dm.insert_part_offer(
        {
            "generic_name": "X_PART",
            "rank": 1,
            "supplier": "Mouser",
            "supplier_sku": "ABC",
            "mpn": "MPN1",
            "note": "n1",
        }
    )
    dm.insert_part_offer(
        {
            "generic_name": "X_PART",
            "rank": 2,
            "supplier": "DigiKey",
            "supplier_sku": "XYZ",
            "mpn": "",
            "note": "",
        }
    )
    rows = dm.list_part_offers("X_PART")
    assert len(rows) == 2
    assert rows[0]["supplier"] == "Mouser"
    assert rows[1]["supplier_sku"] == "XYZ"


def test_migrate_v4_creates_table_on_old_db(tmp_path):
    """Opening DB without part_offers in schema still gets table via migration."""
    db_path = str(tmp_path / "legacy.db")
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE components (id INTEGER PRIMARY KEY, generic_name TEXT UNIQUE)"
        )
    dm = DatabaseManager(db_path=db_path)
    with sqlite3.connect(db_path) as conn:
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='part_offers'"
        )
        assert cur.fetchone() is not None
    dm.insert_part_offer(
        {
            "generic_name": "G",
            "rank": 1,
            "supplier": "S",
            "supplier_sku": "1",
            "mpn": "",
            "note": "",
        }
    )
    assert len(dm.list_part_offers("G")) == 1
