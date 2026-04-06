"""Load SIM-002 analysis bundles from JSON or YAML (shared by CLI and ``Board.simulate``)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_spice_analysis_raw(path: str | Path) -> dict[str, Any]:
    """Parse *path* as JSON or YAML (.yaml / .yml). Must be a mapping object."""
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    suf = p.suffix.lower()
    if suf in (".yaml", ".yml"):
        try:
            import yaml  # type: ignore[import-untyped]
        except ImportError as e:
            raise ImportError(
                "PyYAML is required for .yaml/.yml spice analysis files (pip install pyyaml)."
            ) from e
        raw = yaml.safe_load(text)
    else:
        raw = json.loads(text)
    if not isinstance(raw, dict):
        raise ValueError("Spice analysis file must contain a JSON/YAML object at the top level.")
    return raw


def resolve_spice_analysis_from_mapping(raw: dict[str, Any]) -> tuple[list[str] | None, str | None]:
    """Return ``(analysis_lines, preset_name)`` from config keys ``analysis_lines`` / ``preset`` (mutually exclusive)."""
    al = raw.get("analysis_lines")
    pr = raw.get("preset")
    if al is not None and pr is not None:
        raise ValueError("Spice config: specify only one of 'analysis_lines' or 'preset', not both.")
    if al is not None:
        if not isinstance(al, list) or not al or not all(isinstance(x, str) for x in al):
            raise ValueError("Spice config: 'analysis_lines' must be a non-empty list of strings.")
        return list(al), None
    if pr is not None:
        if not isinstance(pr, str) or not pr.strip():
            raise ValueError("Spice config: 'preset' must be a non-empty string.")
        return None, str(pr).strip()
    raise ValueError("Spice config: need 'analysis_lines' or 'preset'.")
