from __future__ import annotations

import json
from pathlib import Path


def write_sipi_handoff_json(base: str | Path, project_name: str, board) -> Path | None:
    """Write a consolidated SI/PI handoff JSON from existing intent fields.

    This does not solve SI/PI; it packages existing intent in a stable, tool-friendly format.
    """
    basep = Path(base)
    payload = {
        "schema": "openhac.sipi_handoff.v1",
        "board_class": str(getattr(board, "board_class", "generic") or "generic"),
        "fab_profile": (str(getattr(board, "fab_profile", "")) if getattr(board, "fab_profile", None) else ""),
        "stackup_references": list(getattr(board, "_stackup_references", None) or []),
        "diff_pair_intent": [],
        "length_match_groups": list(getattr(board, "_length_match_groups", None) or []),
        "net_roles": list(getattr(board, "_net_roles", None) or []),
        "net_merge_hints": list(getattr(board, "_net_merge_hints", None) or []),
    }
    # Diff pairs live in board.constraints with type diff_pair (SIG-002).
    for c in list(getattr(board, "constraints", None) or []):
        if not isinstance(c, dict):
            continue
        if c.get("type") != "diff_pair":
            continue
        try:
            p_net, n_net, z0 = c.get("args", (None, None, None))
            payload["diff_pair_intent"].append(
                {
                    "p": str(getattr(p_net, "name", p_net)),
                    "n": str(getattr(n_net, "name", n_net)),
                    "target_impedance_ohms": float(z0),
                }
            )
        except Exception:
            continue

    if not any(payload.get(k) for k in ("stackup_references", "diff_pair_intent", "length_match_groups", "net_roles", "net_merge_hints")):
        return None

    out = basep / f"{project_name}.openhac-sipi-handoff.json"
    out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return out

