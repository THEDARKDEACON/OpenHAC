"""
Parse KiCad schematic ERC reports produced by ``kicad-cli sch erc`` (SCH-003).

Supports JSON output (``--format json``) and a loose heuristic for plain-text reports.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

logger = logging.getLogger("openhac.kicad_erc")

# Loose match for KiCad human-readable ERC / DRC style lines (varies by locale/version).
_TEXT_ERRORISH = re.compile(r"(?i)\berror\b|\bunconnected\b|\bconflict\b|violat")


def _count_json_items(data: object) -> tuple[int, int, int]:
    """Return (error_count, warning_count, total_items) for common KiCad JSON shapes."""
    items: list[dict] = []
    if isinstance(data, list):
        items = [x for x in data if isinstance(x, dict)]
    elif isinstance(data, dict):
        v = data.get("violations")
        if isinstance(v, list):
            items = [x for x in v if isinstance(x, dict)]
        else:
            it = data.get("items")
            if isinstance(it, list):
                items = [x for x in it if isinstance(x, dict)]
            else:
                items = [data]
    total = len(items)
    errors = warnings = 0
    for obj in items:
        sev = str(obj.get("severity") or obj.get("type") or obj.get("level") or "").lower()
        if sev in ("error", "e_error", "err"):
            errors += 1
        elif sev in ("warning", "warn", "w_warning"):
            warnings += 1
    return errors, warnings, total


def summarize_kicad_erc_report(path: str | Path) -> dict:
    """Return a small summary dict: ``format``, counts, and ``path``.

    Use in CI or scripts to assert ``error_count == 0`` without shell-parsing.
    """
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"ERC report not found: {p}")

    raw = p.read_text(encoding="utf-8", errors="replace")
    stripped = raw.lstrip()

    if stripped.startswith(("{", "[")):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            logger.warning("ERC file looks like JSON but failed to parse: %s", e)
        else:
            err, warn, total = _count_json_items(data)
            return {
                "path": str(p),
                "format": "json",
                "error_count": err,
                "warning_count": warn,
                "item_count": total,
            }

    # Plain-text heuristic (KiCad "report" format varies by version).
    lines = raw.splitlines()
    hits = sum(1 for line in lines if _TEXT_ERRORISH.search(line))
    return {
        "path": str(p),
        "format": "text",
        "error_count": hits,
        "warning_count": 0,
        "line_count": len(lines),
    }
