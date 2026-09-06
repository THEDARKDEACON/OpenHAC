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

_DETERMINISTIC_ZIP_DT = (1980, 1, 1, 0, 0, 0)


def _zip_dir_deterministic(src_dir: Path, zip_path: Path) -> None:
    """Write a deterministic zip of all files under *src_dir*.

    Determinism here means:
    - Files are added in sorted path order.
    - Zip entry timestamps are fixed (so bytes are stable across runs).
    """
    src_dir = src_dir.resolve()
    zip_path = zip_path.resolve()
    zip_path.parent.mkdir(parents=True, exist_ok=True)

    files: list[Path] = []
    for root, _, fns in os.walk(src_dir):
        for fn in fns:
            files.append((Path(root) / fn).resolve())
    files = sorted(dict.fromkeys(files), key=lambda p: str(p.relative_to(src_dir)))

    with zipfile.ZipFile(zip_path, "w") as zf:
        for fp in files:
            rel = str(fp.relative_to(src_dir))
            info = zipfile.ZipInfo(rel)
            info.date_time = _DETERMINISTIC_ZIP_DT
            info.compress_type = zipfile.ZIP_DEFLATED
            # Preserve UNIX permissions so extracted artifacts remain readable in CI.
            try:
                mode = fp.stat().st_mode
                info.external_attr = (mode & 0xFFFF) << 16
            except OSError:
                pass
            zf.writestr(info, fp.read_bytes())


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
    assembler: str | None = None,
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
    goal = (os.environ.get("OPENHAC_COMPILE_GOAL") or "").strip().lower()
    raw_omit = (os.environ.get("OPENHAC_OMITTED_FOOTPRINT_REFS") or "").strip()
    if raw_omit and goal in ("fabrication", "fab"):
        refs = [x.strip() for x in raw_omit.split(",") if x.strip()]
        if refs:
            raise FabExportError(
                "FAB-003: refusing fab export with omitted footprints: " + ", ".join(refs)
            )
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

    asm = str(assembler or "").strip().lower()
    if asm in ("jlc", "jlcpcb"):
        from openhac.compiler.export_jlc import export_jlc_pack

        bom_sib = pcb.with_suffix(".csv")
        export_jlc_pack(pcb if bom_sib.is_file() else bom_sib, out, strict=True, bom_csv=bom_sib if bom_sib.is_file() else None)

    zip_written: Path | None = None
    if zip_path is not None:
        zp = Path(zip_path)
        _zip_dir_deterministic(out, zp)
        logger.info("Wrote fabrication zip: %s", zp)
        zip_written = zp
    return zip_written
