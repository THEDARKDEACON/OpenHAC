"""Compile ``examples/complex_iot_edge_node_jlc_only.py`` with an isolated seeded DB (SW-006)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_EXAMPLE = _REPO_ROOT / "examples" / "complex_iot_edge_node_jlc_only.py"


def _seed_iot_edge_db(dm) -> None:
    """Minimal LCSC-style rows so the example board constructs and netlists."""

    def ins(
        gn: str,
        sym: str,
        fp: str,
        *,
        mpn: str = "",
        sku: str = "C1",
        cat: str = "ic",
        pinout: list[dict] | None = None,
    ) -> None:
        row = {
            "generic_name": gn,
            "kicad_symbol": sym,
            "kicad_footprint": fp,
            "manufacturer": "X",
            "mpn": mpn or gn,
            "supplier_sku": sku,
            "description": "",
            "category": cat,
            "attributes_json": "{}",
        }
        if pinout is not None:
            row["pinout_json"] = json.dumps(pinout)
        dm.insert_component(row, ignore_duplicate=True)

    # --- Power path (matches flight smoke + buck/LDO wiring) ---
    ins(
        "BUCK_TPS63001DRCR",
        "Device:Q",
        "Package_TO_SOT_SMD:SOT-23",
        pinout=[
            {"num": "1", "name": "VIN", "type": "power"},
            {"num": "2", "name": "GND", "type": "power"},
            {"num": "3", "name": "L1", "type": "bidirectional"},
            {"num": "4", "name": "FB", "type": "input"},
        ],
    )
    ins(
        "LDO_LDL1117S33R",
        "Device:Q",
        "Package_TO_SOT_SMD:SOT-23",
        pinout=[
            {"num": "1", "name": "IN", "type": "power"},
            {"num": "2", "name": "OUT", "type": "power"},
            {"num": "3", "name": "GND", "type": "power"},
        ],
    )
    for g, fp in (
        ("INDUCTOR_2R2_2520", "Inductor_SMD:L_2520"),
        ("C_10UF_0805", "Capacitor_SMD:C_0805_2012Metric"),
        ("C_22UF_0805", "Capacitor_SMD:C_0805_2012Metric"),
        ("C_100NF_0603", "Capacitor_SMD:C_0603_1608Metric"),
        ("C_100NF_0402", "Capacitor_SMD:C_0402_1005Metric"),
    ):
        ins(g, "Device:C", fp, cat="capacitors")
    for g in ("R_100K_0603", "R_32K4_0603", "R_1K_0603"):
        ins(g, "Device:R", "Resistor_SMD:R_0603_1608Metric", cat="resistors")

    ins(
        "LED_GREEN_0603",
        "Device:LED",
        "LED_SMD:LED_0603_1608Metric",
        cat="leds",
        pinout=[{"num": "1", "name": "A"}, {"num": "2", "name": "K"}],
    )
    ins(
        "LED_BLUE_0603",
        "Device:LED",
        "LED_SMD:LED_0603_1608Metric",
        cat="leds",
        pinout=[{"num": "1", "name": "A"}, {"num": "2", "name": "K"}],
    )

    # --- Host stub (SOIC-8 pads 1..8) ---
    ins(
        "MCU_EDGE_STUB_SOIC8",
        "Device:Q",
        "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
        cat="ic",
        pinout=[
            {"num": "1", "name": "VDD", "type": "power"},
            {"num": "2", "name": "VSS", "type": "power"},
            {"num": "3", "name": "CAN_TX", "type": "bidirectional"},
            {"num": "4", "name": "CAN_RX", "type": "bidirectional"},
            {"num": "5", "name": "NRST", "type": "input"},
            {"num": "6", "name": "NC", "type": "no_connect"},
            {"num": "7", "name": "NC", "type": "no_connect"},
            {"num": "8", "name": "NC", "type": "no_connect"},
        ],
    )

    # --- CAN transceiver (names aligned with ``CANModule`` wiring) ---
    ins(
        "CAN_TJA1051",
        "Device:Q",
        "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
        cat="ic",
        pinout=[
            {"num": "1", "name": "TXD", "type": "bidirectional"},
            {"num": "2", "name": "GND", "type": "power"},
            {"num": "3", "name": "VCC", "type": "power"},
            {"num": "4", "name": "RXD", "type": "bidirectional"},
            {"num": "5", "name": "NC", "type": "no_connect"},
            {"num": "6", "name": "CANL", "type": "bidirectional"},
            {"num": "7", "name": "CANH", "type": "bidirectional"},
            {"num": "8", "name": "S", "type": "input"},
        ],
    )


@pytest.mark.skipif(not _EXAMPLE.is_file(), reason="example script missing")
def test_complex_iot_edge_cli_compile_skip_layout(tmp_path):
    db_path, dm = (tmp_path / "edge.db").resolve(), None
    from openhac.database.db_manager import DatabaseManager

    dm = DatabaseManager(db_path=str(db_path))
    _seed_iot_edge_db(dm)

    env = {
        **os.environ,
        "PYTHONPATH": str(_REPO_ROOT),
        "OPENHAC_DB_PATH": str(db_path),
        "OPENHAC_SKIP_LAYOUT": "1",
        "OPENHAC_NO_NETWORK": "1",
    }
    r = subprocess.run(
        [
            sys.executable,
            "-m",
            "openhac.cli",
            "compile",
            str(_EXAMPLE),
            "-o",
            str(tmp_path),
            "--name",
            "iot_edge_smoke",
            "--no-route",
            "--no-schematic",
        ],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=300,
        env=env,
    )
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert (tmp_path / "iot_edge_smoke.net").is_file()
    assert (tmp_path / "iot_edge_smoke.csv").is_file()
    mf = tmp_path / "iot_edge_smoke.openhac-manifest.json"
    assert mf.is_file()
    data = json.loads(mf.read_text(encoding="utf-8"))
    assert data.get("project_name") == "iot_edge_smoke"
