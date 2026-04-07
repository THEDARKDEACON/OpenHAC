from __future__ import annotations

import re

_SPLIT_NUM_RE = re.compile(r"(\d+)")


def natural_key(s: str) -> tuple:
    """Case-insensitive 'natural' sort key (numbers sort numerically).

    Example: R2 < R10, U9 < U12.
    """
    raw = (s or "").strip()
    parts = _SPLIT_NUM_RE.split(raw)
    out: list[object] = []
    for p in parts:
        if not p:
            continue
        if p.isdigit():
            out.append(int(p))
        else:
            out.append(p.upper())
    return tuple(out)

