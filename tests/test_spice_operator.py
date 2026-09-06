"""SPS-050…057 operator-path tests (no live vendor HTTP)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from openhac.compiler.spice_models import (
    file_sha256,
    looks_encrypted_or_ltspice_only,
    parse_model_record,
    reset_spice_model_registry_cache,
    verify_record_file,
    verify_vendor_dir_records,
)
from openhac.core.base import OpenHaCError


def test_sps050_coverage_cli_divider(capsys):
    from argparse import Namespace

    from openhac.cli import cmd_spice_coverage

    script = Path(__file__).resolve().parents[1] / "examples" / "spice_island_golden.py"
    cmd_spice_coverage(
        Namespace(
            script=str(script),
            as_json=True,
        )
    )
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["schema"] == "openhac.spice_coverage.v1"
    statuses = {r["ref"]: r["status"] for r in data["coverage"]}
    assert "primitive" in statuses.values()


def test_sps050_unmodeled_ldo_and_header():
    from openhac.compiler.spice_models import collect_spice_coverage

    class P:
        def __init__(self, ref, value, **fields):
            self.refdes = ref
            self.ref = ref
            self.value = value
            self.name = value
            self.fields = fields

    parts = [
        P("R1", "10k"),
        P("U1", "AMS1117", category="Regulator"),
        P("J1", "HDR", category="connector"),
    ]
    rows = {r["ref"]: r for r in collect_spice_coverage(parts)}
    assert rows["R1"]["status"] == "primitive"
    assert rows["U1"]["status"] == "unmodeled"
    assert rows["J1"]["status"] == "omitted"


def test_sps052_hashed_lib_pass(tmp_path, monkeypatch):
    lib = tmp_path / "v.lib"
    lib.write_text(".subckt VREG VIN GND VOUT\nR1 VIN VOUT 1\n.ends\n", encoding="utf-8")
    digest = file_sha256(lib)
    rec = parse_model_record(
        {
            "mpn": "FAKE",
            "kind": "vendor",
            "include": str(lib),
            "subckt": "VREG",
            "sha256": digest,
            "license": "LicenseRef-Test",
            "pin_map": [
                {"name": "VIN", "num": "1", "subckt_index": 1},
                {"name": "GND", "num": "2", "subckt_index": 2},
                {"name": "VOUT", "num": "3", "subckt_index": 3},
            ],
            "physics_checks": [
                {
                    "name": "x",
                    "analysis": ".op",
                    "rails": {"VIN": 5},
                    "probe": "VOUT",
                    "vmin": 0,
                    "vmax": 10,
                }
            ],
        }
    )
    assert verify_record_file(rec, signoff=True)


def test_sps052_flipped_hash_fails(tmp_path):
    lib = tmp_path / "v.lib"
    lib.write_text(".subckt VREG VIN GND VOUT\nR1 VIN VOUT 1\n.ends\n", encoding="utf-8")
    rec = parse_model_record(
        {
            "mpn": "FAKE",
            "kind": "vendor",
            "include": str(lib),
            "subckt": "VREG",
            "sha256": "ab" * 32,
            "license": "LicenseRef-Test",
            "pin_map": [
                {"name": "VIN", "num": "1", "subckt_index": 1},
                {"name": "GND", "num": "2", "subckt_index": 2},
                {"name": "VOUT", "num": "3", "subckt_index": 3},
            ],
            "physics_checks": [
                {
                    "name": "x",
                    "analysis": ".op",
                    "rails": {"VIN": 5},
                    "probe": "VOUT",
                    "vmin": 0,
                    "vmax": 10,
                }
            ],
        }
    )
    with pytest.raises(OpenHaCError, match="sha256"):
        verify_record_file(rec, signoff=True)


def test_sps052_unset_vendor_dir_fails_vendor(monkeypatch):
    monkeypatch.delenv("OPENHAC_SPICE_VENDOR_DIR", raising=False)
    rec = parse_model_record(
        {
            "mpn": "FAKE",
            "kind": "vendor",
            "include": "${OPENHAC_SPICE_VENDOR_DIR}/missing.lib",
            "subckt": "VREG",
            "sha256": "ab" * 32,
            "license": "LicenseRef-Test",
            "pin_map": [
                {"name": "VIN", "num": "1", "subckt_index": 1},
                {"name": "GND", "num": "2", "subckt_index": 2},
                {"name": "VOUT", "num": "3", "subckt_index": 3},
            ],
            "physics_checks": [
                {
                    "name": "x",
                    "analysis": ".op",
                    "rails": {"VIN": 5},
                    "probe": "VOUT",
                    "vmin": 0,
                    "vmax": 10,
                }
            ],
        }
    )
    with pytest.raises(OpenHaCError, match="SPS-011"):
        verify_record_file(rec, signoff=True)


def test_sps052_physics_only_verify_exits_ok(monkeypatch):
    monkeypatch.delenv("OPENHAC_SPICE_VENDOR_DIR", raising=False)
    reset_spice_model_registry_cache()
    errors = verify_vendor_dir_records()
    assert errors == []


def test_sps051_download_page_ignored(tmp_path):
    rec = {
        "mpn": "AD620ANZ",
        "kind": "physics",
        "include": "ad620.cir",
        "subckt": "AD620",
        "license": "Apache-2.0",
        "notes": {
            "text": "Not a vendor part.",
            "download_page": "https://www.analog.com/en/products/ad620.html",
        },
        "pin_map": [
            {"name": n, "num": str(i), "subckt_index": i}
            for i, n in enumerate(["RG1", "INN", "INP", "VSM", "REF", "OUT", "VSP", "RG2"], start=1)
        ],
        "physics_checks": [
            {
                "name": "unity_gain_1v",
                "analysis": ".op",
                "rails": {"INP": 1.0},
                "probe": "OUT",
                "vmin": 0.0,
                "vmax": 10.0,
            }
        ],
    }
    with patch("urllib.request.urlopen") as mock_open:
        parsed = parse_model_record(rec)
        mock_open.assert_not_called()
    assert "http" not in (parsed.notes or "").lower()
    path = tmp_path / "ov.json"
    path.write_text(json.dumps({"models": [rec]}), encoding="utf-8")
    with patch("urllib.request.urlopen") as mock_open:
        from openhac.compiler.spice_models import _load_json_records

        _load_json_records(path)
        mock_open.assert_not_called()


def test_sps054_asc_refused(tmp_path):
    p = tmp_path / "x.asc"
    p.write_text("Version 4\nSHEET 1 880 680\n", encoding="utf-8")
    rec = parse_model_record(
        {
            "mpn": "X",
            "kind": "vendor",
            "include": str(p),
            "subckt": "X",
            "sha256": file_sha256(p),
            "license": "x",
            "pin_map": [
                {"name": "A", "num": "1", "subckt_index": 1},
                {"name": "B", "num": "2", "subckt_index": 2},
            ],
            "physics_checks": [
                {
                    "name": "x",
                    "analysis": ".op",
                    "rails": {"A": 1},
                    "probe": "B",
                    "vmin": 0,
                    "vmax": 1,
                }
            ],
        }
    )
    with pytest.raises(OpenHaCError, match="SPS-054"):
        verify_record_file(rec, signoff=True)


def test_sps054_encrypted_sniff(tmp_path):
    p = tmp_path / "enc.lib"
    p.write_bytes(b"* Encrypted\n\x00\x01\x02secret")
    assert looks_encrypted_or_ltspice_only(p) is not None
    rec = parse_model_record(
        {
            "mpn": "X",
            "kind": "vendor",
            "include": str(p),
            "subckt": "X",
            "sha256": file_sha256(p),
            "license": "x",
            "pin_map": [
                {"name": "A", "num": "1", "subckt_index": 1},
                {"name": "B", "num": "2", "subckt_index": 2},
            ],
            "physics_checks": [
                {
                    "name": "x",
                    "analysis": ".op",
                    "rails": {"A": 1},
                    "probe": "B",
                    "vmin": 0,
                    "vmax": 1,
                }
            ],
        }
    )
    with pytest.raises(OpenHaCError, match="SPS-054"):
        verify_record_file(rec, signoff=True)


def test_sps054_plain_ascii_lib_ok(tmp_path):
    p = tmp_path / "ok.lib"
    p.write_text(".subckt X A B\nR1 A B 1\n.ends\n", encoding="utf-8")
    rec = parse_model_record(
        {
            "mpn": "X",
            "kind": "vendor",
            "include": str(p),
            "subckt": "X",
            "sha256": file_sha256(p),
            "license": "x",
            "simulator": "ngspice",
            "pin_map": [
                {"name": "A", "num": "1", "subckt_index": 1},
                {"name": "B", "num": "2", "subckt_index": 2},
            ],
            "physics_checks": [
                {
                    "name": "x",
                    "analysis": ".op",
                    "rails": {"A": 1},
                    "probe": "B",
                    "vmin": 0,
                    "vmax": 1,
                }
            ],
        }
    )
    assert verify_record_file(rec, signoff=True)


def test_sps055_stamp_on_get_component(tmp_db, monkeypatch):
    reset_spice_model_registry_cache()
    _, dm = tmp_db
    dm.insert_component(
        {
            "generic_name": "NMOS_L1",
            "kicad_symbol": "Device:Q_NMOS_GSD",
            "kicad_footprint": "Package_TO_SOT_SMD:SOT-23",
            "manufacturer": "",
            "mpn": "OPENHAC-NMOS-L1",
            "supplier_sku": "C0",
            "description": "nmos",
            "category": "mosfets",
        }
    )
    row = dm.get_component("NMOS_L1")
    assert row.get("spice_include")
    assert row.get("spice_subckt") == "NMOS_L1"


def test_sps055_no_bundled_does_not_stamp(tmp_db, monkeypatch):
    monkeypatch.setenv("OPENHAC_NO_BUNDLED_SPICE_MODELS", "1")
    reset_spice_model_registry_cache()
    _, dm = tmp_db
    dm.insert_component(
        {
            "generic_name": "NMOS_L1",
            "kicad_symbol": "Device:Q_NMOS_GSD",
            "kicad_footprint": "Package_TO_SOT_SMD:SOT-23",
            "manufacturer": "",
            "mpn": "OPENHAC-NMOS-L1",
            "supplier_sku": "C0",
            "description": "nmos",
            "category": "mosfets",
        }
    )
    row = dm.get_component("NMOS_L1")
    assert not row.get("spice_include")
    reset_spice_model_registry_cache()


@pytest.mark.skipif(
    __import__("shutil").which("ngspice") is None, reason="ngspice not installed"
)
def test_sps053_physics_diode_bench(tmp_path):
    from openhac.compiler.spice_models import load_spice_model_registry
    from openhac.compiler.spice_physics import run_record_physics_checks

    reset_spice_model_registry_cache()
    recs = [r for r in load_spice_model_registry() if r.generic_name == "D_1N4007"]
    assert recs
    assert "not a vendor part" in recs[0].notes.lower()
    out = run_record_physics_checks(recs[0], work_dir=tmp_path)
    assert out and out[0]["passed"]


@pytest.mark.skipif(
    __import__("shutil").which("ngspice") is None, reason="ngspice not installed"
)
def test_sps053_physics_inamp_and_opto(tmp_path):
    from openhac.compiler.spice_models import load_spice_model_registry
    from openhac.compiler.spice_physics import run_record_physics_checks

    reset_spice_model_registry_cache()
    names = {"AD620", "OPTO_PC817"}
    recs = [r for r in load_spice_model_registry() if r.generic_name in names]
    assert {r.generic_name for r in recs} == names
    for rec in recs:
        assert "not a vendor part" in rec.notes.lower()
        out = run_record_physics_checks(rec, work_dir=tmp_path)
        assert out and out[0]["passed"]


def test_sps057_http_fetch_still_out_of_scope():
    text = Path("docs/internal/IMPLEMENTATION_STATUS.md").read_text(encoding="utf-8")
    assert "HTTP fetch of vendor SPICE" in text
    assert "SPS-019" in text


def test_sps056_user_guide_operator_path():
    text = Path("docs/USER_GUIDE.md").read_text(encoding="utf-8")
    assert "OPENHAC_SPICE_VENDOR_DIR" in text
    assert "openhac spice verify-vendor-dir" in text
    assert "--spice-signoff" in text
    assert "spice_island_golden.py" in text
    assert "curl http" not in text.lower()
    assert "curl a .lib" not in text.lower()
