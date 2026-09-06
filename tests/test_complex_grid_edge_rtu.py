"""Full-suite grid-edge RTU: vendor parse → catalog → compile (no _offline_parts).

Default path uses recorded Digi-Key / jlcsearch JSON (CODE-002). Live HTTP is
gated on ``OPENHAC_TEST_VENDOR_LIVE=1`` and is skipped in CI.
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest

from openhac.core.circuit import reset_default_circuit
from openhac.database.pin_policy import pinout_is_named, should_store_vendor_pinout
from openhac.database.vendor_apis import DigiKeyAPI, JLCPCBAPI

_REPO = Path(__file__).resolve().parents[1]
_EXAMPLE = _REPO / "examples" / "complex_grid_edge_rtu.py"
_CASSETTE_PY = _REPO / "tests" / "fixtures" / "vendor" / "grid_edge_rtu_cassettes.py"
_CASSETTE_DIR = _CASSETTE_PY.parent


def _cassettes():
    spec = importlib.util.spec_from_file_location("grid_edge_rtu_cassettes", _CASSETTE_PY)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_example():
    spec = importlib.util.spec_from_file_location("complex_grid_edge_rtu", _EXAMPLE)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_example_does_not_import_offline_parts():
    src = _EXAMPLE.read_text(encoding="utf-8")
    assert "from _offline_parts" not in src
    assert "import _offline_parts" not in src


def test_digikey_parse_named_ic_pinout():
    cas = _cassettes()
    rec = next(r for r in cas.digikey_records() if r["generic_name"] == "AMS1117_3V3")
    raw = json.loads(json.dumps(rec["product"]))
    info = DigiKeyAPI(client_id="cassette", client_secret="cassette")._parse_product(raw)
    assert info.mpn == "AMS1117-3.3"
    names = {str(p["name"]) for p in info.pinout}
    assert names == {"VIN", "GND", "VOUT"}
    assert pinout_is_named(info.pinout, category="PMIC - Voltage Regulators", generic_name="AMS1117_3V3")
    assert should_store_vendor_pinout(info.pinout, category="regulator", generic_name="AMS1117_3V3")


def test_jlcsearch_parse_and_derive_passive_names():
    cas = _cassettes()
    from openhac.database.sync_jlc import _component_row_from_jlc_item, _derive_generic_name

    api = JLCPCBAPI(api_key=None)
    blob = json.loads(json.dumps(cas.jlcsearch_payload()))
    ten_k = next(x for x in blob["resistors"] if x["resistance"] == 10000)
    info = api._parse_jlcsearch_item(ten_k)
    assert info.supplier_sku == "C17513"
    assert info.package == "0805"
    assert info.pinout is None
    assert _derive_generic_name("resistors", ten_k) == "R_10k_0805"
    packed = _component_row_from_jlc_item("resistors", ten_k)
    assert packed is not None
    assert packed["generic_name"] == "R_10k_0805"
    assert "R_0805" in packed["kicad_footprint"]
    pins = json.loads(packed["pinout_json"])
    assert len(pins) == 2
    assert _derive_generic_name("resistors", next(x for x in blob["resistors"] if x["resistance"] == 4700)) == "R_4k7_0805"
    cap = next(x for x in blob["capacitors"] if x["capacitance"] == 100e-9)
    assert _derive_generic_name("capacitors", cap) == "C_100nF_0603"
    led = blob["leds"][0]
    assert _derive_generic_name("leds", led) == "LED_GREEN_0805"
    fuse = blob["fuses"][0]
    assert _derive_generic_name("fuses", fuse) == "FUSE_0805"
    fuse_row = _component_row_from_jlc_item("fuses", fuse)
    assert fuse_row is not None
    assert "Fuse_0805" in fuse_row["kicad_footprint"]


def test_cat004_jlc_pin_count_not_stored_on_ic():
    api = JLCPCBAPI(api_key=None)
    info = api._parse_product(
        {
            "componentCode": "FAKEIC",
            "componentId": "C9",
            "componentTypeEn": "ic",
            "package": "SOIC-8",
            "componentSpecification": {"pinCount": 8},
        }
    )
    assert info.pinout
    assert not should_store_vendor_pinout(info.pinout, category="ic", generic_name="FAKEIC")


def test_cassette_json_roundtrip(tmp_path):
    cas = _cassettes()
    dk_path, jlc_path = cas.dump_cassette_json(tmp_path)
    dk = json.loads(dk_path.read_text(encoding="utf-8"))
    jlc = json.loads(jlc_path.read_text(encoding="utf-8"))
    assert len(dk) >= 20
    assert "resistors" in jlc and "capacitors" in jlc
    parsed = DigiKeyAPI(client_id="x", client_secret="y")._parse_product(dk[0]["product"])
    assert parsed.pinout


@pytest.fixture()
def vendor_catalog(tmp_db, tmp_path, monkeypatch):
    db_path, dm = tmp_db
    cas = _cassettes()
    cassette_dir = tmp_path / "cassettes"
    cas.dump_cassette_json(cassette_dir)
    monkeypatch.setenv("OPENHAC_NO_NETWORK", "1")
    monkeypatch.setenv("OPENHAC_DB_PATH", db_path)
    monkeypatch.setenv("OPENHAC_SKIP_LAYOUT", "1")
    counts = cas.ingest_vendor_cassettes(dm, cassette_dir=cassette_dir)
    assert counts["digikey"] >= 20
    assert counts["jlcsearch"] >= 10
    from openhac.core.base import Component

    monkeypatch.setattr(Component, "db", dm)
    return db_path, dm


def _compile_variant(example, tmp_path, variant: str):
    reset_default_circuit()
    board = example.build_board(variant=variant)
    out = tmp_path / variant
    out.mkdir(parents=True, exist_ok=True)
    board.compile(
        project_name=f"grid_edge_{variant}",
        generate_bom=True,
        auto_route=False,
        export_schematic=False,
        output_dir=out,
        compile_profile="logic",
        source_script_path=_EXAMPLE,
    )
    return board, out


def test_grid_edge_rtu_full_suite_from_vendor_cassettes(vendor_catalog, tmp_path):
    _db_path, dm = vendor_catalog
    row = dm.get_component("AMS1117_3V3")
    assert row is not None
    pins = json.loads(row["pinout_json"])
    assert {p["name"] for p in pins} == {"VIN", "GND", "VOUT"}
    assert row.get("pinout_source") in ("digikey", "digikey")
    assert dm.get_component("R_10k_0805")
    assert dm.get_component("R_4k7_0805")
    assert dm.get_component("AD620")
    assert dm.get_component("ESP32_S3_WROOM_1")

    example = _load_example()
    board, out = _compile_variant(example, tmp_path, "field")

    eco = out / "grid_edge_field.openhac-eco.json"
    assert eco.is_file()
    eco_data = json.loads(eco.read_text(encoding="utf-8"))
    assert eco_data.get("schema") == "openhac.eco.v1"
    assert eco_data.get("current", {}).get("refs")

    bom = (out / "grid_edge_field.csv").read_text(encoding="utf-8")
    assert "ESP32_S3_WROOM_1" in bom or "ESP32" in bom
    assert "AD620" in bom

    from openhac.database.catalog_lock import collect_lock_entries

    lock_rows = collect_lock_entries(board, db=dm)
    gns = {r["generic_name"] for r in lock_rows}
    assert "AMS1117_3V3" in gns
    assert "AD620" in gns
    assert any(r.get("pinout_hash") for r in lock_rows)

    assert board._spice_island_names == ["AnalogFrontEnd"]
    assert len(getattr(board, "_declared_testpoints", []) or []) >= 5

    from openhac.compiler.spice_models import collect_spice_coverage
    from openhac.core.circuit import default_circuit

    cov = collect_spice_coverage(
        list(default_circuit.parts),
        island_names=frozenset({"AnalogFrontEnd"}),
    )
    modeled = {r["value"] for r in cov if r["status"] == "modeled"}
    omitted = {r["value"] for r in cov if r["status"] == "omitted"}
    assert any("AD620" in str(v) for v in modeled)
    assert any("ESP32" in str(v) or "STM32" in str(v) for v in omitted)

    _, lite_out = _compile_variant(example, tmp_path, "lite")
    lite_bom = (lite_out / "grid_edge_lite.csv").read_text(encoding="utf-8")
    assert lite_bom != bom
    assert "Yes" in lite_bom


@pytest.mark.skipif(
    os.environ.get("OPENHAC_TEST_VENDOR_LIVE", "").strip().lower() not in ("1", "true", "yes", "on"),
    reason="live vendor HTTP; set OPENHAC_TEST_VENDOR_LIVE=1",
)
def test_optional_live_vendor_lookup():
    from openhac.database.vendor_apis import lookup_part_live

    info = lookup_part_live("RC0805FR-0710KL")
    assert info is not None
    assert info.mpn or info.supplier_sku
