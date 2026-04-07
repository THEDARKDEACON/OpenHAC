"""Immutable-ish release zip of compile outputs (MFG-005)."""

from __future__ import annotations

import logging
import zipfile
from pathlib import Path

logger = logging.getLogger("openhac.release")

_DETERMINISTIC_ZIP_DT = (1980, 1, 1, 0, 0, 0)

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
    ".openhac-stackup-handoff.json",
    ".openhac-power-rails.json",
    ".openhac-rail-conversions.json",
    ".openhac-unverified-parts.json",
    ".openhac-sch-pinpos-report.json",
    ".openhac-netclass-hint.md",
    ".openhac-diff-pair-constraints.json",
    ".openhac-no-autoroute-constraints.json",
    ".openhac-pcb-auxiliary-constraints.json",
    ".openhac-length-match-hint.md",
    ".openhac-length-match-constraints.json",
    ".openhac-mixed-signal-hint.md",
    ".openhac-mixed-signal-constraints.json",
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

    files: list[Path] = []
    for p in sorted(base.iterdir(), key=lambda x: x.name):
        if not p.is_file():
            continue
        if not p.name.startswith(f"{project_name}"):
            continue
        if not any(p.name.endswith(s) for s in _RELEASE_SUFFIXES):
            continue
        files.append(p.resolve())

    added = 0
    with zipfile.ZipFile(out, "w") as zf:
        for p in files:
            info = zipfile.ZipInfo(p.name)
            info.date_time = _DETERMINISTIC_ZIP_DT
            info.compress_type = zipfile.ZIP_DEFLATED
            try:
                mode = p.stat().st_mode
                info.external_attr = (mode & 0xFFFF) << 16
            except OSError:
                pass
            zf.writestr(info, p.read_bytes())
            added += 1

    logger.info("Wrote release zip %s (%s files)", out, added)
    return out
