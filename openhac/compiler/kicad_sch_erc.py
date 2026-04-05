"""
Run KiCad schematic ERC via ``kicad-cli`` (SCH-003).

OpenHaC's ``run_erc`` in ``rule_check`` is a **pre-check** on the SKiDL graph.
KiCad's ERC enforces symbol pin types, power pins, and other library rules on
the generated ``.kicad_sch``.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path

from openhac.core.base import KiCadCliNotFoundError, KiCadSchErcError

logger = logging.getLogger("openhac.kicad_erc")


def run_kicad_schematic_erc(
    sch_path: str | os.PathLike[str],
    *,
    output_report: str | os.PathLike[str] | None = None,
    report_format: str = "report",
    strict: bool = True,
) -> Path | None:
    """Run ``kicad-cli sch erc`` on *sch_path* with ``--exit-code-violations``.

    Args:
        sch_path: Path to ``.kicad_sch``.
        output_report: If set, write ERC output here (recommended for debugging).
        report_format: ``report`` or ``json`` (KiCad 8+).
        strict: If True (default), pass ``--exit-code-violations`` and raise when the CLI
            exits non-zero. If False, always return after running (caller should parse
            *output_report*; SCH-003 CI golden).

    Returns:
        Path to the report file if *output_report* was set, else ``None``.

    Raises:
        KiCadCliNotFoundError: ``kicad-cli`` is not on ``PATH``.
        KiCadSchErcError: schematic missing, or ERC reported violations / CLI failure (when *strict*).
    """
    kicad_cli = shutil.which("kicad-cli")
    if not kicad_cli:
        raise KiCadCliNotFoundError(
            "kicad-cli not found on PATH. Install KiCad and run ERC manually, "
            "or skip with compile flag kicad_sch_erc=False."
        )

    sch = Path(sch_path)
    if not sch.is_file():
        raise KiCadSchErcError(f"Schematic not found for KiCad ERC: {sch}")

    cmd: list[str] = [kicad_cli, "sch", "erc"]
    if strict:
        cmd.append("--exit-code-violations")
    cmd.extend(["--format", report_format])
    out_path: Path | None = None
    if output_report is not None:
        out_path = Path(output_report)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        cmd.extend(["-o", str(out_path)])
    cmd.append(str(sch))

    logger.info("Running KiCad schematic ERC: %s", " ".join(cmd))
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 and strict:
        msg = (
            f"KiCad schematic ERC failed (exit {r.returncode}). "
            f"See report: {out_path}" if out_path else "KiCad schematic ERC reported violations."
        )
        detail = (r.stderr or r.stdout or "").strip()
        if detail:
            msg = f"{msg}\n--- kicad-cli ---\n{detail}"
        raise KiCadSchErcError(msg)

    logger.info("KiCad schematic ERC passed for %s", sch.name)
    return out_path
