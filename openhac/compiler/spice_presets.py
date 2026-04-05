"""Named SPICE analysis directive bundles (SIM-002)."""

from __future__ import annotations

PRESETS: dict[str, list[str]] = {
    "tran": [".tran 1m 100m"],
    "ac": [".ac dec 10 1 1Meg"],
    "op": [".op"],
    # SIM-002 — common extras (tune sources/nodes in the generated .cir as needed)
    "dc": [".dc V1 0 5 0.1"],
    "noise": [".noise V(out) V1 dec 10 1k 100Meg"],
}


def preset_analysis_lines(name: str) -> list[str]:
    """Return analysis lines for preset *name* (case-insensitive)."""
    key = (name or "").strip().lower()
    if key not in PRESETS:
        allowed = ", ".join(sorted(PRESETS))
        raise ValueError(f"Unknown SPICE preset {name!r}; choose one of: {allowed}")
    return list(PRESETS[key])
