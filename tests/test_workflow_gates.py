"""Workflow gates: ECO / LOCK / MFG / PWR / PIN / VAR / LIVE-010 / PLC / TST / GLD."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from openhac.compiler.eco import (
    ECO_SCHEMA,
    diff_snapshots,
    overlay_drops,
    write_eco_report,
)
from openhac.compiler.export_jlc import export_jlc_pack, is_lcsc_sku, jlc_bom_rows_from_openhac
from openhac.compiler.kicad_artwork import FpPose, KicadArtworkOverlay, TrackSeg
from openhac.compiler.kicad_live import discover_kicad_api_sockets, try_pcb_revert_via_ipc
from openhac.compiler.pinout_init import build_pinout_stub, write_pinout_overlay
from openhac.compiler.placement_intent import check_overlay_placement, pose_outside_outline
from openhac.core.exceptions import (
    CatalogLockError,
    JlcExportError,
    PinoutAuthoringError,
    PlacementIntentError,
)
from openhac.database.catalog_lock import (
    LOCK_SCHEMA,
    compare_lock_to_bom,
    collect_lock_entries,
    enforce_lock,
    write_lockfile,
)
from openhac.database.pin_policy import pinout_hash, two_terminal_pinout
from openhac.compiler.rule_check import DRCViolationError, ERCPowerBudgetError, run_drc


def _resistor(name: str, *, sku: str = "C17513"):
    from openhac.core.base import Component

    return Component(
        name,
        {
            "generic_name": name,
            "category": "resistors",
            "kicad_symbol": "Device:R",
            "kicad_footprint": "Resistor_SMD:R_0805_2012Metric",
            "supplier_sku": sku,
            "mpn": "RC0805FR-0710KL",
            "pinout_json": json.dumps(two_terminal_pinout()),
        },
        pins={"1": ("1", "passive"), "2": ("2", "passive")},
        footprint="Resistor_SMD:R_0805_2012Metric",
    )


def test_eco001_diff_and_overlay_drop(tmp_path):
    prev = {
        "refs": {"R1": {"value": "10k", "footprint": "R_0805", "sku": "C1", "dnp": False}, "R2": {"value": "1k", "footprint": "R_0805", "sku": "C2", "dnp": False}},
        "nets": ["GND", "GONE", "3V3"],
        "pinout_grades": {"R_A": "warehouse"},
    }
    cur = {
        "refs": {"R1": {"value": "10k", "footprint": "R_0805", "sku": "C1", "dnp": False}, "R3": {"value": "2k", "footprint": "R_0805", "sku": "C3", "dnp": False}},
        "nets": ["GND", "3V3"],
        "pinout_grades": {"R_A": "compile_ready"},
    }
    d = diff_snapshots(prev, cur)
    assert "R3" in d["added_refs"]
    assert "R2" in d["removed_refs"]
    assert "GONE" in d["nets_vanished"]
    assert d["pinout_grade_changes"][0]["to"] == "compile_ready"

    ov = KicadArtworkOverlay(tracks=[TrackSeg(1, 2, 3, 4, 0.25, "F.Cu", "GONE")])
    cu, _w = overlay_drops(ov, {"GND", "3V3"})
    assert {"kind": "track", "net": "GONE"} in cu

    write_eco_report(tmp_path, "demo", snapshot=cur)
    data = json.loads((tmp_path / "demo.openhac-eco.json").read_text(encoding="utf-8"))
    assert data["schema"] == ECO_SCHEMA
    assert data["added_refs"] == []
    assert "R3" in data["current"]["refs"]
    write_eco_report(tmp_path, "demo", snapshot=cur)
    data2 = json.loads((tmp_path / "demo.openhac-eco.json").read_text(encoding="utf-8"))
    assert data2["source_of_truth"] == "native_graph"
    assert data2["added_refs"] == []
    assert data2 == data
    later = {
        "refs": {"R1": cur["refs"]["R1"], "R9": {"value": "x", "footprint": "R_0805", "sku": "C9", "dnp": False}},
        "nets": ["GND", "3V3"],
        "pinout_grades": {"R_A": "compile_ready"},
    }
    write_eco_report(tmp_path, "demo", snapshot=later)
    data3 = json.loads((tmp_path / "demo.openhac-eco.json").read_text(encoding="utf-8"))
    assert "R9" in data3["added_refs"]
    assert "R3" in data3["removed_refs"]
    assert data3.get("baseline") == "previous_eco"


def test_lock001_mismatch_and_require(tmp_path, tmp_db, monkeypatch):
    from openhac.core.circuit import reset_default_circuit
    from openhac.core.board import Board
    from openhac.core.base import Component, Module
    from openhac.core.net import Net

    reset_default_circuit()
    _, dm = tmp_db
    row = {
        "generic_name": "R_LOCK",
        "category": "resistors",
        "kicad_symbol": "Device:R",
        "kicad_footprint": "Resistor_SMD:R_0805_2012Metric",
        "supplier_sku": "C2",
        "mpn": "RC0805",
        "pinout_json": json.dumps(two_terminal_pinout()),
        "manufacturer": "",
        "description": "lock",
    }
    dm.insert_component(row)
    monkeypatch.setattr(Component, "db", dm)

    class Node(Module):
        def __init__(self):
            super().__init__("N")
            r = self.add(_resistor("R_LOCK", sku="C2"))
            vcc, gnd = Net("3V3"), Net("GND")
            r[1] += vcc
            r[2] += gnd

    board = Board(size_mm=(20, 20), compile_goal="fabrication", strict=False, strict_kicad=False)
    board.add_module(Node())
    entries = collect_lock_entries(board, db=dm)
    locked = json.loads(json.dumps(entries))
    locked[0]["sku"] = "C1"
    lock_path = tmp_path / "openhac.lock"
    write_lockfile(lock_path, locked, project="demo")
    assert json.loads(lock_path.read_text())["schema"] == LOCK_SCHEMA
    with pytest.raises(CatalogLockError, match="SKU"):
        enforce_lock(board, lock_path, fail_closed=True)

    empty = tmp_path / "nolock"
    empty.mkdir()
    (empty / "board.py").write_text("# lock missing\n", encoding="utf-8")
    with pytest.raises(CatalogLockError, match="require-lock"):
        from openhac.compiler.compile_pipeline import CompileState, phase_catalog_lock

        st = CompileState(
            board=board,
            project_name="demo",
            generate_bom=False,
            auto_route=False,
            export_schematic=False,
            allow_risky_part_lookups=True,
            kicad_sch_erc=False,
            kicad_sch_erc_format="report",
            source_script_path=str(empty / "board.py"),
            output_dir=empty,
            release_zip_path=None,
            require_lock=True,
        )
        phase_catalog_lock(st)


def test_lock001_write_does_not_http(tmp_path, monkeypatch):
    """LOCK-001: lock write is local; mocked HTTP must not run."""
    from openhac.database.catalog_lock import write_lockfile

    def _boom(*_a, **_k):
        raise AssertionError("LOCK-001 must not HTTP")

    monkeypatch.setattr("urllib.request.urlopen", _boom)
    monkeypatch.setattr("urllib.request.Request", _boom)
    dest = tmp_path / "openhac.lock"
    write_lockfile(
        dest,
        [{"generic_name": "R", "sku": "C1", "mpn": "X", "pinout_hash": "ab", "footprint": "F", "catalog_tier": "compile_ready"}],
        project="offline",
    )
    assert dest.is_file()
    assert json.loads(dest.read_text())["schema"] == LOCK_SCHEMA


def test_lock001_compare_hash():
    h = pinout_hash(two_terminal_pinout())
    assert len(h) == 64
    msgs = compare_lock_to_bom(
        [{"generic_name": "R", "sku": "C1", "pinout_hash": h, "footprint": "F"}],
        [{"generic_name": "R", "sku": "C1", "pinout_hash": "dead", "footprint": "F"}],
    )
    assert any("pinout hash" in m for m in msgs)


def test_mfg010_jlc_bom_strict(tmp_path):
    bom = tmp_path / "board.csv"
    bom.write_text(
        "Reference,Value,Footprint,Supplier_SKU,DNP\n"
        "R1,10k,Resistor_SMD:R_0805_2012Metric,C17513,No\n",
        encoding="utf-8",
    )
    out = tmp_path / "jlc"
    written = export_jlc_pack(bom, out, strict=True)
    text = written["bom"].read_text(encoding="utf-8")
    assert "Comment" in text and "Designator" in text
    assert "C17513" in text
    assert is_lcsc_sku("C17513")
    rows = jlc_bom_rows_from_openhac(
        [{"Reference": "R2", "Value": "1k", "Footprint": "R_0805", "Supplier_SKU": ""}]
    )
    with pytest.raises(JlcExportError, match="missing LCSC"):
        from openhac.compiler.export_jlc import write_jlc_bom

        write_jlc_bom(rows, tmp_path / "bad.csv", strict=True)


def test_pwr010_rail_overdraw():
    from openhac.core.circuit import reset_default_circuit
    from openhac.core.board import Board
    from openhac.core.base import Module
    from openhac.core.net import Net
    from openhac.compiler.rule_check import _run_power_tree

    reset_default_circuit()

    class Load(Module):
        def __init__(self):
            super().__init__("Load")
            self.draws_from("3V3", amp=0.2)
            r = self.add(_resistor("R_PWR"))
            vcc, gnd = Net("3V3"), Net("GND")
            r[1] += vcc
            r[2] += gnd

    board = Board(size_mm=(20, 20), compile_goal="handoff", strict=False, strict_kicad=False)
    board.add_module(Load())
    board.declare_rail("3V3", voltage_v=3.3, max_amp=0.1)
    from openhac.compiler.rule_check import _run_power_tree

    with pytest.raises(ERCPowerBudgetError, match="PWR-010"):
        _run_power_tree(board)

    reset_default_circuit()

    class Light(Module):
        def __init__(self):
            super().__init__("Light")
            self.draws_from("3V3", ma=50)
            r = self.add(_resistor("R_PWR2"))
            vcc, gnd = Net("3V3"), Net("GND")
            r[1] += vcc
            r[2] += gnd

    board2 = Board(size_mm=(20, 20), compile_goal="handoff", strict=False, strict_kicad=False)
    board2.add_module(Light())
    board2.declare_rail("3V3", voltage_v=3.3, max_amp=0.1)
    _run_power_tree(board2)


def test_pin001_named_and_refuse_numeric(tmp_db, monkeypatch, tmp_path):
    from openhac.core.base import Component

    _, dm = tmp_db
    pins = [
        {"num": "8", "name": "VDD", "type": "power_in"},
        {"num": "9", "name": "SDA", "type": "bidirectional"},
    ]
    dm.insert_component(
        {
            "generic_name": "MCU_CHIP",
            "category": "microcontrollers",
            "kicad_symbol": "NameShift:Chip",
            "kicad_footprint": "Package_DIP:DIP-8_W7.62mm",
            "supplier_sku": "C9",
            "mpn": "CHIP",
            "pinout_json": json.dumps(pins),
            "manufacturer": "",
            "description": "named",
        }
    )
    monkeypatch.setattr(Component, "db", dm)
    stub = build_pinout_stub("MCU_CHIP", db=dm)
    assert stub["pinout_hash"]
    assert stub["pinout"][0]["name"] != stub["pinout"][0]["num"] or stub["pinout"][0]["name"] == "VDD"
    dest = tmp_path / "chip.json"
    write_pinout_overlay(stub, dest)
    assert dest.is_file()

    with pytest.raises(PinoutAuthoringError, match="numeric-only"):
        build_pinout_stub(
            "MCU_FAKE",
            db=dm,
            kicad_pinout=[{"num": str(i), "name": str(i), "type": "bidirectional"} for i in range(1, 9)],
        )


def test_var001_two_variants_different_bom(tmp_path, monkeypatch):
    from openhac.core.circuit import reset_default_circuit
    from openhac.core.board import Board
    from openhac.core.base import Module
    from openhac.core.net import Net

    monkeypatch.setenv("OPENHAC_SKIP_LAYOUT", "1")

    def _build(variant: str):
        reset_default_circuit()
        vcc, gnd = Net("3V3"), Net("GND")

        class Core(Module):
            def __init__(self):
                super().__init__("Core")
                r = self.add(_resistor("R_CORE"))
                r[1] += vcc
                r[2] += gnd

        class Extra(Module):
            def __init__(self):
                super().__init__("Extra")
                self.include_in_variants("full")
                c = self.add(_resistor("R_EXTRA", sku="C99"))
                c[1] += vcc
                c[2] += gnd

        board = Board(
            size_mm=(30, 20),
            compile_goal="handoff",
            strict=False,
            strict_kicad=False,
            variant=variant,
        )
        board.add_module(Core())
        board.add_module(Extra())
        board.compile(
            project_name=f"var_{variant}",
            generate_bom=True,
            auto_route=False,
            output_dir=tmp_path / variant,
            compile_profile="logic",
        )
        return (tmp_path / variant / f"var_{variant}.csv").read_text(encoding="utf-8")

    full = _build("full")
    lite = _build("lite")
    assert full != lite
    assert "Yes" in lite
    man = json.loads((tmp_path / "full" / "var_full.openhac-manifest.json").read_text(encoding="utf-8"))
    assert man.get("variant") == "full"


def test_live010_ipc_best_effort(tmp_path):
    pcb = tmp_path / "b.kicad_pcb"
    pcb.write_text("(kicad_pcb)\n", encoding="utf-8")
    none = try_pcb_revert_via_ipc(pcb, sockets=[])
    assert none["attempted"] is False
    assert none["reloaded"] is False
    assert none["schematic_reload"] is False

    sock_dir = tmp_path / "kicad"
    sock_dir.mkdir()
    sock = sock_dir / "api-1.sock"
    sock.write_text("", encoding="utf-8")
    found = discover_kicad_api_sockets(root=sock_dir)
    assert sock in found

    client = MagicMock()
    client.revert_pcb.return_value = True
    ok = try_pcb_revert_via_ipc(pcb, sockets=found, client=client)
    assert ok["attempted"] is True
    assert ok["reloaded"] is True

    boom = MagicMock()
    boom.revert_pcb.side_effect = RuntimeError("ipc down")
    err = try_pcb_revert_via_ipc(pcb, sockets=found, client=boom)
    assert err["reloaded"] is False
    assert "ipc_error" in err["reason"]


def test_plc001_outside_and_overlap():
    board = SimpleNamespace(size_mm=(20.0, 20.0))
    outside = KicadArtworkOverlay(
        footprints={"R1": FpPose(ref="R1", x=999.0, y=999.0, rot=0.0)}
    )
    with pytest.raises(PlacementIntentError, match="outside"):
        check_overlay_placement(outside, board, fail=True)
    stacked = KicadArtworkOverlay(
        footprints={
            "R1": FpPose(ref="R1", x=5.0, y=5.0, rot=0.0),
            "R2": FpPose(ref="R2", x=5.0, y=5.0, rot=0.0),
        }
    )
    with pytest.raises(PlacementIntentError, match="courtyard"):
        check_overlay_placement(stacked, board, fail=True)
    ok = KicadArtworkOverlay(
        footprints={
            "R1": FpPose(ref="R1", x=5.0, y=5.0, rot=0.0),
            "R2": FpPose(ref="R2", x=12.0, y=12.0, rot=0.0),
        }
    )
    assert check_overlay_placement(ok, board, fail=True) == []
    assert pose_outside_outline(FpPose("R9", 100, 100), 20, 20)


def test_tst001_declared_missing(monkeypatch):
    from openhac.core.circuit import reset_default_circuit
    from openhac.core.board import Board
    from openhac.core.base import Module
    from openhac.core.net import Net
    from openhac.compiler.rule_check import DRCViolationError

    reset_default_circuit()
    vcc, gnd = Net("3V3"), Net("GND")

    class Node(Module):
        def __init__(self):
            super().__init__("N")
            r = self.add(_resistor("R_TP"))
            r[1] += vcc
            r[2] += gnd

    board = Board(
        size_mm=(20, 20),
        compile_goal="handoff",
        strict=False,
        strict_kicad=False,
    )
    board.add_module(Node())
    board._declared_testpoints = ["3V3"]
    board._require_testpoints = True
    with pytest.raises(DRCViolationError, match="TST-001"):
        run_drc(board)


def test_gld001_spice_island_uses_bundled_physics():
    import runpy

    root = Path(__file__).resolve().parents[1]
    script = root / "examples" / "spice_island_golden.py"
    text = script.read_text(encoding="utf-8")
    assert "D_1N4007" in text
    assert "OPTO_PC817" in text
    assert "AD620" in text
    overlay = json.loads(
        (root / "openhac" / "database" / "spice_model_overlays" / "bundled_openhac.json").read_text(
            encoding="utf-8"
        )
    )
    names = {m["generic_name"] for m in overlay["models"]}
    assert {"D_1N4007", "OPTO_PC817", "AD620"} <= names
    ns = runpy.run_path(str(script))
    board = ns["board"]
    assert "PhysicsIsland" in board._spice_island_names
    assert "DigitalIgnored" not in board._spice_island_names
    prod = (root / "scripts" / "ci_validate_production.py").read_text(encoding="utf-8")
    assert "fab_golden_board" in prod
    assert "--require-all" in prod
    assert "Not implied by --require-all" in prod
    docs = (root / "docs" / "internal" / "PRODUCTION_VALIDATION.md").read_text(encoding="utf-8")
    assert "spice_island_golden.py" in docs
    assert "sso041_signoff_node.py" in docs


def test_cli_lock_and_jlc_and_pinout_registered():
    from openhac.cli import main
    import openhac.cli as cli_mod

    src = Path(cli_mod.__file__).read_text(encoding="utf-8")
    assert '"lock"' in src
    assert '"pinout"' in src
    assert '"jlc"' in src
    assert "--require-lock" in src
    assert "--placement-intent" in src
    assert "--require-testpoints" in src
    assert "--assembler" in src
    assert "try_pcb_revert_via_ipc" in src
    assert main is not None
