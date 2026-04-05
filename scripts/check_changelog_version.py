#!/usr/bin/env python3
"""Ensure CHANGELOG.md documents the current pyproject version (SW-004).

Exit 0 if a release section for the static version exists; 1 otherwise; 2 on parse errors.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


def _pyproject_version(root: Path) -> str:
    text = (root / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'(?m)^version\s*=\s*"([^"]+)"', text)
    if not m:
        print("SW-004: no static version = line in pyproject.toml", file=sys.stderr)
        sys.exit(2)
    return m.group(1)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    ver = _pyproject_version(root)
    cl = root / "CHANGELOG.md"
    if not cl.is_file():
        print("SW-004: CHANGELOG.md is missing at repo root", file=sys.stderr)
        return 1
    body = cl.read_text(encoding="utf-8")
    # Keep a Changelog style: ## [x.y.z]
    if f"## [{ver}]" in body:
        return 0
    print(
        f"SW-004: CHANGELOG.md has no section heading '## [{ver}]' "
        f"(add a release section for pyproject version {ver!r})",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
