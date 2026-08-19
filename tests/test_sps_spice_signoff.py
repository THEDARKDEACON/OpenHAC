"""SPS — physics-first SPICE sign-off gates."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from openhac.compiler.ngspice_runner import parse_ngspice_op_voltages
from openhac.compiler.spice_gen import generate_spice
from openhac.compiler.spice_models import (
    file_sha256,
    parse_model_record,
    parse_subckt_pin_count,
    reset_spice_model_registry_cache,
    verify_record_file,
)
from openhac.compiler.spice_nodes import assert_no_sanitization_collisions, spice_token
from openhac.core.base import OpenHaCError


def test_sps001_ground_is_node_zero():
    assert spice_token("GND") == "0"
    assert spice_token("VSS") == "0"
    assert spice_token("PGND") == "0"
    assert spice_token("AGND") != "0"


def test_sps004_leading_digit_and_collision():
    assert spice_token("3V3") == "N_3V3"
    with pytest.raises(OpenHaCError, match="SPS-004"):
        assert_no_sanitization_collisions(["A-B", "A_B"])


def test_sps001_generated_deck_uses_zero(tmp_path, monkeypatch):
    class _Net:
        def __init__(self, name: str):
            self.name = name

    class _Pin:
        def __init__(self, num, net):
            self.num = num
            self.number = num
            self.name = str(num)
            self.net = net

    class _Part:
        def __init__(self):
            self.ref = "R1"
            self.refdes = "R1"
            self.value = "1k"
            self.name = "R"
            self.fields = {}
            self.pins = [_Pin("1", _Net("3V3")), _Pin("2", _Net("GND"))]

    class _Circuit:
        parts = [_Part()]

    monkeypatch.setattr("openhac.compiler.spice_gen.get_default_circuit", lambda: _Circuit())
    out = tmp_path / "gnd.cir"
    generate_spice(str(out), analysis_lines=[".op"])
    text = out.read_text(encoding="utf-8")
    assert " R1 N_3V3 0 1k" in f" {text}" or "R1 N_3V3 0 1k" in text
    assert not any(
        ln.split()[:1] == ["R1"] and "GND" in ln.split()[1:-1] for ln in text.splitlines()
    )


def test_sps003_pin_map_order(tmp_path, monkeypatch):
    class _Net:
        def __init__(self, name: str):
            self.name = name

    class _Pin:
        def __init__(self, num, name, net):
            self.num = num
            self.number = num
            self.name = name
            self.net = net

    class _Part:
        def __init__(self):
            self.ref = "U1"
            self.refdes = "U1"
            self.value = "X"
            self.name = "IC"
            self.fields = {
                "Spice_Subckt": "FOO",
                "Spice_Kind": "physics",
                "Spice_Include": "unused.lib",
                "Spice_Pin_Map": json.dumps(
                    [
                        {"num": "2", "name": "B", "subckt_index": 1},
                        {"num": "1", "name": "A", "subckt_index": 2},
                    ]
                ),
            }
            self.pins = [
                _Pin("1", "A", _Net("NA")),
                _Pin("2", "B", _Net("NB")),
            ]

    class _Circuit:
        parts = [_Part()]

    monkeypatch.setattr("openhac.compiler.spice_gen.get_default_circuit", lambda: _Circuit())
    out = tmp_path / "map.cir"
    generate_spice(str(out), analysis_lines=[".op"], signoff=False, allow_behavioral=True)
    text = out.read_text(encoding="utf-8")
    inst = [ln for ln in text.splitlines() if ln.startswith("XU1") or ln.startswith("U1")]
    assert inst
    # pin_map order: B then A
    assert "NB NA FOO" in inst[0]


def test_sps002_unconnected_pin_fails_signoff(tmp_path, monkeypatch):
    class _Net:
        def __init__(self, name: str):
            self.name = name

    class _Pin:
        def __init__(self, num, name, net):
            self.num = num
            self.number = num
            self.name = name
            self.net = net

    class _Part:
        def __init__(self):
            self.ref = "U1"
            self.refdes = "U1"
            self.value = "X"
            self.name = "IC"
            self.fields = {
                "Spice_Subckt": "FOO",
                "Spice_Kind": "physics",
                "Spice_Include": str(tmp_path / "foo.lib"),
                "Spice_Pin_Map": json.dumps(
                    [
                        {"num": "1", "name": "A", "subckt_index": 1},
                        {"num": "2", "name": "B", "subckt_index": 2},
                    ]
                ),
            }
            self.pins = [_Pin("1", "A", _Net("NA"))]  # B missing

    (tmp_path / "foo.lib").write_text(".subckt FOO A B\n.ends\n", encoding="utf-8")

    class _Circuit:
        parts = [_Part()]

    monkeypatch.setattr("openhac.compiler.spice_gen.get_default_circuit", lambda: _Circuit())
    with pytest.raises(OpenHaCError, match="SPS-002"):
        generate_spice(str(tmp_path / "x.cir"), analysis_lines=[".op"], signoff=True, allow_behavioral=True)


def test_sps005_ic_without_model_fails_signoff(tmp_path, monkeypatch):
    class _Net:
        def __init__(self, name: str):
            self.name = name

    class _Pin:
        def __init__(self, num, net):
            self.num = num
            self.net = net

    class _Part:
        def __init__(self):
            self.ref = "U1"
            self.refdes = "U1"
            self.value = "ESP32"
            self.name = "ESP32"
            self.fields = {}
            self.pins = [_Pin("1", _Net("A")), _Pin("2", _Net("B"))]

    class _Circuit:
        parts = [_Part()]

    monkeypatch.setattr("openhac.compiler.spice_gen.get_default_circuit", lambda: _Circuit())
    with pytest.raises(OpenHaCError, match="SPS-005"):
        generate_spice(str(tmp_path / "u.cir"), analysis_lines=[".op"], signoff=True)


def test_sps010_registry_schema():
    with pytest.raises(OpenHaCError, match="SPS-010"):
        parse_model_record({"generic_name": "X"})  # missing kind
    rec = parse_model_record(
        {
            "generic_name": "NMOS_L1",
            "kind": "physics",
            "include": "nmos_l1.cir",
            "subckt": "NMOS_L1",
            "pin_map": [
                {"name": "D", "num": "1", "subckt_index": 1},
                {"name": "G", "num": "2", "subckt_index": 2},
                {"name": "S", "num": "3", "subckt_index": 3},
            ],
            "physics_checks": [
                {
                    "name": "t",
                    "rails": {"G": 3},
                    "probe": "S",
                    "vmin": 0,
                    "vmax": 5,
                    "temp_c": 27,
                }
            ],
        }
    )
    assert rec.kind == "physics"
    assert len(rec.pin_map) == 3


def test_sps011_checksum_mismatch(tmp_path):
    lib = tmp_path / "v.lib"
    lib.write_text(".subckt FOO A B\n.ends\n", encoding="utf-8")
    rec = parse_model_record(
        {
            "mpn": "X",
            "kind": "vendor",
            "include": str(lib),
            "subckt": "FOO",
            "sha256": "0" * 64,
            "pin_map": [
                {"name": "A", "num": "1", "subckt_index": 1},
                {"name": "B", "num": "2", "subckt_index": 2},
            ],
            "physics_checks": [
                {"name": "t", "rails": {}, "probe": "A", "vmin": 0, "vmax": 1, "temp_c": 27}
            ],
        }
    )
    with pytest.raises(OpenHaCError, match="SPS-011"):
        verify_record_file(rec, signoff=True)


def test_sps014_missing_file_signoff(tmp_path):
    rec = parse_model_record(
        {
            "mpn": "X",
            "kind": "physics",
            "include": str(tmp_path / "nope.lib"),
            "subckt": "FOO",
            "pin_map": [
                {"name": "A", "num": "1", "subckt_index": 1},
                {"name": "B", "num": "2", "subckt_index": 2},
            ],
            "physics_checks": [
                {"name": "t", "rails": {}, "probe": "A", "vmin": 0, "vmax": 1, "temp_c": 27}
            ],
        }
    )
    with pytest.raises(OpenHaCError, match="SPS-014"):
        verify_record_file(rec, signoff=True)


def test_sps018_subckt_arity():
    text = ".subckt FOO A B C\n.ends\n"
    assert parse_subckt_pin_count(text, "FOO") == 3


def test_sps021_missing_v1_fails_signoff(tmp_path, monkeypatch):
    class _Net:
        def __init__(self, name: str):
            self.name = name

    class _Pin:
        def __init__(self, num, net):
            self.num = num
            self.net = net

    class _Part:
        def __init__(self):
            self.ref = "R1"
            self.refdes = "R1"
            self.value = "1k"
            self.name = "R"
            self.fields = {}
            self.pins = [_Pin("1", _Net("3V3")), _Pin("2", _Net("GND"))]

    class _Circuit:
        parts = [_Part()]

    monkeypatch.setattr("openhac.compiler.spice_gen.get_default_circuit", lambda: _Circuit())
    with pytest.raises(OpenHaCError, match="SPS-021"):
        generate_spice(
            str(tmp_path / "dc.cir"),
            analysis_lines=[".dc V1 0 5 0.1"],
            signoff=True,
            rails={"3V3": 3.3},
        )


def test_sps032_parse_op_numbers():
    txt = "v(n_3v3) = 3.300000e+00\nv(0) = 0.000000e+00\n"
    d = parse_ngspice_op_voltages(txt)
    assert d["n_3v3"] == pytest.approx(3.3)


def test_sps017_behavioral_refused(tmp_path, monkeypatch):
    class _Net:
        def __init__(self, name: str):
            self.name = name

    class _Pin:
        def __init__(self, num, name, net):
            self.num = num
            self.number = num
            self.name = name
            self.net = net

    lib = tmp_path / "ldo.cir"
    lib.write_text(".subckt LDO_BEH VIN GND EN VOUT\nE1 VOUT GND VALUE={3.3}\n.ends\n", encoding="utf-8")

    class _Part:
        def __init__(self):
            self.ref = "U1"
            self.refdes = "U1"
            self.value = "LDO"
            self.name = "LDO"
            self.fields = {
                "Spice_Subckt": "LDO_BEH",
                "Spice_Kind": "behavioral",
                "Spice_Include": str(lib),
                "Spice_Pin_Map": json.dumps(
                    [
                        {"name": "VIN", "num": "1", "subckt_index": 1},
                        {"name": "GND", "num": "2", "subckt_index": 2},
                        {"name": "EN", "num": "3", "subckt_index": 3},
                        {"name": "VOUT", "num": "4", "subckt_index": 4},
                    ]
                ),
            }
            g = _Net("GND")
            self.pins = [
                _Pin("1", "VIN", _Net("VIN")),
                _Pin("2", "GND", g),
                _Pin("3", "EN", _Net("VIN")),
                _Pin("4", "VOUT", _Net("VOUT")),
            ]

    class _Circuit:
        parts = [_Part()]

    monkeypatch.setattr("openhac.compiler.spice_gen.get_default_circuit", lambda: _Circuit())
    with pytest.raises(OpenHaCError, match="SPS-017"):
        generate_spice(str(tmp_path / "b.cir"), analysis_lines=[".op"], signoff=True, allow_behavioral=False)


@pytest.mark.skipif(shutil.which("ngspice") is None, reason="ngspice not installed")
def test_sps033_generated_divider_op(tmp_path, monkeypatch):
    class _Net:
        def __init__(self, name: str):
            self.name = name

    class _Pin:
        def __init__(self, num, net):
            self.num = num
            self.number = num
            self.name = str(num)
            self.net = net

    mid, vcc, gnd = _Net("MID"), _Net("3V3"), _Net("GND")

    class _R:
        def __init__(self, ref, p1, p2, val):
            self.ref = ref
            self.refdes = ref
            self.value = val
            self.name = "R"
            self.fields = {}
            self.pins = [_Pin("1", p1), _Pin("2", p2)]

    class _Circuit:
        parts = [_R("R1", vcc, mid, "1k"), _R("R2", mid, gnd, "1k")]

    monkeypatch.setattr("openhac.compiler.spice_gen.get_default_circuit", lambda: _Circuit())
    cir = tmp_path / "div.cir"
    generate_spice(
        str(cir),
        analysis_lines=[".op"],
        signoff=True,
        rails={"3V3": 3.3},
        probes=[{"net": "MID", "vmin": 1.5, "vmax": 1.8}],
    )
    from openhac.compiler.ngspice_runner import run_ngspice_headless
    from openhac.compiler.spice_physics import assert_probe_window

    log = Path(run_ngspice_headless(cir, log_path=tmp_path / "div.log"))
    volts = parse_ngspice_op_voltages(log.read_text(encoding="utf-8", errors="replace"))
    assert_probe_window(volts, "MID", 1.5, 1.8)
    text = cir.read_text(encoding="utf-8")
    assert "TNOM=27" in text
    assert " 0 " in text or text.find(" 0\n") or " 0 DC" in text


@pytest.mark.skipif(shutil.which("ngspice") is None, reason="ngspice not installed")
def test_sps016_physics_mosfet_bench(tmp_path):
    from openhac.compiler.spice_models import load_spice_model_registry
    from openhac.compiler.spice_physics import run_record_physics_checks

    reset_spice_model_registry_cache()
    recs = [r for r in load_spice_model_registry() if r.generic_name == "NMOS_L1"]
    assert recs
    results = run_record_physics_checks(recs[0], work_dir=tmp_path)
    assert results and results[0]["passed"]


@pytest.mark.skipif(shutil.which("ngspice") is None, reason="ngspice not installed")
def test_sps034_tmp_vendor_lib_bench(tmp_path, monkeypatch):
    lib = tmp_path / "vendor.lib"
    lib.write_text(
        "\n".join(
            [
                ".subckt VREG VIN GND VOUT",
                "E1 VOUT GND VALUE={3.3}",
                ".ends",
                "",
            ]
        ),
        encoding="utf-8",
    )
    digest = file_sha256(lib)
    rec = parse_model_record(
        {
            "mpn": "FAKE-LDO",
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
                    "name": "vout",
                    "analysis": ".op",
                    "rails": {"VIN": 5.0},
                    "load_ohm": 330,
                    "probe": "VOUT",
                    "vmin": 3.2,
                    "vmax": 3.4,
                    "temp_c": 27,
                }
            ],
        }
    )
    verify_record_file(rec, signoff=True)
    from openhac.compiler.spice_physics import run_record_physics_checks

    out = run_record_physics_checks(rec, work_dir=tmp_path)
    assert out[0]["passed"]


def test_sps034_require_vendor_dir_fails(monkeypatch):
    monkeypatch.delenv("OPENHAC_SPICE_VENDOR_DIR", raising=False)
    from openhac.core.board import Board
    from openhac.core.base import OpenHaCError as E

    b = Board(size_mm=(10.0, 10.0), quality_gates={})
    with pytest.raises(E, match="SPS-034"):
        b.simulate("x", spice_signoff=True, require_vendor_models=True, run_ngspice=False)
