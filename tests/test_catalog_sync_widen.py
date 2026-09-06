"""CAT-002 / CAT-003: widen jlcsearch categories with mocked HTTP."""

from __future__ import annotations

import json
from io import BytesIO
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

from openhac.database.sync_jlc import (
    CATEGORY_ENDPOINTS,
    endpoint_path_for_sync,
    probe_typed_category,
    sync_catalog,
)


def _http_error(code: int, url: str = "https://jlcsearch.tscircuit.com/inductors/list.json"):
    return HTTPError(url, code, "not found", hdrs=None, fp=BytesIO(b""))


def test_default_passive_urls_keep_is_basic():
    path, _ = endpoint_path_for_sync("resistors", include_extended=False)
    assert "is_basic=true" in path
    path_x, _ = endpoint_path_for_sync("resistors", include_extended=True)
    assert "is_basic=true" not in path_x


def test_probe_404_skipped(monkeypatch):
    def opener(req, timeout=15):
        raise _http_error(404)

    assert probe_typed_category("inductors", opener=opener) is False


def test_mocked_200_inductors_insert(tmp_db, monkeypatch):
    db_path, dm = tmp_db
    monkeypatch.setenv("OPENHAC_DB_PATH", db_path)

    def fake_probe(category, opener=None):
        return category == "inductors"

    items = [
        {
            "inductance": 10e-6,
            "package": "0805",
            "stock": 100,
            "lcsc": 111,
            "mfr": "L0805",
            "description": "10uH",
        }
    ]
    with patch("openhac.database.sync_jlc.probe_typed_category", side_effect=fake_probe), patch(
        "openhac.database.sync_jlc._fetch_category", return_value=items
    ):
        n = sync_catalog(categories=["inductors"], verbose=False)
    assert n == 1
    row = dm.get_component("L_10uH_0805")
    assert row
    assert row["category"] == "inductors"
    po = json.loads(row["pinout_json"])
    assert len(po) == 2


def test_max_per_category_cap(tmp_db, monkeypatch):
    db_path, _dm = tmp_db
    monkeypatch.setenv("OPENHAC_DB_PATH", db_path)
    items = [
        {
            "resistance": 1000 * (i + 1),
            "package": "0603",
            "stock": 10,
            "lcsc": 1000 + i,
            "mfr": f"R{i}",
            "description": "r",
        }
        for i in range(20)
    ]
    with patch("openhac.database.sync_jlc._fetch_category", return_value=items) as fetch:
        n = sync_catalog(
            categories=["resistors"], verbose=False, max_per_category=3
        )
        assert fetch.call_args.kwargs.get("limit") == 3 or fetch.call_args[1].get("limit") == 3
    assert n <= 3


def test_new_categories_listed():
    for cat in ("inductors", "crystals", "connectors", "fuses", "beads", "bjts"):
        assert cat in CATEGORY_ENDPOINTS
