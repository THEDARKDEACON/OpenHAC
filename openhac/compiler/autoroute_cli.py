"""
Autorouter integration for OpenHaC.

Workflow:
  1. Resolve FreeRouting jar path (parameter → FREEROUTING_JAR env var → error)
  2. Export DSN from the KiCad PCB via kicad-cli
  3. Invoke FreeRouting jar, streaming stdout in real time
  4. Verify SES output exists, then import it back via kicad-cli
"""

import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger("openhac.autoroute")

from openhac.core.base import FreeRoutingNotFoundError, AutorouterFailedError


def _resolve_jar_path(freerouting_jar_path: str | None) -> str:
    """Return the jar path from the explicit argument or FREEROUTING_JAR env var.

    Raises FreeRoutingNotFoundError if neither is set.
    """
    jar = freerouting_jar_path or os.environ.get("FREEROUTING_JAR")
    if not jar:
        raise FreeRoutingNotFoundError(
            "FreeRouting jar not found. "
            "Pass freerouting_jar_path= or set the FREEROUTING_JAR environment variable."
        )
    return jar


def run_freerouting(pcb_path: str, freerouting_jar_path: str = None) -> None:
    """Run the FreeRouting autorouter on *pcb_path*.

    Args:
        pcb_path: Path to the .kicad_pcb file to route.
        freerouting_jar_path: Optional explicit path to the FreeRouting jar.
            Falls back to the FREEROUTING_JAR environment variable.

    Raises:
        FreeRoutingNotFoundError: Jar path cannot be resolved.
        AutorouterFailedError: DSN export, FreeRouting invocation, or SES import fails.
    """
    # --- 9.2: Resolve jar and export DSN ---
    jar = _resolve_jar_path(freerouting_jar_path)

    pcb = Path(pcb_path)
    dsn_path = pcb.with_suffix(".dsn")
    ses_path = pcb.with_suffix(".ses")

    logger.info(f"Exporting DSN from {pcb_path} ...")
    dsn_result = subprocess.run(
        ["kicad-cli", "pcb", "export-dsn", str(pcb), "--output", str(dsn_path)],
        capture_output=True,
        text=True,
    )
    if dsn_result.returncode != 0:
        raise AutorouterFailedError(
            f"kicad-cli pcb export-dsn failed (exit {dsn_result.returncode}):\n"
            f"{dsn_result.stderr}"
        )

    # --- 9.3: Invoke FreeRouting with real-time stdout streaming ---
    logger.info(f"Starting FreeRouting: java -jar {jar} ...")
    with subprocess.Popen(
        ["java", "-jar", jar, "-input", str(dsn_path), "-output", str(ses_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,  # line-buffered
    ) as proc:
        for line in proc.stdout:
            logger.debug(line.rstrip())
        proc.wait()
        stderr_output = proc.stderr.read()

    if proc.returncode != 0:
        raise AutorouterFailedError(
            f"FreeRouting exited with code {proc.returncode}:\n{stderr_output}"
        )

    # --- 9.4: Verify SES and import ---
    if not ses_path.exists():
        raise AutorouterFailedError(
            f"FreeRouting completed but no SES output was produced at {ses_path}"
        )

    logger.info(f"Importing SES {ses_path} into {pcb_path} ...")
    ses_result = subprocess.run(
        ["kicad-cli", "pcb", "import-ses", str(pcb), "--input", str(ses_path)],
        capture_output=True,
        text=True,
    )
    if ses_result.returncode != 0:
        raise AutorouterFailedError(
            f"kicad-cli pcb import-ses failed (exit {ses_result.returncode}):\n"
            f"{ses_result.stderr}"
        )

    logger.info(f"Autorouting complete: {pcb_path}")
