"""LIB-001: part_offers table and DatabaseManager API."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from openhac.database.db_manager import DatabaseManager
from openhac.database.vendor_apis import PartInfo


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


def test_migrate_v8_allows_vendor_update_stock_package(tmp_db, sample_component_data):
    """``update_component_from_vendor`` writes ``stock`` / ``package`` after v8 migration."""
    _, dm = tmp_db
    dm.insert_component(sample_component_data)
    part = PartInfo(
        mpn=sample_component_data["mpn"],
        manufacturer=sample_component_data["manufacturer"],
        supplier_sku=sample_component_data["supplier_sku"],
        description=sample_component_data["description"],
        stock=42,
        price_breaks=[],
        datasheet_url=None,
        product_url=None,
        category="resistor",
        package="0805",
        rohs=True,
        lead_time_days=None,
        last_updated=datetime.now(timezone.utc),
    )
    assert dm.update_component_from_vendor(sample_component_data["generic_name"], part) is True
    row = dm.get_component(sample_component_data["generic_name"])
    assert row["stock"] == 42
    assert row["package"] == "0805"
