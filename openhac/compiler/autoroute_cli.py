"""
Autorouter integration for OpenHaC.

Workflow:
  1. Resolve FreeRouting jar path (parameter → FREEROUTING_JAR env var → error)
  2. Export DSN: ``kicad-cli pcb export-dsn`` (KiCad 8) or ``pcbnew.ExportSpecctraDSN`` (KiCad 9+)
  3. Invoke FreeRouting jar, streaming stdout in real time
  4. Import SES: ``kicad-cli pcb import-ses`` or ``pcbnew.ImportSpecctraSES`` + save
"""

import logging
import os
import shutil
import subprocess
import time
from pathlib import Path

logger = logging.getLogger("openhac.autoroute")

from openhac.core.base import FreeRoutingNotFoundError, AutorouterFailedError


def _export_specctra_dsn(pcb: Path, dsn_path: Path) -> None:
    """Export Specctra DSN via ``kicad-cli`` (KiCad 8) or ``pcbnew`` (KiCad 9+ dropped CLI Specctra)."""
    r: subprocess.CompletedProcess[str] | None
    try:
        r = subprocess.run(
            ["kicad-cli", "pcb", "export-dsn", str(pcb), "--output", str(dsn_path)],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as e:
        logger.debug("kicad-cli missing for export-dsn, trying pcbnew: %s", e)
        r = None
    if r is not None and r.returncode == 0:
        return
    cli_err = ""
    if r is not None:
        cli_err = "\n".join(
            x
            for x in ((r.stderr or "").strip(), (r.stdout or "").strip())
            if x
        )
    try:
        import pcbnew  # type: ignore
    except Exception as e:
        raise AutorouterFailedError(
            "kicad-cli pcb export-dsn is not available on this KiCad build, and pcbnew could not be "
            f"imported for Specctra export: {e}\n"
            f"CLI output:\n{cli_err}"
        ) from e
    board = pcbnew.LoadBoard(str(pcb))
    ok = pcbnew.ExportSpecctraDSN(board, str(dsn_path.resolve()))
    if not ok:
        raise AutorouterFailedError(
            f"pcbnew.ExportSpecctraDSN failed for {pcb} (after kicad-cli failed). CLI output:\n{cli_err}"
        )
    logger.info("Exported Specctra DSN via pcbnew (KiCad 9+ style).")


def _import_specctra_ses(pcb: Path, ses_path: Path) -> None:
    """Import Specctra SES via ``kicad-cli`` (KiCad 8) or ``pcbnew`` (KiCad 9+)."""
    r: subprocess.CompletedProcess[str] | None
    try:
        r = subprocess.run(
            ["kicad-cli", "pcb", "import-ses", str(pcb), "--input", str(ses_path)],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as e:
        logger.debug("kicad-cli missing for import-ses, trying pcbnew: %s", e)
        r = None
    if r is not None and r.returncode == 0:
        return
    cli_err = ""
    if r is not None:
        cli_err = "\n".join(
            x
            for x in ((r.stderr or "").strip(), (r.stdout or "").strip())
            if x
        )
    try:
        import pcbnew  # type: ignore
    except Exception as e:
        raise AutorouterFailedError(
            "kicad-cli pcb import-ses is not available on this KiCad build, and pcbnew could not be "
            f"imported for Specctra import: {e}\n"
            f"CLI output:\n{cli_err}"
        ) from e
    board = pcbnew.LoadBoard(str(pcb))
    ok = pcbnew.ImportSpecctraSES(board, str(ses_path.resolve()))
    if not ok:
        raise AutorouterFailedError(
            f"pcbnew.ImportSpecctraSES failed for {pcb} (after kicad-cli failed). CLI output:\n{cli_err}"
        )
    pcbnew.SaveBoard(str(pcb.resolve()), board)
    logger.info("Imported Specctra SES via pcbnew (KiCad 9+ style).")


def _resolve_freerouting_backend(freerouting_jar_path: str | None) -> tuple[str, str | list[str]]:
    """Resolve a FreeRouting backend.

    Order:
    - If OPENHAC_FREEROUTING_CMD is set: use it as a shell-style command template.
      It must accept placeholders {dsn} and {ses}.
    - If a known CLI wrapper exists on PATH (freeroute-cli / freeroute / freerouting): use it.
    - Else fall back to jar path (arg or FREEROUTING_JAR).
    """
    cmd_tpl = (os.environ.get("OPENHAC_FREEROUTING_CMD") or "").strip()
    if cmd_tpl:
        return ("cmd_tpl", cmd_tpl)

    for exe in ("freeroute-cli", "freeroute", "freerouting"):
        p = shutil.which(exe)
        if p:
            return ("cli", [p])

    # Freerouting API client (freerouting-client package). This is not a local CLI.
    api_key = (os.environ.get("OPENHAC_FREEROUTING_API_KEY") or "").strip()
    if api_key:
        try:
            import freerouting  # type: ignore
            _ = freerouting.FreeroutingClient
            return ("api", api_key)
        except Exception:
            # If the package isn't importable, fall through to jar resolution.
            pass

    jar = (freerouting_jar_path or os.environ.get("FREEROUTING_JAR") or "").strip()
    if jar:
        return ("jar", jar)

    raise FreeRoutingNotFoundError(
        "FreeRouting backend not found. Set FREEROUTING_JAR to a freerouting.jar, "
        "or install a CLI wrapper on PATH (freeroute-cli/freeroute), "
        "or set OPENHAC_FREEROUTING_CMD (template with {dsn} and {ses}), "
        "or set OPENHAC_FREEROUTING_API_KEY to use freerouting-client (cloud API)."
    )


def _env_timeout_seconds(name: str, default_s: float) -> float:
    v = os.environ.get(name, "").strip()
    if not v:
        return float(default_s)
    try:
        return float(v)
    except ValueError:
        return float(default_s)


def _freerouting_subprocess_timeout() -> float | None:
    """Return ``subprocess`` timeout seconds, or ``None`` for no limit.

    Env ``OPENHAC_FREEROUTING_TIMEOUT_S``:
    - unset / empty / ``0`` / ``none`` / ``unlimited`` / ``off`` → no timeout
    - positive float → cap in seconds
    """
    v = (os.environ.get("OPENHAC_FREEROUTING_TIMEOUT_S") or "").strip().lower()
    if not v or v in ("0", "none", "off", "unlimited", "infinity", "inf"):
        return None
    try:
        x = float(v)
    except ValueError:
        return None
    if x <= 0:
        return None
    return x


def _tail(s: str, n: int = 4000) -> str:
    ss = s or ""
    if len(ss) <= n:
        return ss
    return ss[-n:]


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
    backend_kind, backend_val = _resolve_freerouting_backend(freerouting_jar_path)

    pcb = Path(pcb_path)
    dsn_path = pcb.with_suffix(".dsn")
    ses_path = pcb.with_suffix(".ses")

    logger.info(f"Exporting DSN from {pcb_path} ...")
    try:
        _export_specctra_dsn(pcb, dsn_path)
    except AutorouterFailedError:
        raise
    except Exception as e:
        raise AutorouterFailedError(f"Specctra DSN export failed: {e}") from e

    # --- 9.3: Invoke FreeRouting with real-time stdout streaming ---
    if backend_kind == "jar":
        logger.info("Starting FreeRouting: java -jar %s ...", backend_val)
        cmd = ["java", "-jar", str(backend_val), "-de", str(dsn_path), "-do", str(ses_path)]
    elif backend_kind == "cli":
        # Best-effort: most wrappers forward to the jar and accept -de/-do.
        cmd = list(backend_val) + ["-de", str(dsn_path), "-do", str(ses_path)]
        logger.info("Starting FreeRouting via CLI: %s ...", " ".join(cmd))
    elif backend_kind == "api":
        # Cloud API routing via freerouting-client package.
        try:
            import freerouting  # type: ignore
        except Exception as e:
            raise AutorouterFailedError(f"freerouting-client import failed: {e}")

        base_url = (os.environ.get("OPENHAC_FREEROUTING_API_URL") or "").strip() or "https://api.freerouting.app"
        timeout_s = _env_timeout_seconds("OPENHAC_FREEROUTING_TIMEOUT_S", 1800.0)
        poll_s = int(_env_timeout_seconds("OPENHAC_FREEROUTING_POLL_S", 5.0))
        try:
            client = freerouting.FreeroutingClient(api_key=str(backend_val), base_url=base_url)
            out = client.run_routing_job(
                name=pcb.stem,
                dsn_file_path=str(dsn_path),
                settings=None,
                poll_interval=poll_s,
                timeout=int(timeout_s),
            )
            # Persist SES to expected location if API returned data.
            try:
                client.download_output(out.get("job_id") or out.get("id") or "", output_path=str(ses_path))
            except Exception:
                # Many API responses already contain base64 `data`; use the helper.
                try:
                    client.download_output(out.get("id") or "", output_path=str(ses_path))
                except Exception:
                    # If `out` has 'data', decode manually.
                    import base64
                    if isinstance(out, dict) and out.get("data"):
                        Path(ses_path).write_bytes(base64.b64decode(out["data"]))
        except Exception as e:
            raise AutorouterFailedError(f"FreeRouting API routing failed: {e}") from e
    else:
        # User provided a template.
        tpl = str(backend_val)
        rendered = tpl.format(dsn=str(dsn_path), ses=str(ses_path))
        cmd = ["bash", "-lc", rendered]
        logger.info("Starting FreeRouting via OPENHAC_FREEROUTING_CMD ...")

    if backend_kind == "api":
        # Proceed to SES import step below.
        cmd = None

    if cmd is not None:
        # Default: no wall-clock timeout (FreeRouting may run a long time on dense boards).
        # Set OPENHAC_FREEROUTING_TIMEOUT_S to a positive number of seconds to cap runtime.
        timeout_s = _freerouting_subprocess_timeout()
        t0 = time.monotonic()
        with subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,  # line-buffered
        ) as proc:
            try:
                out, err = proc.communicate(timeout=timeout_s)
            except subprocess.TimeoutExpired as e:
                try:
                    proc.kill()
                except Exception:
                    pass
                try:
                    out2, err2 = proc.communicate(timeout=5)
                except Exception:
                    out2, err2 = "", ""
                raise AutorouterFailedError(
                    "FreeRouting timed out after "
                    f"{timeout_s}s. stdout_tail={_tail(out2)} stderr_tail={_tail(err2)}"
                ) from e

        if out:
            for line in out.splitlines():
                logger.debug(line.rstrip())

        if proc.returncode != 0:
            dt = time.monotonic() - t0
            raise AutorouterFailedError(
                f"FreeRouting exited with code {proc.returncode} after {dt:.1f}s:\n{_tail(err)}"
            )

    # --- 9.4: Verify SES and import ---
    if not ses_path.exists():
        raise AutorouterFailedError(
            f"FreeRouting completed but no SES output was produced at {ses_path}"
        )

    logger.info(f"Importing SES {ses_path} into {pcb_path} ...")
    try:
        _import_specctra_ses(pcb, ses_path)
    except AutorouterFailedError:
        raise
    except Exception as e:
        raise AutorouterFailedError(f"Specctra SES import failed: {e}") from e

    logger.info(f"Autorouting complete: {pcb_path}")
