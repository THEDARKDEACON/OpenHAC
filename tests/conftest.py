"""
Shared pytest fixtures for the OpenHaC test suite.

Provides isolated database instances and SKiDL circuit teardown
to prevent test pollution.
"""

import os
import sqlite3
import tempfile

import pytest

from openhac.core.dotenv_load import apply_kicad_env_aliases

apply_kicad_env_aliases()

@pytest.fixture(autouse=True)
def _isolate_machine_openhac_env(monkeypatch):
    """CODE-002: unit tests do not inherit machine OPENHAC_* or repo .env."""
    for key in list(os.environ):
        if key.startswith("OPENHAC_"):
            monkeypatch.delenv(key, raising=False)
    yield
    from openhac.core.base import Component, _SharedCatalogDb

    Component.db = _SharedCatalogDb()


_LEGACY_SKIDL_SHEET_TESTS = {
    "test_schematic_gen.py",
    "test_schematic_layout.py",
    "test_kicad_sym_pinpos.py",
    "test_architecture_roadmap.py",
    "test_sch001_golden_connectivity_graph.py",
    "test_sch002_multisheet_export.py",
    "test_generated_symbol_lib.py",
    "test_spice_gen.py",
    "test_sso_schematic.py",
    "test_schematic_hierarchy_pins.py",
    "test_audit_gates.py",
    "test_sso_no_hardcoded_graphics.py",
    "test_sps_spice_signoff.py",
}


@pytest.fixture(autouse=True)
def _legacy_skidl_for_skidl_sheet_tests(request, monkeypatch):
    """SKiDL Part/Net sheet tests opt into OPENHAC_LEGACY_SKIDL (FAB-004)."""
    fn = os.path.basename(str(getattr(request, "fspath", "") or ""))
    if fn in _LEGACY_SKIDL_SHEET_TESTS:
        monkeypatch.setenv("OPENHAC_LEGACY_SKIDL", "1")


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
        "description": "10k 1% 0805",
        "category": "Resistor",
        "jlc_class": "Extended",
        "pinout_json": '[{"num": "1", "name": "~", "type": "passive"}, {"num": "2", "name": "~", "type": "passive"}]'
    }


@pytest.fixture(autouse=True)
def _reset_skidl_circuit():
    """Reset the SKiDL default circuit between tests.

    SKiDL accumulates parts/nets into a global circuit object.
    Without reset, tests bleed state into each other.

    Also resets the native OpenHaC core circuit which tracks Component parts.
    """
    def _do_reset():
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
        # Reset the native OpenHaC core circuit so Component parts don't bleed across tests.
        try:
            from openhac.core.circuit import reset_default_circuit
            reset_default_circuit()
        except Exception:
            pass

    _do_reset()
    yield
    _do_reset()
