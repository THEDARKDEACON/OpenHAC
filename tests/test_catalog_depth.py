"""CAT / 3D catalog-depth tests (CAT-001…015, 3D-001…005)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from openhac.database.catalog_coverage import catalog_grade, collect_catalog_coverage
from openhac.database.db_manager import DatabaseManager
from openhac.database.pin_policy import (
    kicad_symbol_is_pin_name_oracle,
    pinout_for_sync_category,
    should_store_vendor_pinout,
    two_terminal_pinout,
)

_FIXTURE_SYM_DIR = Path(__file__).resolve().parent / "fixtures" / "kicad_symbols"


def _resistor_ready(**extra):
    row = {
        "generic_name": "R_10k_0603",
        "category": "resistors",
        "kicad_symbol": "Device:R",
        "kicad_footprint": "Resistor_SMD:R_0603_1608Metric",
        "mpn": "RC0603FR-0710KL",
        "supplier_sku": "C17513",
        "pinout_json": json.dumps(two_terminal_pinout()),
        "model_3d_source": "kicad_lib",
        "model_3d_local": "${KICAD8_3DMODEL_DIR}/Resistor_SMD.3dshapes/R_0603_1608Metric.wrl",
        "manufacturer": "",
        "description": "10k 0603",
    }
    row.update(extra)
    return row


def test_cat001_two_terminal_0603_compile_ready():
    assert catalog_grade(_resistor_ready()) == "compile_ready"


def test_cat001_mcu_sku_only_warehouse():
    row = {
        "generic_name": "MCU_ESP_C123",
        "category": "microcontrollers",
        "kicad_symbol": "MCU_Module:Generic_MCU",
        "kicad_footprint": "Package_QFP:LQFP-48_7x7mm_P0.5mm",
        "mpn": "ESP32",
        "supplier_sku": "C123",
        "pinout_json": None,
        "manufacturer": "",
        "description": "sku only",
    }
    assert catalog_grade(row) == "warehouse"


def test_cat001_numeric_only_mcu_warehouse():
    pins = [{"num": str(i), "name": str(i), "type": "bidirectional"} for i in range(1, 9)]
    row = {
        "generic_name": "MCU_FAKE",
        "category": "microcontrollers",
        "kicad_symbol": "MCU_Module:Generic_MCU",
        "kicad_footprint": "Package_QFP:LQFP-48_7x7mm_P0.5mm",
        "mpn": "FAKE",
        "supplier_sku": "C1",
        "pinout_json": json.dumps(pins),
        "model_3d_source": "kicad_lib",
        "manufacturer": "",
        "description": "numeric",
    }
    assert catalog_grade(row) == "warehouse"


def test_cat004_resistor_sync_has_2pin():
    po = pinout_for_sync_category("resistors")
    assert po is not None and len(po) == 2


def test_cat004_mcu_sync_has_empty_pinout():
    assert pinout_for_sync_category("microcontrollers") is None


def test_cat004_hard_skip_numeric_ic_pinout():
    pins = [{"num": "1", "name": "1"}, {"num": "2", "name": "2"}, {"num": "3", "name": "3"}]
    assert should_store_vendor_pinout(pins, category="microcontrollers", generic_name="MCU_X") is False


def test_cat004_vendor_update_skips_numeric_ic(tmp_db):
    from datetime import datetime, timezone

    from openhac.database.vendor_apis import PartInfo

    _, dm = tmp_db
    dm.insert_component(
        {
            "generic_name": "MCU_SKIP",
            "kicad_symbol": "MCU_Module:Generic_MCU",
            "kicad_footprint": "Package_QFP:LQFP-32_7x7mm_P0.8mm",
            "manufacturer": "X",
            "mpn": "MCU1",
            "supplier_sku": "C9",
            "description": "ic",
            "category": "microcontrollers",
        }
    )
    part = PartInfo(
        mpn="MCU1",
        manufacturer="X",
        supplier_sku="C9",
        description="ic",
        stock=1,
        price_breaks=[],
        datasheet_url=None,
        product_url=None,
        category="microcontrollers",
        package="LQFP-32",
        rohs=True,
        lead_time_days=None,
        last_updated=datetime.now(timezone.utc),
        pinout=[{"num": "1", "name": "1"}, {"num": "2", "name": "2"}],
    )
    dm.update_component_from_vendor("MCU_SKIP", part)
    row = dm.get_component("MCU_SKIP")
    assert not row.get("pinout_json")


def test_cat006_coverage_fixture_db(tmp_db, monkeypatch, tmp_path):
    monkeypatch.setenv("OPENHAC_NO_NETWORK", "1")
    _, dm = tmp_db
    dm.insert_component(_resistor_ready())
    dm.insert_component(
        {
            "generic_name": "MCU_WH",
            "kicad_symbol": "MCU_Module:Generic_MCU",
            "kicad_footprint": "Package_QFP:LQFP-32_7x7mm_P0.8mm",
            "manufacturer": "",
            "mpn": "WH",
            "supplier_sku": "C2",
            "description": "warehouse",
            "category": "microcontrollers",
        }
    )
    report = collect_catalog_coverage(dm)
    assert report["schema"] == "openhac.catalog_coverage.v1"
    assert report["compile_ready"] == 1
    assert report["warehouse"] == 1
    assert report["named_pinout"] == 1
    assert any(m["generic_name"] == "MCU_WH" for m in report["missing_3d"])


def test_cat006_coverage_cli_no_socket(tmp_db, monkeypatch):
    db_path, dm = tmp_db
    dm.insert_component(_resistor_ready())
    monkeypatch.setenv("OPENHAC_NO_NETWORK", "1")
    monkeypatch.setenv("OPENHAC_DB_PATH", db_path)
    with patch("urllib.request.urlopen") as mock_open:
        from argparse import Namespace

        from openhac.cli import cmd_catalog_coverage

        cmd_catalog_coverage(Namespace(output=None, as_json=True, json=False))
        mock_open.assert_not_called()


def test_cat007_csv_warehouse_banner(tmp_db, tmp_path, capsys, monkeypatch):
    db_path, _dm = tmp_db
    monkeypatch.setenv("OPENHAC_DB_PATH", db_path)
    csv_path = tmp_path / "lcsc.csv"
    csv_path.write_text(
        "LCSC Part Number,Manufacturer Part Number,Manufacturer,Description,First Category,Package,Stock\n"
        "C999,IC-NO-PINS,Acme,mystery IC,ICs,QFN-16,10\n",
        encoding="utf-8",
    )
    from openhac.database.import_lcsc_csv import WAREHOUSE_IMPORT_BANNER, import_lcsc_csv

    n = import_lcsc_csv(str(csv_path), verbose=False)
    err = capsys.readouterr().err
    assert "WAREHOUSE" in err
    assert "WAREHOUSE" in WAREHOUSE_IMPORT_BANNER
    assert n >= 1
    dm = DatabaseManager(db_path=db_path)
    # generic name derived; search by sku
    row = dm.get_component_by_supplier_sku("C999") or dm.get_component("ICS_IC-NO-PINS_QFN-16")
    assert row
    assert catalog_grade(row) == "warehouse"
    assert (row.get("catalog_tier") or "warehouse") == "warehouse"


def test_cat008_overlay_3d_spice_keys(tmp_db, tmp_path, monkeypatch):
    from openhac.database.catalog_overlay import reset_catalog_overlay_caches

    db_path, dm = tmp_db
    monkeypatch.setenv("OPENHAC_NO_BUNDLED_CATALOG_OVERLAYS", "1")
    monkeypatch.setenv("OPENHAC_NO_BUNDLED_SPICE_MODELS", "1")
    dm.insert_component(
        {
            "generic_name": "OV_PART",
            "kicad_symbol": "Device:R",
            "kicad_footprint": "Resistor_SMD:R_0603_1608Metric",
            "manufacturer": "",
            "mpn": "X",
            "supplier_sku": "C1",
            "description": "ov",
            "category": "resistors",
        }
    )
    overlay = tmp_path / "ov.json"
    overlay.write_text(
        json.dumps(
            [
                {
                    "generic_name": "OV_PART",
                    "model_3d_local": str(tmp_path / "missing.step"),
                    "model_3d_sha256": "abc123",
                    "model_3d_license": "CC-BY-4.0",
                    "spice_include": "nmos_l1.cir",
                    "spice_subckt": "NMOS_L1",
                    "pinout": two_terminal_pinout(),
                }
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENHAC_CATALOG_OVERLAY", str(overlay))
    reset_catalog_overlay_caches()
    row = dm.get_component("OV_PART")
    assert row["model_3d_sha256"] == "abc123"
    assert row["model_3d_license"] == "CC-BY-4.0"
    assert row["spice_include"] == "nmos_l1.cir"
    assert row["spice_subckt"] == "NMOS_L1"
    reset_catalog_overlay_caches()


def test_cat009_catalog_tier_migration(tmp_db):
    _, dm = tmp_db
    dm.insert_component(
        {
            "generic_name": "TIER_R",
            "kicad_symbol": "Device:R",
            "kicad_footprint": "Resistor_SMD:R_0603_1608Metric",
            "manufacturer": "",
            "mpn": "X",
            "supplier_sku": "C1",
            "description": "t",
            "category": "resistors",
            "catalog_tier": "warehouse",
            "pinout_json": json.dumps(two_terminal_pinout()),
            "model_3d_source": "kicad_lib",
            "model_3d_local": "${KICAD8_3DMODEL_DIR}/Resistor_SMD.3dshapes/R_0603_1608Metric.wrl",
        }
    )
    row = dm.get_component("TIER_R")
    assert row.get("catalog_tier") == "warehouse"
    assert DatabaseManager.catalog_grade(row) == "compile_ready"


def test_cat013_device_r_fills_names(monkeypatch):
    monkeypatch.setenv("OPENHAC_KICAD_SYMBOL_DIRS", str(_FIXTURE_SYM_DIR))
    from openhac.database.enrich import fill_pin_names_from_kicad_symbol

    row = {
        "generic_name": "R_X",
        "kicad_symbol": "Device:R",
        "kicad_footprint": "Resistor_SMD:R_0603_1608Metric",
        "category": "resistors",
    }
    po = fill_pin_names_from_kicad_symbol(row)
    assert po and len(po) == 2
    assert {p["num"] for p in po} == {"1", "2"}


def test_cat013_device_ic_no_fill():
    assert kicad_symbol_is_pin_name_oracle("Device:IC") is False
    assert kicad_symbol_is_pin_name_oracle("MCU_Module:Generic_MCU") is False
    from openhac.database.enrich import fill_pin_names_from_kicad_symbol

    assert fill_pin_names_from_kicad_symbol({"kicad_symbol": "Device:IC"}) is None


def test_3d001_provenance_columns(tmp_db):
    _, dm = tmp_db
    dm.insert_component(
        {
            **_resistor_ready(generic_name="R_3D_PROV"),
            "model_3d_sha256": "",
            "model_3d_license": "KiCad",
            "model_3d_source": "kicad_lib",
        }
    )
    row = dm.get_component("R_3D_PROV")
    assert row.get("model_3d_source") == "kicad_lib"
    assert not row.get("model_3d_sha256")


def test_3d002_skip_easyeda_for_jedec():
    from openhac.database.kicad_3d import should_skip_easyeda_3d

    row = _resistor_ready()
    assert should_skip_easyeda_3d(row) is True
    with patch("openhac.database.easyeda_integration.generate_footprint_from_lcsc") as gen:
        from openhac.database.kicad_3d import should_skip_easyeda_3d as skip

        assert skip(row)
        gen.assert_not_called()


def test_3d003_prefetch_no_network(monkeypatch):
    monkeypatch.setenv("OPENHAC_NO_NETWORK", "1")
    from argparse import Namespace

    from openhac.cli import cmd_catalog_prefetch_3d

    with pytest.raises(SystemExit) as ei:
        cmd_catalog_prefetch_3d(Namespace(script=None, skus="C123"))
    assert ei.value.code == 2


def test_3d004_missing_3d_coverage_row(tmp_db):
    _, dm = tmp_db
    dm.insert_component(
        {
            "generic_name": "IC_NO3D",
            "kicad_symbol": "Device:IC",
            "kicad_footprint": "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
            "manufacturer": "",
            "mpn": "X",
            "supplier_sku": "C3",
            "description": "no 3d",
            "category": "ic",
            "pinout_json": json.dumps(
                [{"num": "1", "name": "IN"}, {"num": "2", "name": "OUT"}]
            ),
        }
    )
    report = collect_catalog_coverage(dm)
    assert any(m["generic_name"] == "IC_NO3D" for m in report["missing_3d"])


def test_3d005_gitignore_and_cache_policy():
    gi = Path(__file__).resolve().parents[1] / ".gitignore"
    text = gi.read_text(encoding="utf-8")
    assert "**/*.step" in text
    assert "**/*.wrl" in text
    assert "3D-005" in text
    assert "~/.kiro/openhac/" in text


def test_cat005_missing_pinouts_no_http(tmp_db, monkeypatch):
    db_path, dm = tmp_db
    monkeypatch.setenv("OPENHAC_NO_NETWORK", "1")
    monkeypatch.setenv("OPENHAC_DB_PATH", db_path)
    dm.insert_component(
        {
            "generic_name": "MCU_HOLE",
            "kicad_symbol": "MCU_Module:Generic_MCU",
            "kicad_footprint": "Package_QFP:LQFP-32_7x7mm_P0.8mm",
            "manufacturer": "",
            "mpn": "STM32",
            "supplier_sku": "C8",
            "description": "hole",
            "category": "microcontrollers",
        }
    )
    from openhac.database.enrich import enrich_missing_pinouts_from_db

    with patch("urllib.request.urlopen") as mock_open:
        attempted, updated = enrich_missing_pinouts_from_db(dm)
        assert attempted == 0
        mock_open.assert_not_called()


def test_cat005_mocked_digikey_named_pins(tmp_db, monkeypatch):
    from datetime import datetime, timezone

    from openhac.database.vendor_apis import PartInfo

    _, dm = tmp_db
    monkeypatch.delenv("OPENHAC_NO_NETWORK", raising=False)
    dm.insert_component(
        {
            "generic_name": "MCU_ENR",
            "kicad_symbol": "MCU_Module:Generic_MCU",
            "kicad_footprint": "Package_QFP:LQFP-32_7x7mm_P0.8mm",
            "manufacturer": "",
            "mpn": "STM32F0",
            "supplier_sku": "SKU8",
            "description": "hole",
            "category": "microcontrollers",
        }
    )
    named = [
        {"num": "1", "name": "VDD", "type": "power"},
        {"num": "2", "name": "GND", "type": "power"},
        {"num": "3", "name": "PA0", "type": "bidirectional"},
    ]
    fake = PartInfo(
        mpn="STM32F0",
        manufacturer="ST",
        supplier_sku="SKU8",
        description="mcu",
        stock=1,
        price_breaks=[],
        datasheet_url=None,
        product_url=None,
        category="microcontrollers",
        package="LQFP-32",
        rohs=True,
        lead_time_days=None,
        last_updated=datetime.now(timezone.utc),
        pinout=named,
    )
    fake.source_vendor = "digikey"  # type: ignore[attr-defined]
    with patch("openhac.database.enrich.network_allowed", return_value=True), patch(
        "openhac.database.vendor_apis.vendor_apis_configured", return_value=True
    ), patch("openhac.database.vendor_apis.lookup_part_live", return_value=fake):
        from openhac.database.enrich import enrich_component_in_db

        res = enrich_component_in_db(db=dm, generic_name="MCU_ENR", preferred_vendor="digikey")
    row = dm.get_component("MCU_ENR")
    assert res.updated or row.get("pinout_json")
    po = json.loads(row["pinout_json"]) if row.get("pinout_json") else []
    assert any(p.get("name") == "VDD" for p in po)


def test_cat010_nexar_fail_closed_without_keys(monkeypatch):
    monkeypatch.delenv("NEXAR_CLIENT_ID", raising=False)
    monkeypatch.delenv("NEXAR_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("OCTOPART_CLIENT_ID", raising=False)
    monkeypatch.delenv("OCTOPART_CLIENT_SECRET", raising=False)
    from openhac.database.vendor_apis import NexarAPI

    with pytest.raises(ValueError, match="Nexar"):
        NexarAPI()


def test_cat010_nexar_mocked_pinout(monkeypatch):
    monkeypatch.setenv("NEXAR_CLIENT_ID", "id")
    monkeypatch.setenv("NEXAR_CLIENT_SECRET", "secret")
    from openhac.database.vendor_apis import NexarAPI

    api = NexarAPI()
    payload = {
        "data": {
            "supSearchMpn": {
                "results": [
                    {
                        "part": {
                            "mpn": "ABC",
                            "manufacturer": {"name": "Acme"},
                            "shortDescription": "ic",
                            "category": {"name": "IC"},
                            "specs": [
                                {
                                    "attribute": {"name": "pinout"},
                                    "displayValue": "VIN,GND,OUT",
                                }
                            ],
                        }
                    }
                ]
            }
        }
    }
    parts = api._parse_search(payload, "ABC")
    assert parts and parts[0].pinout
    assert parts[0].pinout[0]["name"] == "VIN"


def test_cat011_offers_do_not_override_pinout(tmp_db):
    from openhac.database.assembler_offers import ingest_pcbway_seeed_offers

    _, dm = tmp_db
    pins = json.dumps([{"num": "1", "name": "VIN"}, {"num": "2", "name": "GND"}])
    dm.insert_component(
        {
            "generic_name": "LDO_X",
            "kicad_symbol": "Device:R",
            "kicad_footprint": "Package_TO_SOT_SMD:SOT-23",
            "manufacturer": "",
            "mpn": "LDO1",
            "supplier_sku": "C1",
            "description": "ldo",
            "category": "voltage_regulators",
            "pinout_json": pins,
        }
    )
    ingest_pcbway_seeed_offers(
        dm,
        "LDO_X",
        [{"supplier": "PCBWay", "supplier_sku": "PW-1", "mpn": "LDO1"}],
    )
    row = dm.get_component("LDO_X")
    assert json.loads(row["pinout_json"])[0]["name"] == "VIN"
    offers = dm.list_part_offers("LDO_X")
    assert offers and offers[0]["supplier"] == "PCBWay"
    assert offers[0]["supplier_sku"] == "PW-1"


def test_cat012_refuse_without_licence(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from openhac.database.licensed_cad import store_licensed_cad_file

    assert store_licensed_cad_file(filename="a.step", data=b"step", license_field=None) is None
    dest = store_licensed_cad_file(
        filename="a.step", data=b"step", license_field="CC-BY-4.0", source="snapeda"
    )
    assert dest is not None and dest.is_file()


def test_cat015_alternates_do_not_clone_pinout(tmp_db):
    _, dm = tmp_db
    pins = json.dumps([{"num": "1", "name": "VIN"}, {"num": "2", "name": "GND"}])
    dm.insert_component(
        {
            "generic_name": "TWIN_LDO",
            "kicad_symbol": "Device:R",
            "kicad_footprint": "Package_TO_SOT_SMD:SOT-23",
            "manufacturer": "",
            "mpn": "PRIMARY",
            "supplier_sku": "C-PRI",
            "description": "ldo",
            "category": "voltage_regulators",
            "pinout_json": pins,
        }
    )
    dm.insert_part_alternate(
        {
            "primary_generic": "TWIN_LDO",
            "rank": 1,
            "alternate_mpn": "ALT-MPN",
            "alternate_supplier_sku": "C-ALT",
            "note": "parametric twin",
        }
    )
    dm.insert_part_offer(
        {
            "generic_name": "TWIN_LDO",
            "rank": 2,
            "supplier": "Seeed",
            "supplier_sku": "SEEED-1",
            "mpn": "ALT-MPN",
            "note": "second assembler",
        }
    )
    row = dm.get_component("TWIN_LDO")
    assert json.loads(row["pinout_json"])[0]["name"] == "VIN"
    alts = dm.list_part_alternates("TWIN_LDO")
    assert alts[0]["alternate_supplier_sku"] == "C-ALT"
    # No second components row cloned for the twin SKU.
    assert dm.get_component_by_supplier_sku("C-ALT") is None


def test_cat014_maintainer_snapshot_skip_sync(tmp_db, tmp_path, monkeypatch):
    db_path, dm = tmp_db
    dm.insert_component(_resistor_ready())
    monkeypatch.setenv("OPENHAC_DB_PATH", db_path)
    monkeypatch.setenv("OPENHAC_NO_NETWORK", "1")
    import importlib.util

    script = Path(__file__).resolve().parents[1] / "scripts" / "catalog_snapshot.py"
    spec = importlib.util.spec_from_file_location("catalog_snapshot", script)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    out = tmp_path / "cov.json"
    assert mod.main(["--skip-sync", "-o", str(out)]) == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["schema"] == "openhac.catalog_coverage.v1"
    assert data["compile_ready"] >= 1
    monkeypatch.setenv("OPENHAC_NO_NETWORK", "1")
    monkeypatch.setenv("OPENHAC_COMPILE_GOAL", "fabrication")
    with patch("openhac.database.enrich.enrich_missing_pinouts_from_db") as walker:
        from openhac.database.enrich import network_allowed

        assert network_allowed() is False
        walker.assert_not_called()
