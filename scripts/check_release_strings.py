#!/usr/bin/env python3
"""Lightweight release hygiene scan (SW-004): stale marketing version tokens in tracked docs.

Exit 0 if no suspicious patterns; 1 if any hit. Does not replace human review.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Patterns that often indicate drift vs pyproject / package version.
SUSPICIOUS = (
    r"OpenHaC\s*/\s*1\.0\b",
    r"OpenHaC\s+1\.0\b",
    r"version\s+1\.0\.0\b",
    r"Hardware\s+as\s+Code\s+1\.0\b",
)

def _iter_files(root: Path):
    """Scan customer-facing top-level docs only (normative spec quotes old strings by design)."""
    yield root / "README.md"
    yield root / "SCOPE.md"
    rel = root / "docs" / "RELEASE_CHECKLIST.md"
    if rel.is_file():
        yield rel


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    rx = [re.compile(p, re.IGNORECASE) for p in SUSPICIOUS]
    hits: list[tuple[Path, int, str]] = []
    for path in _iter_files(root):
        if not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for i, line in enumerate(lines, 1):
            for r in rx:
                if r.search(line):
                    hits.append((path, i, line.strip()[:200]))
                    break
    if hits:
        print("SW-004: suspicious version/marketing strings:", file=sys.stderr)
        for p, ln, snippet in hits:
            print(f"  {p.relative_to(root)}:{ln}: {snippet}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
