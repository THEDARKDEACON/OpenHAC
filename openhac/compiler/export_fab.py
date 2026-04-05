"""
Fabrication export via KiCad CLI (Gerbers, drill, optional pick-and-place).

Requires ``kicad-cli`` on PATH (same as autorouter DSN export).
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import zipfile
from pathlib import Path

from openhac.core.base import FabExportError

logger = logging.getLogger("openhac.export_fab")


def _which_kicad_cli() -> str | None:
    return shutil.which("kicad-cli")


def _export_pos_csv_side(kicad_cli: str, pcb: Path, side: str, dest: Path) -> None:
    cmd = [
        kicad_cli,
        "pcb",
        "export",
        "pos",
        "-o",
        str(dest),
        "--side",
        side,
        "--format",
        "csv",
        "--units",
        "mm",
        str(pcb),
    ]
    logger.info("Running kicad-cli pos (%s) → %s", side, dest)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise FabExportError(
            f"kicad-cli pcb export pos ({side}) failed (exit {r.returncode}):\n{r.stderr or r.stdout}"
        )


def export_assembly_csv(
    pcb_path: str | os.PathLike[str],
    output_dir: str | os.PathLike[str],
) -> None:
    """Export front and back pick-and-place CSV files via ``kicad-cli`` (MFG-002)."""
    pcb = Path(pcb_path)
    out = Path(output_dir)
    if not pcb.is_file():
        raise FabExportError(f"PCB file not found: {pcb}")
    kicad_cli = _which_kicad_cli()
    if not kicad_cli:
        raise FabExportError(
            "kicad-cli not found on PATH. Install KiCad and ensure its bin directory is on PATH."
        )
    out.mkdir(parents=True, exist_ok=True)
    pos_front = out / f"{pcb.stem}-pos_front.csv"
    pos_back = out / f"{pcb.stem}-pos_back.csv"
    for side, dest in (("front", pos_front), ("back", pos_back)):
        _export_pos_csv_side(kicad_cli, pcb, side, dest)


def export_fabrication_bundle(
    pcb_path: str | os.PathLike[str],
    output_dir: str | os.PathLike[str],
    *,
    include_pos: bool = True,
    include_ipc2581: bool = False,
    gerber_use_board_settings: bool = False,
    zip_path: str | os.PathLike[str] | None = None,
) -> Path | None:
    """Export Gerbers, Excellon drill, and optionally CSV position files into *output_dir*.

    Args:
        pcb_path: Path to ``.kicad_pcb``.
        output_dir: Directory to create (if missing) and write outputs into.
        include_pos: If True, run ``pos`` export (both sides, CSV, mm).
        include_ipc2581: If True, run ``ipc2581`` export (MFG-001 extension).
        gerber_use_board_settings: If True, pass ``--board-plot-params`` to ``gerbers``.
        zip_path: If set, write a zip archive of *output_dir* (after exports complete).

    Returns:
        Path to the zip file if ``zip_path`` was set, else ``None``.
    """
    pcb = Path(pcb_path)
    out = Path(output_dir)
    if not pcb.is_file():
        raise FabExportError(f"PCB file not found: {pcb}")
    kicad_cli = _which_kicad_cli()
    if not kicad_cli:
        raise FabExportError(
            "kicad-cli not found on PATH. Install KiCad and ensure its bin directory is on PATH."
        )

    out.mkdir(parents=True, exist_ok=True)

    gerber_cmd = [
        kicad_cli,
        "pcb",
        "export",
        "gerbers",
        "-o",
        str(out),
        str(pcb),
    ]
    if gerber_use_board_settings:
        gerber_cmd.insert(-1, "--board-plot-params")

    drill_cmd = [
        kicad_cli,
        "pcb",
        "export",
        "drill",
        "-o",
        str(out),
        "--format",
        "excellon",
        "--excellon-units",
        "mm",
        str(pcb),
    ]

    for cmd, label in ((gerber_cmd, "gerbers"), (drill_cmd, "drill")):
        logger.info("Running kicad-cli %s → %s", label, out)
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise FabExportError(
                f"kicad-cli pcb export {label} failed (exit {r.returncode}):\n{r.stderr or r.stdout}"
            )

    if include_ipc2581:
        ipc_out = out / f"{pcb.stem}.ipc2581"
        ipc_cmd = [
            kicad_cli,
            "pcb",
            "export",
            "ipc2581",
            "-o",
            str(ipc_out),
            str(pcb),
        ]
        logger.info("Running kicad-cli ipc2581 → %s", ipc_out)
        r = subprocess.run(ipc_cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise FabExportError(
                f"kicad-cli pcb export ipc2581 failed (exit {r.returncode}):\n{r.stderr or r.stdout}"
            )

    if include_pos:
        pos_front = out / f"{pcb.stem}-pos_front.csv"
        pos_back = out / f"{pcb.stem}-pos_back.csv"
        for side, dest in (("front", pos_front), ("back", pos_back)):
            _export_pos_csv_side(kicad_cli, pcb, side, dest)

    zip_written: Path | None = None
    if zip_path is not None:
        zp = Path(zip_path)
        zp.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zp, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for root, _, files in os.walk(out):
                for fn in files:
                    fp = Path(root) / fn
                    zf.write(fp, arcname=str(fp.relative_to(out)))
        logger.info("Wrote fabrication zip: %s", zp)
        zip_written = zp
    return zip_written
