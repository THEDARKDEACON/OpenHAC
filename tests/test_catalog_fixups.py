"""Tests for catalog overlays (bundled JSON + merge on read)."""

from __future__ import annotations

import json

from openhac.database.catalog_fixups import merge_catalog_fixup
from openhac.database.catalog_overlay import load_bundled_overlay_index, reset_catalog_overlay_caches


def test_merge_fixup_overrides_footprint_and_pinout() -> None:
    reset_catalog_overlay_caches()
    row = {
        "generic_name": "IMU_ICM42688P",
        "kicad_footprint": "Package_LGA:Wrong",
        "pinout_json": "",
        "category": "capacitors",
        "supplier_sku": "C2191168",
    }
    m = merge_catalog_fixup(row)
    assert "DHWQFN-14" in m["kicad_footprint"]
    po = json.loads(m["pinout_json"])
    assert any(p["num"] == "13" and p["name"] == "SCK" for p in po)
    assert m["supplier_sku"] == "C1850418"


def test_bundled_index_flash_has_numeric_pad_pinout() -> None:
    idx = load_bundled_overlay_index()
    po = json.loads(idx["FLASH_W25Q128JV"]["pinout_json"])
    nums = {p["num"] for p in po}
    assert nums == {str(i) for i in range(1, 9)}


def test_bundled_index_ldo_matches_sot223_three_pads() -> None:
    idx = load_bundled_overlay_index()
    po = json.loads(idx["LDO_LDL1117S33R"]["pinout_json"])
    assert [p["num"] for p in po] == ["1", "2", "3"]


def test_user_overlay_overrides_bundled(monkeypatch, tmp_path) -> None:
    reset_catalog_overlay_caches()
    monkeypatch.setenv("OPENHAC_NO_BUNDLED_CATALOG_OVERLAYS", "1")
    reset_catalog_overlay_caches()
    p = tmp_path / "mine.json"
    p.write_text(
        json.dumps(
            [
                {
                    "generic_name": "FLASH_W25Q128JV",
                    "kicad_footprint": "Package_SO:User_SOIC8",
                    "pinout": [{"num": "1", "name": "CS", "type": "input"}],
                }
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENHAC_CATALOG_OVERLAY", str(p))
    reset_catalog_overlay_caches()
    m = merge_catalog_fixup(
        {"generic_name": "FLASH_W25Q128JV", "kicad_footprint": "Package_SO:Old", "pinout_json": ""}
    )
    assert m["kicad_footprint"] == "Package_SO:User_SOIC8"
    po = json.loads(m["pinout_json"])
    assert len(po) == 1
    reset_catalog_overlay_caches()
    monkeypatch.delenv("OPENHAC_NO_BUNDLED_CATALOG_OVERLAYS", raising=False)
    monkeypatch.delenv("OPENHAC_CATALOG_OVERLAY", raising=False)
    reset_catalog_overlay_caches()
