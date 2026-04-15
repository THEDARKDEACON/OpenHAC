from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


def _which_any(candidates: list[str]) -> str | None:
    for c in candidates:
        p = shutil.which(c)
        if p:
            return p
    return None


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    tex = root / "docs" / "report" / "openhac_report.tex"
    if not tex.is_file():
        print(f"error: missing {tex}", file=sys.stderr)
        return 2

    out_dir = root / "docs" / "report" / "build"
    out_dir.mkdir(parents=True, exist_ok=True)

    engine = _which_any(["lualatex", "pdflatex"])
    if not engine:
        print("error: neither lualatex nor pdflatex found on PATH", file=sys.stderr)
        return 2

    cmd = [
        engine,
        "-interaction=nonstopmode",
        "-halt-on-error",
        "-output-directory",
        str(out_dir),
        str(tex),
    ]
    # Run twice for TOC and references consistency.
    for i in range(2):
        r = subprocess.run(cmd, cwd=str(root))
        if r.returncode != 0:
            return int(r.returncode)

    pdf = out_dir / "openhac_report.pdf"
    if pdf.is_file():
        print(f"ok: wrote {pdf}")
        return 0
    print("error: build completed but PDF not found", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

