"""Matrix tests for complex multi-IC example boards.

Offline fab boards: logic ERC/DRC (always). Place/Gerbers when pcbnew is available
and OPENHAC_TEST_COMPLEX_PLACE=1 (slow).

API board: live jlcsearch when OPENHAC_TEST_COMPLEX_API=1 (needs network).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_SCRIPT = _REPO / "scripts" / "ci_validate_complex_boards.py"

_FAB_IDS = ("esp32_devkit", "stm32_can", "rs485_node", "esp32c3_usb", "sensor_hub")


def _run(args: list[str], *, timeout: int = 600) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["OPENHAC_NO_NETWORK"] = "1"
    env["PYTHONPATH"] = str(_REPO) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, str(_SCRIPT), *args],
        cwd=str(_REPO),
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


@pytest.mark.parametrize("board_id", _FAB_IDS)
def test_complex_fab_logic(board_id: str) -> None:
    r = _run(["--only", board_id], timeout=180)
    assert r.returncode == 0, r.stdout + "\n" + r.stderr


@pytest.mark.skipif(
    os.environ.get("OPENHAC_TEST_COMPLEX_PLACE", "").strip().lower() not in ("1", "true", "yes"),
    reason="Set OPENHAC_TEST_COMPLEX_PLACE=1 to run slow place+Gerbers matrix",
)
@pytest.mark.parametrize("board_id", _FAB_IDS)
def test_complex_fab_place(board_id: str) -> None:
    pytest.importorskip("pcbnew")
    r = _run(["--place", "--only", board_id], timeout=300)
    assert r.returncode == 0, r.stdout + "\n" + r.stderr


@pytest.mark.skipif(
    os.environ.get("OPENHAC_TEST_COMPLEX_API", "").strip().lower() not in ("1", "true", "yes"),
    reason="Set OPENHAC_TEST_COMPLEX_API=1 to exercise live LCSC/jlcsearch",
)
def test_complex_lcsc_api_mixed() -> None:
    env = os.environ.copy()
    env.pop("OPENHAC_NO_NETWORK", None)
    env["OPENHAC_ALLOW_NETWORK"] = "1"
    env["OPENHAC_ALLOW_RISKY_PARTS"] = "1"
    env["PYTHONPATH"] = str(_REPO) + os.pathsep + env.get("PYTHONPATH", "")
    r = subprocess.run(
        [sys.executable, str(_SCRIPT), "--api", "--only", "lcsc_api_mixed"],
        cwd=str(_REPO),
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert r.returncode == 0, r.stdout + "\n" + r.stderr
