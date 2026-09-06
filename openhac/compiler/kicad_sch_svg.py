"""Export a KiCad schematic to SVG (SSO-012). Never runs ERC."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path

from openhac.core.exceptions import KiCadCliNotFoundError

logger = logging.getLogger("openhac.kicad_svg")


def find_exported_svg(output_dir: Path, stem: str) -> Path:
    """Prefer ``{stem}.svg``; else the newest ``*.svg`` in *output_dir*."""
    exact = output_dir / f"{stem}.svg"
    if exact.is_file():
        return exact
    svgs = [p for p in output_dir.glob("*.svg") if p.is_file()]
    if not svgs:
        raise RuntimeError(f"kicad-cli sch export svg produced no .svg under {output_dir}")
    svgs.sort(key=lambda p: p.stat().st_mtime_ns, reverse=True)
    return svgs[0]


def export_schematic_svg(
    sch_path: str | os.PathLike[str],
    *,
    output_dir: str | os.PathLike[str] | None = None,
) -> Path:
    """Run ``kicad-cli sch export svg`` (not ``sch erc``)."""
    sch = Path(sch_path)
    if not sch.is_file():
        raise FileNotFoundError(f"schematic not found: {sch}")
    kicad_cli = shutil.which("kicad-cli")
    if not kicad_cli:
        raise KiCadCliNotFoundError(
            "kicad-cli not found on PATH. Install KiCad to export preview SVG."
        )
    out_dir = Path(output_dir) if output_dir is not None else sch.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [kicad_cli, "sch", "export", "svg", "--output", str(out_dir), str(sch)]
    logger.info("SSO-012 preview SVG (not ERC): %s", " ".join(cmd))
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        detail = ((r.stderr or "") + (r.stdout or "")).strip()[:800]
        raise RuntimeError(f"kicad-cli sch export svg failed (rc={r.returncode}): {detail}")
    return find_exported_svg(out_dir, sch.stem)
