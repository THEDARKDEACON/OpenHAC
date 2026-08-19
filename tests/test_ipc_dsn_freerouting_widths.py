"""Unit tests for IPC-2152 → Specctra / FreeRouting width handoff."""

from __future__ import annotations

from pathlib import Path
import json

import pytest

from openhac.compiler.pcb_physics import (
    _ipc2152_width_mm,
    _netclass_for_current,
    assert_dsn_netclass_widths,
    patch_dsn_ipc_widths,
)
from openhac.compiler.autoroute_cli import export_dsn_with_ipc_widths, run_freerouting
from openhac.core.base import FreeRoutingNotFoundError


def test_ipc_bucket_uses_higher_threshold():
    assert _netclass_for_current(2.1) == "Power_2A"
    assert _netclass_for_current(4.9) == "Power_2A"
    assert _netclass_for_current(5.0) == "HighCurrent_5A"
    w2 = _ipc2152_width_mm(2.1)
    w5 = _ipc2152_width_mm(4.9)
    assert w5 >= w2


def test_patch_dsn_ipc_widths(tmp_path: Path):
    dsn = tmp_path / "board.dsn"
    dsn.write_text(
        """(pcb board
  (network
    (net GND (pins U1-1))
    (net 3V3 (pins U1-2))
    (net SIG (pins U1-3))
    (class kicad_default GND 3V3 SIG
      (rule
        (width 200)
        (clearance 200)
      )
    )
  )
  (wiring
  )
)
""",
        encoding="utf-8",
    )
    n = patch_dsn_ipc_widths(dsn, {"GND": 0.5, "3V3": 0.35})
    assert n == 2
    text = dsn.read_text(encoding="utf-8")
    assert "IPC_500um" in text
    assert "(width 500)" in text
    assert "IPC_350um" in text
    assert "SIG" in text  # leftover in default
    viols = assert_dsn_netclass_widths(
        dsn,
        net_widths_mm={"GND": 0.5, "3V3": 0.35},
        strict=False,
    )
    assert viols == []


def test_export_dsn_with_ipc_widths_writes_file(tmp_path: Path, monkeypatch):
    pcb = tmp_path / "board.kicad_pcb"
    pcb.write_text("(kicad_pcb (version 20211014))\n", encoding="utf-8")

    def fake_export(_pcb: Path, dsn_path: Path) -> None:
        dsn_path.write_text("(pcb board)\n", encoding="utf-8")

    monkeypatch.setattr("openhac.compiler.autoroute_cli._export_specctra_dsn", fake_export)
    out = export_dsn_with_ipc_widths(pcb, required_netclass_widths_mm={"Default": 0.2})
    assert out == pcb.with_suffix(".dsn")
    assert out.is_file()
    assert "pcb board" in out.read_text(encoding="utf-8")


def test_run_freerouting_writes_dsn_even_if_backend_missing(tmp_path: Path, monkeypatch):
    pcb = tmp_path / "board.kicad_pcb"
    pcb.write_text("(kicad_pcb (version 20211014))\n", encoding="utf-8")

    def fake_export(_pcb: Path, dsn_path: Path) -> None:
        dsn_path.write_text("(pcb board)\n", encoding="utf-8")

    monkeypatch.setattr("openhac.compiler.autoroute_cli._export_specctra_dsn", fake_export)

    def _no_backend(_p):
        raise FreeRoutingNotFoundError("no jar")

    monkeypatch.setattr("openhac.compiler.autoroute_cli._resolve_freerouting_backend", _no_backend)

    with pytest.raises(FreeRoutingNotFoundError):
        run_freerouting(str(pcb), freerouting_jar_path="missing.jar")
    assert pcb.with_suffix(".dsn").is_file()


def test_collect_net_widths_from_openhac_kicad_pro(tmp_path: Path, monkeypatch):
    from openhac.compiler.pcb_physics import collect_net_widths_mm_from_pcb

    pcb = tmp_path / "board.kicad_pcb"
    pcb.write_text("(kicad_pcb)\n", encoding="utf-8")
    pro = tmp_path / "board.kicad_pro"
    pro.write_text(
        """{
          "board": {
            "design_settings": {
              "net_classes": {
                "classes": [
                  {"name": "Default", "track_width": 0.2},
                  {"name": "Power_2A", "track_width": 0.786},
                  {"name": "Signal", "track_width": 0.25}
                ],
                "setup": [
                  {"class": "Power_2A", "net": "GND"},
                  {"class": "Power_2A", "net": "VIN_24V"},
                  {"class": "Signal", "net": "I2C_SDA"}
                ]
              }
            }
          }
        }
        """,
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "openhac.compiler.pcb_physics._net_widths_mm_from_pcbnew",
        lambda _p: {},
    )
    widths = collect_net_widths_mm_from_pcb(pcb)
    assert widths["GND"] == pytest.approx(0.786)
    assert widths["VIN_24V"] == pytest.approx(0.786)
    assert widths["I2C_SDA"] == pytest.approx(0.25)


def test_collect_net_widths_from_kicad_net_settings(tmp_path: Path, monkeypatch):
    from openhac.compiler.pcb_physics import collect_net_widths_mm_from_pcb

    pcb = tmp_path / "board.kicad_pcb"
    pcb.write_text("(kicad_pcb)\n", encoding="utf-8")
    (tmp_path / "board.kicad_pro").write_text(
        """{
          "net_settings": {
            "classes": [
              {"name": "Power_1A", "track_width": 0.529}
            ],
            "netclass_assignments": {"3V3": "Power_1A"}
          }
        }
        """,
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "openhac.compiler.pcb_physics._net_widths_mm_from_pcbnew",
        lambda _p: {},
    )
    widths = collect_net_widths_mm_from_pcb(pcb)
    assert widths["3V3"] == pytest.approx(0.529)


