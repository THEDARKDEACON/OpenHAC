from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from openhac.core.base import OpenHaCError


def parse_ngspice_log(text: str) -> dict:
    """Very small log parser for ngspice batch output.

    This is not a full results extractor; it provides stable summary signals for CI/golden tests.
    """
    s = text or ""
    low = s.lower()
    return {
        "log_bytes": int(len(s.encode("utf-8", errors="replace"))),
        "error_line_count": int(sum(1 for ln in low.splitlines() if "error" in ln)),
        "warning_line_count": int(sum(1 for ln in low.splitlines() if "warn" in ln)),
    }


def run_ngspice_headless(
    cir_path: str | Path,
    *,
    log_path: str | Path | None = None,
    timeout_s: float = 30.0,
) -> str:
    """Run ngspice in batch mode for a `.cir` file.

    Returns the path to the log file written.
    """
    exe = shutil.which("ngspice")
    if not exe:
        raise OpenHaCError("ngspice not found on PATH (install ngspice or disable run_ngspice).")
    cir = Path(cir_path)
    if not cir.is_file():
        raise OpenHaCError(f"SPICE netlist not found: {str(cir)!r}")
    if log_path is None:
        log_path = cir.with_suffix(cir.suffix + ".ngspice.log")
    logp = Path(log_path)

    try:
        cp = subprocess.run(
            [exe, "-b", "-o", str(logp), str(cir)],
            capture_output=True,
            text=True,
            timeout=float(timeout_s),
        )
    except subprocess.TimeoutExpired as e:
        raise OpenHaCError(f"ngspice timed out after {timeout_s}s for {str(cir)!r}") from e

    if cp.returncode != 0:
        extra = ""
        if cp.stderr and cp.stderr.strip():
            extra = "\n" + cp.stderr.strip()
        raise OpenHaCError(f"ngspice failed (exit={cp.returncode}) for {str(cir)!r}{extra}")

    # Some ngspice builds write status to stdout/stderr even on success; the log is the primary artifact.
    return str(logp)

