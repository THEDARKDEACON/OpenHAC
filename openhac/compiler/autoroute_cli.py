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


def fallback_route_with_pcbnew(pcb_path: str, *, no_autoroute_nets: list[str] | None = None) -> None:
    """Best-effort routing fallback using pcbnew.

    This is **not** a real autorouter. It draws a small number of straight-line
    tracks between pads of common nets so the output PCB visibly contains tracks
    when FreeRouting is not installed.
    """
    try:
        import pcbnew  # type: ignore
    except Exception as e:  # pragma: no cover
        raise AutorouterFailedError(f"pcbnew import failed for fallback router: {e}")

    board = pcbnew.LoadBoard(str(pcb_path))

    # Route a bunch of nets so the PCB visibly contains tracks even without FreeRouting.
    # This is intentionally simple (straight lines) and is not production routing.
    preferred = ("GND", "3V3", "5V", "VBATT", "I2C_SDA", "I2C_SCL", "SPI1_SCK", "SPI1_MOSI", "SPI1_MISO")
    netinfo = board.GetNetsByName()
    blocked = {str(x) for x in (no_autoroute_nets or []) if str(x).strip()}
    names = [n for n in preferred if n in netinfo and n not in blocked]

    # If named rails aren't present, just route the first few nets we can find.
    if not names:
        if hasattr(netinfo, "keys"):
            names = [n for n in list(netinfo.keys()) if str(n) not in blocked][:40]
        else:  # pragma: no cover
            names = [n for n in list(netinfo) if str(n) not in blocked][:40]

    # Use the board's current track width where possible.
    try:
        width = int(board.GetDesignSettings().GetCurrentTrackWidth())
    except Exception:
        width = int(200000)  # ~0.2mm-ish in internal units (KiCad-dependent)

    max_tracks = 250
    added = 0
    for net_name in names:
        try:
            ni = netinfo[net_name]
        except Exception:
            continue
        net_code = int(ni.GetNetCode())
        pads = []
        for fp in board.GetFootprints():
            for pad in fp.Pads():
                if int(pad.GetNetCode()) == net_code:
                    pads.append(pad)
        if len(pads) < 2:
            continue
        # Connect pads in a chain: p0->p1->p2... This yields many tracks on dense nets.
        chain = pads[: min(len(pads), 30)]
        for a_pad, b_pad in zip(chain, chain[1:]):
            if added >= max_tracks:
                break
            a = a_pad.GetPosition()
            b = b_pad.GetPosition()
            t = pcbnew.PCB_TRACK(board)
            t.SetNetCode(net_code)
            t.SetWidth(width)
            # Alternate layers a bit so it looks more "routed".
            t.SetLayer(pcbnew.F_Cu if (added % 2 == 0) else pcbnew.B_Cu)
            t.SetStart(a)
            t.SetEnd(b)
            board.Add(t)
            added += 1
        if added >= max_tracks:
            break

    pcbnew.SaveBoard(str(pcb_path), board)
    logger.info("Fallback pcbnew routing added %s track(s).", added)


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
