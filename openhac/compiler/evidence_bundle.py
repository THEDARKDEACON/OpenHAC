from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path


def _utc_iso(deterministic: bool) -> str:
    if deterministic:
        return "1980-01-01T00:00:00+00:00"
    return datetime.now(timezone.utc).isoformat()


def write_evidence_markdown(base: str | Path, project_name: str, board) -> Path:
    basep = Path(base)
    det = (
        os.environ.get("OPENHAC_DETERMINISTIC", "").strip().lower() in ("1", "true", "yes", "on")
        or os.environ.get("OPENHAC_DETERMINISTIC_MANIFEST", "").strip().lower() in ("1", "true", "yes", "on")
    )
    out = basep / f"{project_name}.openhac-evidence.md"
    lines: list[str] = []
    lines.append("# OpenHaC evidence bundle")
    lines.append("")
    lines.append(f"- **project**: `{project_name}`")
    lines.append(f"- **generated_utc**: `{_utc_iso(det)}`")
    lines.append(f"- **compile_goal**: `{getattr(board, 'effective_compile_goal', lambda: getattr(board, 'compile_goal', 'handoff'))()}`")
    lines.append(f"- **board_class**: `{getattr(board, 'board_class', 'generic')}`")
    pm = getattr(board, "_last_pcb_metrics", None)
    if isinstance(pm, dict) and pm:
        lines.append("")
        lines.append("## PCB metrics (best-effort)")
        for k in sorted(pm.keys()):
            lines.append(f"- **{k}**: `{pm[k]}`")
    lines.append("")
    lines.append("## Notes")
    lines.append("- This file is an **evidence index**, not a sign-off certificate.")
    lines.append("- Treat autorouting as assistance unless fabrication gates and human review are complete.")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def write_attestation_json(base: str | Path, project_name: str, board) -> Path | None:
    """Optional attestation metadata (signing is future; metadata is useful now)."""
    signer = (os.environ.get("OPENHAC_ATTEST_SIGNER") or "").strip()
    if not signer:
        return None
    basep = Path(base)
    det = (
        os.environ.get("OPENHAC_DETERMINISTIC", "").strip().lower() in ("1", "true", "yes", "on")
        or os.environ.get("OPENHAC_DETERMINISTIC_MANIFEST", "").strip().lower() in ("1", "true", "yes", "on")
    )
    payload = {
        "schema": "openhac.attestation.v1",
        "project_name": project_name,
        "generated_utc": _utc_iso(det),
        "signer": signer,
        "compile_goal": getattr(board, "effective_compile_goal", lambda: getattr(board, "compile_goal", "handoff"))(),
        "board_class": str(getattr(board, "board_class", "generic")),
    }
    out = basep / f"{project_name}.openhac-attestation.json"
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return out

