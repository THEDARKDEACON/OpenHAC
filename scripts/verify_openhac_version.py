#!/usr/bin/env python3
"""Compare ``pyproject.toml`` ``version`` with the installed package (SW-004).

Exit codes: 0 match, 1 mismatch, 2 pyproject parse error.
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
    rs = str(root)
    if rs not in sys.path:
        sys.path.insert(0, rs)
    expected = _pyproject_version(root)
    from openhac.version_info import get_version

    got = get_version()
    if got != expected:
        print(
            f"SW-004: version mismatch: pyproject.toml has {expected!r}, "
            f"importlib.metadata reports {got!r}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
