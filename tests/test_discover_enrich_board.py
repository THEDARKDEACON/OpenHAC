"""Tests for discover_enrich_targets_from_board."""

from __future__ import annotations

from unittest.mock import MagicMock

from openhac.database.enrich import (
    _guess_mpn_tail_from_generic_name,
    _search_strings_for_enrich,
    discover_enrich_targets_from_board,
)


class _FakeDB:
    def __init__(self, rows: dict[str, dict | None]) -> None:
        self._rows = rows

    def get_component(self, gn: str):
        return self._rows.get(gn)


def test_discover_skips_when_pinout_present() -> None:
    board = MagicMock()
    mod = MagicMock()
    comp = MagicMock()
    comp.generic_name = "U1_PART"
    comp._comp_data = {"pinout_json": '[{"num":"1","name":"VIN"}]'}
    comp.db = _FakeDB({})
    mod.components = [comp]
    board._get_all_modules.return_value = [mod]

    assert discover_enrich_targets_from_board(board) == []


def test_discover_includes_mpn_when_row_missing_pinout() -> None:
    board = MagicMock()
    mod = MagicMock()
    comp = MagicMock()
    comp.generic_name = "U2_PART"
    comp._comp_data = {}
    comp.db = _FakeDB(
        {
            "U2_PART": {
                "generic_name": "U2_PART",
                "mpn": "XYZ123",
                "supplier_sku": "C12345",
                "pinout_json": None,
                "symbol_data": None,
            }
        }
    )
    mod.components = [comp]
    board._get_all_modules.return_value = [mod]

    assert discover_enrich_targets_from_board(board) == [
        {"generic_name": "U2_PART", "mpn": "XYZ123", "supplier_sku": "C12345"}
    ]


def test_guess_mpn_tail() -> None:
    assert _guess_mpn_tail_from_generic_name("BUCK_TPS63001DRCR") == "TPS63001DRCR"
    assert _guess_mpn_tail_from_generic_name("R_0603") is None


def test_search_strings_dedupes_mpn_and_tail() -> None:
    assert _search_strings_for_enrich("BUCK_TPS63001DRCR", "TPS63001DRCR") == [
        "TPS63001DRCR",
        "BUCK_TPS63001DRCR",
    ]


def test_discover_unique_generic_names() -> None:
    board = MagicMock()
    mod = MagicMock()
    db = _FakeDB(
        {
            "R": {"generic_name": "R", "mpn": None, "supplier_sku": None, "pinout_json": None, "symbol_data": None},
        }
    )
    c1 = MagicMock()
    c1.generic_name = "R"
    c1._comp_data = {}
    c1.db = db
    c2 = MagicMock()
    c2.generic_name = "R"
    c2._comp_data = {}
    c2.db = db
    mod.components = [c1, c2]
    board._get_all_modules.return_value = [mod]

    assert len(discover_enrich_targets_from_board(board)) == 1
