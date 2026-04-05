"""Immutable-ish release zip of compile outputs (MFG-005)."""

from __future__ import annotations

import logging
import zipfile
from pathlib import Path

logger = logging.getLogger("openhac.release")

# Suffixes we consider part of a named OpenHaC / KiCad compile bundle.
_RELEASE_SUFFIXES: tuple[str, ...] = (
    ".net",
    ".csv",
    ".kicad_pcb",
    ".kicad_sch",
    ".kicad_pro",
    ".openhac-manifest.json",
    ".openhac-manifest.json.sha256",
    ".openhac-fab-handoff.md",
    ".openhac-length-match-hint.md",
    ".openhac-mixed-signal-hint.md",
    ".openhac-pcb-routing-handoff.json",
    ".openhac-bom-alternates.json",
    ".openhac-bom-expand-hint.md",
    ".openhac-spice-model-hint.md",
    ".openhac-autoroute-policy.md",
    ".openhac-si-stackup-reminder.md",
    ".cir",
    ".kicad_sch.erc.txt",
    ".kicad_sch.erc.json",
)


def zip_project_outputs(base: Path, project_name: str, zip_path: str | Path) -> Path:
    """Write *zip_path* containing files under *base* whose names start with *project_name* and match known suffixes."""
    base = base.resolve()
    out = Path(zip_path).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    added = 0
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(base.iterdir()):
            if not p.is_file():
                continue
            if not p.name.startswith(f"{project_name}"):
                continue
            if not any(p.name.endswith(s) for s in _RELEASE_SUFFIXES):
                continue
            zf.write(p, arcname=p.name)
            added += 1

    logger.info("Wrote release zip %s (%s files)", out, added)
    return out