def test_collect_net_widths_from_kicad9_patterns_after_assignments_null(tmp_path: Path, monkeypatch):
    from openhac.compiler.pcb_physics import collect_net_widths_mm_from_pcb

    pcb = tmp_path / "board.kicad_pcb"
    pcb.write_text("(kicad_pcb)\n", encoding="utf-8")
    (tmp_path / "board.kicad_pro").write_text(
        """{
          "net_settings": {
            "classes": [
              {"name": "Power_2A", "track_width": 0.786}
            ],
            "netclass_assignments": null,
            "netclass_patterns": [
              {"netclass": "Power_2A", "pattern": "GND"}
            ]
          }
        }
        """,
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "openhac.compiler.pcb_physics._net_widths_mm_from_pcbnew",
        lambda _p: {},
    )
    widths = collect_net_widths_mm_from_pcb(pcb)
    assert widths["GND"] == pytest.approx(0.786)


def test_collect_net_widths_from_openhac_sidecar_when_pro_flattened(tmp_path: Path, monkeypatch):
    from openhac.compiler.pcb_physics import collect_net_widths_mm_from_pcb

    pcb = tmp_path / "board.kicad_pcb"
    pcb.write_text("(kicad_pcb)\n", encoding="utf-8")
    (tmp_path / "board.kicad_pro").write_text(
        '{"net_settings": {"classes": [{"name": "Default", "track_width": 0.2}], '
        '"netclass_assignments": null, "netclass_patterns": []}}',
        encoding="utf-8",
    )
    (tmp_path / "board.openhac-netclasses.json").write_text(
        json.dumps(
            {
                "schema": "openhac.netclasses.v1",
                "assignments": {"GND": "Power_2A"},
                "classes": {"Power_2A": {"name": "Power_2A", "track_width": 0.786}},
                "widths_mm": {"GND": 0.786},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "openhac.compiler.pcb_physics._net_widths_mm_from_pcbnew",
        lambda _p: {},
    )
    widths = collect_net_widths_mm_from_pcb(pcb)
    assert widths["GND"] == pytest.approx(0.786)


def test_export_dsn_strict_fails_when_no_widths(tmp_path: Path, monkeypatch):
    from openhac.core.base import AutorouterFailedError

    pcb = tmp_path / "board.kicad_pcb"
    pcb.write_text("(kicad_pcb)\n", encoding="utf-8")

    def fake_export(_pcb: Path, dsn_path: Path) -> None:
        dsn_path.write_text("(pcb board (network (class kicad_default (rule (width 200)))))\n", encoding="utf-8")

    monkeypatch.setattr("openhac.compiler.autoroute_cli._export_specctra_dsn", fake_export)
    monkeypatch.setattr("openhac.compiler.pcb_physics._net_widths_mm_from_pcbnew", lambda _p: {})
    monkeypatch.setattr("openhac.compiler.pcb_physics._net_widths_mm_from_kicad_pro", lambda _p: {})
    monkeypatch.setattr("openhac.compiler.pcb_physics._net_widths_mm_from_pcb_sexpr", lambda _p: {})
    monkeypatch.setattr("openhac.compiler.pcb_physics._net_widths_mm_from_specctra_rules", lambda _p: {})
    monkeypatch.setattr("openhac.compiler.pcb_physics._net_widths_mm_from_openhac_sidecar", lambda _p: {})
    with pytest.raises(AutorouterFailedError, match="no compile-time netclass widths"):
        export_dsn_with_ipc_widths(pcb, require_dsn_widths=True)


def test_export_dsn_patches_ipc_from_saved_pcb(tmp_path: Path, monkeypatch):
    pcb = tmp_path / "board.kicad_pcb"
    pcb.write_text("(kicad_pcb)\n", encoding="utf-8")
    flat = """(pcb board
  (network
    (net GND (pins U1-1))
    (net 3V3 (pins U1-2))
    (class kicad_default GND 3V3
      (rule
        (width 200)
        (clearance 200)
      )
    )
  )
  (wiring
  )
)
"""

    def fake_export(_pcb: Path, dsn_path: Path) -> None:
        dsn_path.write_text(flat, encoding="utf-8")

    monkeypatch.setattr("openhac.compiler.autoroute_cli._export_specctra_dsn", fake_export)
    monkeypatch.setattr(
        "openhac.compiler.pcb_physics._net_widths_mm_from_pcbnew",
        lambda _p: {"GND": 0.5, "3V3": 0.35},
    )
    monkeypatch.setattr(
        "openhac.compiler.pcb_physics._net_widths_mm_from_kicad_pro",
        lambda _p: {},
    )
    monkeypatch.setattr(
        "openhac.compiler.pcb_physics._net_widths_mm_from_pcb_sexpr",
        lambda _p: {},
    )
    out = export_dsn_with_ipc_widths(pcb)
    text = out.read_text(encoding="utf-8")
    assert "IPC_500um" in text
    assert "(width 500)" in text
    assert "IPC_350um" in text
    assert "(width 350)" in text
