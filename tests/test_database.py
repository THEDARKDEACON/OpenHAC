"""Tests for openhac.database.db_manager — CRUD operations and search."""

import sqlite3
import pytest


class TestDatabaseManager:
    """DatabaseManager basic CRUD."""

    def test_insert_and_get_component(self, tmp_db, sample_component_data):
        _, dm = tmp_db
        row_id = dm.insert_component(sample_component_data)
        assert row_id is not None

        result = dm.get_component("R_10k_0805")
        assert result is not None
        assert result["kicad_symbol"] == "Device:R"
        assert result["mpn"] == "RC0805FR-0710KL"
        assert result["supplier_sku"] == "C17513"

    def test_get_nonexistent_returns_none(self, tmp_db):
        _, dm = tmp_db
        assert dm.get_component("NONEXISTENT_PART_XYZ") is None

    def test_insert_duplicate_raises(self, tmp_db, sample_component_data):
        _, dm = tmp_db
        dm.insert_component(sample_component_data)
        with pytest.raises(sqlite3.IntegrityError):
            dm.insert_component(sample_component_data, ignore_duplicate=False)

    def test_insert_duplicate_ignore(self, tmp_db, sample_component_data):
        _, dm = tmp_db
        first_id = dm.insert_component(sample_component_data)
        second_id = dm.insert_component(sample_component_data, ignore_duplicate=True)
        assert first_id is not None
        assert second_id is None  # row was skipped

    def test_insert_with_category_and_attributes(self, tmp_db):
        _, dm = tmp_db
        import json
        comp = {
            "generic_name": "LED_RED_0603",
            "kicad_symbol": "Device:LED",
            "kicad_footprint": "LED_SMD:LED_0603_1608Metric",
            "manufacturer": "",
            "mpn": "TEST-LED",
            "supplier_sku": "C12345",
            "description": "Red LED 0603",
            "category": "leds",
            "attributes_json": json.dumps({"color": "RED"}),
        }
        row_id = dm.insert_component(comp)
        assert row_id is not None

        result = dm.get_component("LED_RED_0603")
        assert result["category"] == "leds"
        attrs = json.loads(result["attributes_json"])
        assert attrs["color"] == "RED"


class TestSearchComponents:
    """DatabaseManager.search_components()."""

    def _seed(self, dm):
        components = [
            {"generic_name": "R_1k_0402", "kicad_symbol": "Device:R",
             "kicad_footprint": "Resistor_SMD:R_0402_1005Metric",
             "manufacturer": "", "mpn": "X", "description": "1k resistor", "category": "resistors"},
            {"generic_name": "R_10k_0805", "kicad_symbol": "Device:R",
             "kicad_footprint": "Resistor_SMD:R_0805_2012Metric",
             "manufacturer": "", "mpn": "Y", "description": "10k resistor", "category": "resistors"},
            {"generic_name": "C_100nF_0603", "kicad_symbol": "Device:C",
             "kicad_footprint": "Capacitor_SMD:C_0603_1608Metric",
             "manufacturer": "", "mpn": "Z", "description": "100nF cap", "category": "capacitors"},
        ]
        for c in components:
            dm.insert_component(c)

    def test_search_by_query(self, tmp_db):
        _, dm = tmp_db
        self._seed(dm)
        results = dm.search_components(query="10k")
        assert len(results) == 1
        assert results[0]["generic_name"] == "R_10k_0805"

    def test_search_by_category(self, tmp_db):
        _, dm = tmp_db
        self._seed(dm)
        results = dm.search_components(category="resistors")
        assert len(results) == 2

    def test_search_by_query_and_category(self, tmp_db):
        _, dm = tmp_db
        self._seed(dm)
        results = dm.search_components(query="1k", category="resistors")
        # Should match "R_1k_0402" and "R_10k_0805" (both contain "1k")
        assert len(results) >= 1

    def test_search_no_filters(self, tmp_db):
        _, dm = tmp_db
        self._seed(dm)
        results = dm.search_components()
        assert len(results) == 3

    def test_search_limit(self, tmp_db):
        _, dm = tmp_db
        self._seed(dm)
        results = dm.search_components(limit=1)
        assert len(results) == 1

    def test_search_no_results(self, tmp_db):
        _, dm = tmp_db
        results = dm.search_components(query="ZZZZZ_NONEXISTENT")
        assert results == []
