"""Tests for footprint-aware pinout sufficiency and sensor category normalization."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openhac.core.base import Component
from openhac.database.db_manager import _normalize_sensor_category_for_db
from openhac.database.enrich import (
    _merge_kicad_and_vendor_pinouts,
    _pinout_footprint_aligned,
    _pinout_is_sufficient,
    needs_pinout_database_enrich,
)


def test_pinout_sufficient_when_footprint_aligned_passive(monkeypatch) -> None:
    monkeypatch.setattr(
        "openhac.database.enrich._footprint_pad_set_for_row",
        lambda row: {"1", "2"},
    )
    po = [{"num": "1", "name": "1"}, {"num": "2", "name": "2"}]
    row = {"kicad_footprint": "Resistor_SMD:R_0805_2012Metric"}
    assert _pinout_footprint_aligned(po, row) is True
    assert _pinout_is_sufficient(po, row) is True
    assert needs_pinout_database_enrich(__import__("json").dumps(po), catalog_row=row) is False


def test_pinout_not_sufficient_duplicate_nums() -> None:
    po = [{"num": "1", "name": "1"}, {"num": "1", "name": "1"}]
    assert _pinout_is_sufficient(po, None) is False
    assert needs_pinout_database_enrich(__import__("json").dumps(po), catalog_row=None) is True


def test_merge_prefers_local_nums_when_pad_aligned(monkeypatch) -> None:
    monkeypatch.setattr(
        "openhac.database.enrich._footprint_pad_set_for_row",
        lambda row: {"1", "2", "3"},
    )
    row = {"kicad_footprint": "Package_TO_SOT_SMD:SOT-223-3_TabPin2"}
    local = [
        {"num": "1", "name": "1", "type": "passive"},
        {"num": "2", "name": "2", "type": "passive"},
        {"num": "3", "name": "3", "type": "passive"},
    ]
    vendor = [
        {"num": "IN", "name": "IN", "type": "power"},
        {"num": "GND", "name": "GND", "type": "power"},
        {"num": "OUT", "name": "OUT", "type": "power"},
    ]
    merged = _merge_kicad_and_vendor_pinouts(local, vendor, preference="auto", row=row)
    assert merged is not None
    assert [p["num"] for p in merged] == ["1", "2", "3"]
    assert len(merged) == 3
    assert merged[0]["name"] == "1"


def test_refdes_prefix_accelerometer_category() -> None:
    assert Component._get_refdes_prefix(object(), "accelerometers") == "U"
    assert Component._get_refdes_prefix(object(), "barometers") == "U"


def test_refdes_prefix_xtal_not_switch() -> None:
    assert (
        Component._get_refdes_prefix(
            object(),
            "switches",
            generic_name="XTAL_8MHZ_3225",
        )
        == "X"
    )


def test_refdes_prefix_tja1051_not_diode() -> None:
    assert (
        Component._get_refdes_prefix(
            object(),
            "Diodes - General Purpose",
            generic_name="CAN_TJA1051",
        )
        == "U"
    )
    assert (
        Component._get_refdes_prefix(
            object(),
            "Diodes - General Purpose",
            mpn="TJA1051T/3",
        )
        == "U"
    )


def test_normalize_sensor_category_for_db() -> None:
    assert _normalize_sensor_category_for_db("accelerometers") == "ic"
    assert _normalize_sensor_category_for_db("Magnetometers") == "ic"
    assert _normalize_sensor_category_for_db("resistors") == "resistors"
    assert (
        _normalize_sensor_category_for_db(
            "Diodes - General Purpose",
            generic_name="CAN_TJA1051",
        )
        == "ic"
    )
    assert (
        _normalize_sensor_category_for_db("Diodes - General Purpose", mpn="TJA1051T")
        == "ic"
    )
    assert (
        _normalize_sensor_category_for_db("switches", generic_name="XTAL_8MHZ_3225")
        == "crystals"
    )


def test_xtal_seed_example_has_pad_numeric_pinout() -> None:
    """Example seed fragment: use with ``sync_jlc --seed-file`` for parts that never enrich online."""
    path = Path(__file__).resolve().parent / "fixtures" / "seed_xtal_8mhz_example.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, list) and data
    row = data[0]
    po = row.get("pinout") or json.loads(row.get("pinout_json") or "[]")
    nums = {str(p["num"]) for p in po}
    assert nums == {"1", "2", "3", "4"}


def test_enrich_strict_pinout_pads_raises_on_mismatch(monkeypatch, tmp_path) -> None:
    import json

    from openhac.database.db_manager import DatabaseManager
    from openhac.database import enrich as enrich_mod

    monkeypatch.setenv("OPENHAC_ENRICH_STRICT_PINOUT_PADS", "1")
    monkeypatch.setattr(
        "openhac.compiler.pcb_placement.footprint_pad_numbers_from_library",
        lambda lib, name: {"1", "2"},
    )
    db = DatabaseManager(db_path=str(tmp_path / "s.db"))
    db.insert_component(
        {
            "generic_name": "BAD_PAD",
            "kicad_symbol": "Device:R",
            "kicad_footprint": "Resistor_SMD:R_0805_2012Metric",
            "manufacturer": "",
            "mpn": "X",
            "supplier_sku": "C1",
            "description": "",
            "category": "resistors",
        }
    )
    db.update_component_fields(
        "BAD_PAD",
        {"pinout_json": json.dumps([{"num": "99", "name": "VIN"}])},
    )
    with pytest.raises(RuntimeError, match="may not match footprint"):
        enrich_mod._warn_if_pinout_mismatches_footprint_pads(db, "BAD_PAD")
