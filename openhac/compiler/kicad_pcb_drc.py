from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path

from openhac.core.base import KiCadCliNotFoundError, OpenHaCError

logger = logging.getLogger("openhac.kicad_pcb_drc")


class KiCadPcbDrcError(OpenHaCError):
    """Raised when `kicad-cli pcb drc` reports violations or fails."""


def run_kicad_pcb_drc(
    pcb_path: str | os.PathLike[str],
    *,
    output_report: str | os.PathLike[str] | None = None,
    strict: bool = True,
) -> Path | None:
    """Run `kicad-cli pcb drc` on a `.kicad_pcb`.

    KiCad's PCB DRC is the authoritative gate for fabrication-mode builds.
    """
    kicad_cli = shutil.which("kicad-cli")
    if not kicad_cli:
        raise KiCadCliNotFoundError(
            "kicad-cli not found on PATH. Install KiCad to run PCB DRC, or run in handoff mode."
        )

    pcb = Path(pcb_path)
    if not pcb.is_file():
        raise KiCadPcbDrcError(f"PCB not found for KiCad DRC: {pcb}")

    cmd: list[str] = [kicad_cli, "pcb", "drc"]
    if strict:
        cmd.append("--exit-code-violations")
    out_path: Path | None = None
    if output_report is not None:
        out_path = Path(output_report)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        cmd.extend(["-o", str(out_path)])
    cmd.append(str(pcb))

    logger.info("Running KiCad PCB DRC: %s", " ".join(cmd))
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 and strict:
        msg = f"KiCad PCB DRC failed (exit {r.returncode})."
        if out_path:
            msg += f" See report: {out_path}"
        detail = (r.stderr or r.stdout or "").strip()
        if detail:
            msg = f"{msg}\n--- kicad-cli ---\n{detail}"
        raise KiCadPcbDrcError(msg)

    logger.info("KiCad PCB DRC passed for %s", pcb.name)
    return out_path

