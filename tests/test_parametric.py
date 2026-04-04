"""Tests for the parametric query engine in DatabaseManager."""

import pytest
from openhac.database.db_manager import DatabaseManager


@pytest.fixture
def seeded_db(tmp_path):
    """Create a temporary DB with parametric seed data."""
    db = DatabaseManager(db_path=str(tmp_path / "test.db"))
    # Insert test components with parametric fields
    db.insert_component({
        "generic_name": "R_10k_0805",
        "kicad_symbol": "Device:R",
        "kicad_footprint": "Resistor_SMD:R_0805",
        "manufacturer": "Yageo",
        "mpn": "RC0805FR-0710KL",
        "supplier_sku": "C17513",
        "description": "10k 1% 0805 Resistor",
        "category": "resistors",
        "tolerance": "1%",
        "power_watts": 0.125,
        "jlc_class": "Basic",
    })
    db.insert_component({
        "generic_name": "R_10k_0603",
        "kicad_symbol": "Device:R",
        "kicad_footprint": "Resistor_SMD:R_0603",
        "manufacturer": "Yageo",
        "mpn": "RC0603FR-0710KL",
        "supplier_sku": "C25804",
        "description": "10k 1% 0603 Resistor",
        "category": "resistors",
        "tolerance": "1%",
        "power_watts": 0.1,
        "jlc_class": "Basic",
    })
    db.insert_component({
        "generic_name": "C_100nF_0603",
        "kicad_symbol": "Device:C",
        "kicad_footprint": "Capacitor_SMD:C_0603",
        "manufacturer": "Samsung",
        "mpn": "CL10B104KB8NNNC",
        "supplier_sku": "C14663",
        "description": "100nF 50V 0603 Capacitor",
        "category": "capacitors",
        "voltage_rating": 50.0,
        "jlc_class": "Basic",
    })
    db.insert_component({
        "generic_name": "C_100nF_0805",
        "kicad_symbol": "Device:C",
        "kicad_footprint": "Capacitor_SMD:C_0805",
        "manufacturer": "Samsung",
        "mpn": "CL21B104KBCNNNC",
        "supplier_sku": "C1525",
        "description": "100nF 25V 0805 Capacitor",
        "category": "capacitors",
        "voltage_rating": 25.0,
        "jlc_class": "Extended",
    })
    db.insert_component({
        "generic_name": "LDO_5V",
        "kicad_symbol": "Regulator_Linear:AMS1117-5.0",
        "kicad_footprint": "Package_TO_SOT_SMD:SOT-223",
        "manufacturer": "AMS",
        "mpn": "AMS1117-5.0",
        "supplier_sku": "C347222",
        "description": "5V 1A LDO Voltage Regulator",
        "category": "voltage_regulators",
        "jlc_class": "Basic",
    })
    return db


class TestParametricSearch:

    def test_exact_match_by_value_and_package(self, seeded_db):
        """Exact match: category + value + package."""
        result, fallback = seeded_db.parametric_search(
            "resistors", value="10k", package="0805"
        )
        assert result is not None
        assert result["generic_name"] == "R_10k_0805"
        assert fallback is False

    def test_exact_match_returns_basic_first(self, seeded_db):
        """When multiple matches, Basic class should come first."""
        result, fallback = seeded_db.parametric_search(
            "capacitors", value="100nF"
        )
        assert result is not None
        assert result["jlc_class"] == "Basic"

    def test_soft_fallback_voltage_over_spec(self, seeded_db):
        """Request 10V cap → should get 25V or 50V cap (over-spec)."""
        result, fallback = seeded_db.parametric_search(
            "capacitors", value="100nF", voltage_rating=10.0
        )
        assert result is not None
        assert result["voltage_rating"] >= 10.0

    def test_soft_fallback_when_exact_voltage_missing(self, seeded_db):
        """Request 30V cap → only 50V available → soft fallback."""
        result, fallback = seeded_db.parametric_search(
            "capacitors", value="100nF", voltage_rating=30.0
        )
        assert result is not None
        assert result["voltage_rating"] >= 30.0
        # The 25V cap is filtered out, only 50V matches

    @pytest.mark.parametrize("mock_jit", [True])
    def test_no_match_returns_none_with_jit_disabled(self, seeded_db, mock_jit):
        """When both local and JIT fail, should return None."""
        from unittest.mock import patch
        with patch("openhac.database.api_fallback.fetch_and_map_part", return_value=None):
            result, fallback = seeded_db.parametric_search(
                "transistors", value="BC547"
            )
            assert result is None

    def test_voltage_regulator_search(self, seeded_db):
        """Find a 5V regulator by v_out."""
        result, fallback = seeded_db.parametric_search(
            "voltage_regulators", v_out=5.0
        )
        assert result is not None
        assert "5V" in result["generic_name"] or "5.0" in result["description"]

    def test_tolerance_as_soft_constraint(self, seeded_db):
        """Request 0.1% tolerance → not available → should fallback."""
        result, fallback = seeded_db.parametric_search(
            "resistors", value="10k", tolerance="0.1%"
        )
        # Exact 0.1% doesn't exist, should fallback to 1%
        assert result is not None
        assert fallback is True


class TestSchemaMigration:

    def test_v2_columns_exist(self, seeded_db):
        """Verify that the v2 parametric columns exist."""
        comp = seeded_db.get_component("R_10k_0805")
        assert "tolerance" in comp
        assert "voltage_rating" in comp
        assert "power_watts" in comp
        assert "jlc_class" in comp

    def test_v2_column_values_stored(self, seeded_db):
        """Verify parametric values are stored and retrieved."""
        comp = seeded_db.get_component("R_10k_0805")
        assert comp["tolerance"] == "1%"
        assert comp["power_watts"] == 0.125
        assert comp["jlc_class"] == "Basic"

    def test_migration_is_idempotent(self, tmp_path):
        """Calling init multiple times should not error."""
        db_path = str(tmp_path / "idem.db")
        db1 = DatabaseManager(db_path=db_path)
        db2 = DatabaseManager(db_path=db_path)
        # No crash = success
