"""LIB-003: low-confidence JIT blocked by default; DB insert strips internal metadata."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from openhac.core.base import Component, PartDatabaseWriteError, RiskyPartLookupError
from openhac.database.db_manager import DatabaseManager
from openhac.database.lookup_meta import (
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    LOOKUP_CONFIDENCE_KEY,
    confidence_numeric,
)


def test_confidence_numeric_maps_tiers():
    assert confidence_numeric(CONFIDENCE_HIGH) == 1.0
    assert confidence_numeric(CONFIDENCE_MEDIUM) == 0.65
    assert confidence_numeric(CONFIDENCE_LOW) == 0.25


def _minimal_comp_data(generic_name: str = "JIT_X") -> dict:
    return {
        "generic_name": generic_name,
        "kicad_symbol": "Device:R",
        "kicad_footprint": "Resistor_SMD:R_0805_2012Metric",
        "manufacturer": "",
        "mpn": "X",
        "supplier_sku": "",
        "description": "",
        "category": "resistors",
    }


def test_low_confidence_comp_data_raises_risky_error(tmp_db):
    _, dm = tmp_db
    data = _minimal_comp_data()
    data[LOOKUP_CONFIDENCE_KEY] = CONFIDENCE_LOW
    with patch.object(Component, "db", dm):
        with pytest.raises(RiskyPartLookupError, match="low-confidence"):
            Component("JIT_X", comp_data=data)


def test_low_confidence_allowed_with_class_flag(tmp_db, monkeypatch):
    _, dm = tmp_db
    monkeypatch.setattr(Component, "allow_risky_part_lookups", True)
    data = _minimal_comp_data()
    data[LOOKUP_CONFIDENCE_KEY] = CONFIDENCE_LOW
    try:
        with patch.object(Component, "db", dm):
            c = Component("JIT_X", comp_data=data)
        assert c.part is not None
    finally:
        monkeypatch.setattr(Component, "allow_risky_part_lookups", False)


def test_low_confidence_allowed_via_env(tmp_db, monkeypatch):
    _, dm = tmp_db
    monkeypatch.setenv("OPENHAC_ALLOW_RISKY_PARTS", "1")
    data = _minimal_comp_data()
    data[LOOKUP_CONFIDENCE_KEY] = CONFIDENCE_LOW
    with patch.object(Component, "db", dm):
        c = Component("JIT_X", comp_data=data)
    assert c.part is not None


def test_insert_component_strips_openhac_internal_fields(tmp_path):
    db = DatabaseManager(db_path=str(tmp_path / "strip.db"))
    row = _minimal_comp_data("R_strip")
    row[LOOKUP_CONFIDENCE_KEY] = CONFIDENCE_HIGH
    db.insert_component(row, ignore_duplicate=True)
    got = db.get_component("R_strip")
    assert LOOKUP_CONFIDENCE_KEY not in got


def test_live_lookup_insert_failure_raises(tmp_db, monkeypatch):
    _, dm = tmp_db
    api = {
        "components": [
            {
                "lcsc": 111,
                "mfr": "TESTPART111",
                "package": "SOT-23",
                "description": "TESTPART111 generic",
            }
        ]
    }
    import json
    from unittest.mock import MagicMock

    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(api).encode()
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch.object(Component, "db", dm):
        with patch("openhac.core.base.urllib.request.urlopen", return_value=mock_resp):
            with patch.object(dm, "insert_component", side_effect=RuntimeError("disk full")):
                with pytest.raises(PartDatabaseWriteError, match="Could not store"):
                    Component._live_lookup("TESTPART111")
