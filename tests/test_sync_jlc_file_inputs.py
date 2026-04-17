from __future__ import annotations

import json

import pytest

from openhac.database.sync_jlc import _load_skus_file, _normalize_jlc_sku, seed_from_file


def test_normalize_jlc_sku():
    assert _normalize_jlc_sku("123") == "C123"
    assert _normalize_jlc_sku("C123") == "C123"
    assert _normalize_jlc_sku("c123") == "C123"
    assert _normalize_jlc_sku("C001") == "C001"


def test_load_skus_file_accepts_pairs_and_objects(tmp_path):
    p = tmp_path / "skus.json"
    p.write_text(
        json.dumps(
            [
                ["BUCK_TPS63001DRCR", "132150"],
                {"generic_name": "MCU_STM32F405RGT6", "sku": "C7862"},
            ]
        ),
        encoding="utf-8",
    )
    items = _load_skus_file(str(p))
    assert items == [("BUCK_TPS63001DRCR", "C132150"), ("MCU_STM32F405RGT6", "C7862")]


def test_seed_from_file_inserts_rows(monkeypatch, tmp_path):
    seed = tmp_path / "seed.json"
    seed.write_text(
        json.dumps(
            [
                {
                    "generic_name": "X",
                    "kicad_symbol": "Device:R",
                    "kicad_footprint": "Resistor_SMD:R_0603_1608Metric",
                    "manufacturer": "ACME",
                    "mpn": "ACME-1",
                    "supplier_sku": "123",
                    "category": "resistors",
                    "pinout": [{"num": "1", "name": "A"}, {"num": "2", "name": "B"}],
                }
            ]
        ),
        encoding="utf-8",
    )

    class _DB:
        def __init__(self):
            self.rows = []

        def insert_component(self, row, ignore_duplicate=False):  # noqa: ARG002
            self.rows.append(dict(row))
            return 1

    db = _DB()
    monkeypatch.setattr("openhac.database.sync_jlc.DatabaseManager", lambda: db)
    n = seed_from_file(str(seed), verbose=False)
    assert n == 1
    assert db.rows[0]["supplier_sku"] == "C123"
    assert "pinout_json" in db.rows[0]

