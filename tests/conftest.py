"""
Shared pytest fixtures for the OpenHaC test suite.

Provides isolated database instances and SKiDL circuit teardown
to prevent test pollution.
"""

import os
import sqlite3
import tempfile

import pytest


@pytest.fixture()
def tmp_db(tmp_path):
    """Create an isolated SQLite database with the OpenHaC schema applied.

    Returns (db_path, DatabaseManager) so tests can inspect the raw file
    *and* use the ORM.
    """
    db_path = str(tmp_path / "test_openhac.db")
    schema_path = os.path.join(
        os.path.dirname(__file__), "..", "openhac", "database", "schema.sql"
    )

    # Apply schema manually so we control the path
    with sqlite3.connect(db_path) as conn:
        with open(schema_path) as f:
            conn.executescript(f.read())

    from openhac.database.db_manager import DatabaseManager
    dm = DatabaseManager(db_path=db_path)
    return db_path, dm


@pytest.fixture()
def sample_component_data():
    """Return a minimal valid component dict for insertion."""
    return {
        "generic_name": "R_10k_0805",
        "kicad_symbol": "Device:R",
        "kicad_footprint": "Resistor_SMD:R_0805_2012Metric",
        "manufacturer": "Yageo",
        "mpn": "RC0805FR-0710KL",
        "supplier_sku": "C17513",
        "description": "10k 1% 0805 Resistor",
    }


@pytest.fixture(autouse=True)
def _reset_skidl_circuit():
    """Reset the SKiDL default circuit between tests.

    SKiDL accumulates parts/nets into a global circuit object.
    Without reset, tests bleed state into each other.
    """
    try:
        import skidl
        skidl.reset()
    except Exception:
        pass
    try:
        from openhac.core.base import Component

        Component.allow_risky_part_lookups = False
        Component.require_kicad_symbols = False
        Component.strict_jit_lookups = False
    except Exception:
        pass
    yield
    try:
        import skidl
        skidl.reset()
    except Exception:
        pass
    try:
        from openhac.core.base import Component

        Component.allow_risky_part_lookups = False
        Component.require_kicad_symbols = False
        Component.strict_jit_lookups = False
    except Exception:
        pass
