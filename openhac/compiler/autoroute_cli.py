"""
Autorouter integration for OpenHaC.

Workflow:
  1. Export DSN: ``kicad-cli pcb export-dsn`` (KiCad 8) or ``pcbnew.ExportSpecctraDSN`` (KiCad 9+)
     (also used by ``--no-route`` so Specctra DSN exists without FreeRouting)
  2. Resolve FreeRouting jar path (parameter → FREEROUTING_JAR env var → error)
  3. Invoke FreeRouting jar, streaming stdout/stderr in real time + heartbeats
  4. Import SES: ``kicad-cli pcb import-ses`` or ``pcbnew.ImportSpecctraSES`` + save
"""

from __future__ import annotations

import json
import logging
import os
import re
import shlex
import shutil
import signal
import subprocess
import threading
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
    - If OPENHAC_FREEROUTING_CMD is set: argv template (JSON list or shlex tokens)
      with placeholders {dsn} and {ses}. Never executed via a shell.
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
        "or set OPENHAC_FREEROUTING_CMD to an argv template with {dsn} and {ses} "
        "(JSON list or space-separated; no shell), "
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


def _freerouting_gui_enabled() -> bool:
    """Whether to show the FreeRouting Java window.

    Default is headless (``--gui.enabled=false``). Enable with
    ``OPENHAC_FREEROUTING_GUI=1`` or ``openhac compile --freerouting-gui``.
    """
    v = (os.environ.get("OPENHAC_FREEROUTING_GUI") or "").strip().lower()
    return v in ("1", "true", "yes", "on")


def _freerouting_gui_flag() -> str:
    return "--gui.enabled=true" if _freerouting_gui_enabled() else "--gui.enabled=false"


def _freerouting_subprocess_timeout() -> float | None:
    """Return ``subprocess`` timeout seconds, or ``None`` for no limit.

    Env ``OPENHAC_FREEROUTING_TIMEOUT_S``:
    - unset / empty → default **1800** seconds (30 min) so CI/fab cannot hang forever;
      if the FreeRouting GUI is enabled, default is **no timeout** so the window is not killed
    - ``0`` / ``none`` / ``unlimited`` / ``off`` → no timeout
    - positive float → cap in seconds
    """
    v = (os.environ.get("OPENHAC_FREEROUTING_TIMEOUT_S") or "").strip().lower()
    if v in ("0", "none", "off", "unlimited", "infinity", "inf"):
        return None
    if not v:
        return None if _freerouting_gui_enabled() else 1800.0
    try:
        x = float(v)
    except ValueError:
        return 1800.0
    if x <= 0:
        return None
    return x


def _freerouting_argv(
    backend_kind: str,
    backend_val: str | list[str],
    dsn_path: Path,
    ses_path: Path,
) -> list[str]:
    """Build a FreeRouting argv list. Never wraps ``bash -c`` / ``bash -lc``."""
    dsn = str(dsn_path)
    ses = str(ses_path)
    user_dir = _prepare_freerouting_user_dir(dsn_path)
    user_data = f"--user_data_path={user_dir}"
    if backend_kind == "jar":
        argv = ["java"]
        xmx = _freerouting_xmx()
        if xmx:
            argv.append(f"-Xmx{xmx}")
        argv.extend(
            [
                "-jar",
                str(backend_val),
                user_data,
                _freerouting_gui_flag(),
                "-de",
                dsn,
                "-do",
                ses,
                f"--router.max_passes={_freerouting_max_passes()}",
                f"--router.max_threads={_freerouting_max_threads()}",
                "-mp",
                str(_freerouting_max_passes()),
                "-mt",
                str(_freerouting_max_threads()),
            ]
        )
        return argv
    if backend_kind == "cli":
        base = list(backend_val) if isinstance(backend_val, (list, tuple)) else [str(backend_val)]
        return [
            *base,
            user_data,
            _freerouting_gui_flag(),
            "-de",
            dsn,
            "-do",
            ses,
            f"--router.max_passes={_freerouting_max_passes()}",
            "-mp",
            str(_freerouting_max_passes()),
        ]
    tpl = str(backend_val).strip()
    if not tpl:
        raise AutorouterFailedError("OPENHAC_FREEROUTING_CMD is empty")
    if tpl.startswith("["):
        import json

        try:
            parts = json.loads(tpl)
        except json.JSONDecodeError as e:
            raise AutorouterFailedError(f"OPENHAC_FREEROUTING_CMD is not valid JSON: {e}") from e
        if not isinstance(parts, list) or not parts:
            raise AutorouterFailedError("OPENHAC_FREEROUTING_CMD JSON must be a non-empty argv list")
        return [str(p).format(dsn=dsn, ses=ses) for p in parts]
    rendered = tpl.format(dsn=dsn, ses=ses)
    argv = shlex.split(rendered)
    if not argv:
        raise AutorouterFailedError("OPENHAC_FREEROUTING_CMD produced an empty argv")
    if argv[0] in ("bash", "sh") and len(argv) >= 2 and argv[1] in ("-c", "-lc", "-l"):
        raise AutorouterFailedError(
            "OPENHAC_FREEROUTING_CMD must be an argv list (JSON or tokens), not a bash -c wrapper"
        )
    return argv


_UNROUTED_RE = re.compile(r"\((\d+)\s+unrouted\)", re.IGNORECASE)


def parse_freerouting_unrouted(line: str) -> int | None:
    """Parse ``(N unrouted)`` from a FreeRouting pass log line."""
    m = _UNROUTED_RE.search(line or "")
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


def _env_int(name: str, default: int, *, lo: int, hi: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return int(default)
    try:
        n = int(float(raw))
    except ValueError:
        return int(default)
    return max(lo, min(hi, n))


def _freerouting_max_passes() -> int:
    return _env_int("OPENHAC_FREEROUTING_MAX_PASSES", 12, lo=1, hi=200)


def _freerouting_max_threads() -> int:
    return _env_int("OPENHAC_FREEROUTING_MAX_THREADS", 4, lo=1, hi=64)


def _freerouting_plateau_passes() -> int:
    """Stop after this many pass logs without beating best unrouted (0 = off).

    Default is off: FreeRouting 2.1 only writes SES on a clean finish, so a
    plateau SIGINT discards every track. Pass limits go through
    ``FREEROUTING__ROUTER__STOP_PASS_NO`` instead (``-mp`` sets ``maxPasses``,
    which the headless batch loop does not read). GUI mode never plateau-kills
    the Java window.
    """
    if _freerouting_gui_enabled():
        return 0
    return _env_int("OPENHAC_FREEROUTING_PLATEAU_PASSES", 0, lo=0, hi=200)


def _freerouting_disable_optimizer() -> bool:
    raw = (os.environ.get("OPENHAC_FREEROUTING_DISABLE_OPTIMIZER") or "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def _prepare_freerouting_user_dir(dsn_path: Path) -> Path:
    """Per-job config dir so ``/tmp/freerouting/freerouting.json`` cannot force 9999 passes."""
    d = Path(dsn_path).resolve().parent / ".openhac-freerouting"
    d.mkdir(parents=True, exist_ok=True)
    cfg = {
        "gui": {"enabled": _freerouting_gui_enabled()},
        "router": {
            "max_passes": _freerouting_max_passes(),
            "max_threads": _freerouting_max_threads(),
            "fanout": {"enabled": False},
            "optimizer": {
                "enabled": not _freerouting_disable_optimizer(),
                "max_passes": 1,
                "max_threads": 1,
            },
        },
        "feature_flags": {"multi_threading": True, "snapshots": False},
    }
    (d / "freerouting.json").write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    return d


def _freerouting_child_env(user_dir: Path) -> dict[str, str]:
    """Env for the Java child.

    FreeRouting 2.1 headless ``BatchAutorouter`` loops while
    ``start_pass_no <= stop_pass_no``. Constructor default is stop=999.
    ``-mp`` only writes ``maxPasses``; GUI ``WindowWelcome`` copies that into
    ``stop_pass_no``, CLI ``InitializeCLI`` does not. Gson ``max_passes`` is
    also unused by the loop. ``FREEROUTING__ROUTER__STOP_PASS_NO`` is the
    field the maze router actually checks (cloned onto the RoutingJob).
    """
    env = {str(k): str(v) for k, v in os.environ.items()}
    passes = _freerouting_max_passes()
    env["FREEROUTING__USER_DATA_PATH"] = str(user_dir)
    env["FREEROUTING__GUI__ENABLED"] = "true" if _freerouting_gui_enabled() else "false"
    env["FREEROUTING__ROUTER__MAX_PASSES"] = str(passes)
    env["FREEROUTING__ROUTER__STOP_PASS_NO"] = str(passes)
    env["FREEROUTING__ROUTER__MAX_THREADS"] = str(_freerouting_max_threads())
    env["FREEROUTING__ROUTER__OPTIMIZER__ENABLED"] = (
        "false" if _freerouting_disable_optimizer() else "true"
    )
    return env


def _freerouting_ses_wait_s() -> float:
    """Seconds to wait after SIGINT for FreeRouting to flush ``-do`` SES."""
    v = (os.environ.get("OPENHAC_FREEROUTING_SES_WAIT_S") or "").strip().lower()
    if not v:
        return 20.0
    if v in ("0", "off", "none"):
        return 0.0
    try:
        return max(0.0, float(v))
    except ValueError:
        return 20.0


def _ses_ready(ses_path: Path) -> bool:
    try:
        return ses_path.is_file() and ses_path.stat().st_size > 64
    except OSError:
        return False


def _stop_java_for_ses(proc: subprocess.Popen, ses_path: Path) -> None:
    """Ask FreeRouting to exit so it can write ``-do`` SES, then escalate.

    2.1.0 only writes SES on a clean autorouter finish. SIGINT/SIGTERM give
    shutdown hooks a chance; SIGKILL (the old plateau path) discards the board.
    """
    wait_s = _freerouting_ses_wait_s()
    try:
        proc.send_signal(signal.SIGINT)
    except Exception:
        try:
            proc.terminate()
        except Exception:
            pass
    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            break
        if _ses_ready(ses_path):
            logger.info(
                "FreeRouting SES appeared after interrupt (%s bytes); waiting for exit.",
                ses_path.stat().st_size,
            )
            break
        time.sleep(0.3)
    if proc.poll() is None:
        try:
            proc.terminate()
        except Exception:
            pass
        try:
            proc.wait(timeout=15)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
    if proc.poll() is None:
        try:
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


def _freerouting_xmx() -> str | None:
    v = (os.environ.get("OPENHAC_FREEROUTING_XMX") or "8g").strip()
    if not v or v.lower() in ("0", "off", "none", "unlimited"):
        return None
    return v


def _tail(s: str, n: int = 4000) -> str:
    ss = s or ""
    if len(ss) <= n:
        return ss
    return ss[-n:]


def _freerouting_heartbeat_s() -> float:
    """Seconds between 'still running' INFO heartbeats (default 15). ``0`` disables."""
    v = (os.environ.get("OPENHAC_FREEROUTING_HEARTBEAT_S") or "").strip().lower()
    if not v:
        return 15.0
    if v in ("0", "off", "none", "false", "no"):
        return 0.0
    try:
        return max(0.0, float(v))
    except ValueError:
        return 15.0


def _freerouting_stream_log_level() -> int:
    """Level for FreeRouting child stdout/stderr lines.

    ``OPENHAC_FREEROUTING_STREAM_LOG``: ``info`` (default) | ``debug`` | ``warning``.
    """
    v = (os.environ.get("OPENHAC_FREEROUTING_STREAM_LOG") or "info").strip().lower()
    if v in ("debug", "dbg"):
        return logging.DEBUG
    if v in ("warning", "warn"):
        return logging.WARNING
    return logging.INFO


def _run_freerouting_subprocess(
    cmd: list[str],
    *,
    timeout_s: float | None,
    ses_path: Path,
    dsn_path: Path,
) -> tuple[int, str, str, float]:
    """Run FreeRouting with live stdout/stderr logging and periodic heartbeats.

    ``communicate()`` was used historically (avoids pipe deadlocks) but hid all
    progress until exit — dense boards look stalled. This streams both pipes on
    reader threads and emits elapsed-time heartbeats while the child is quiet.

    Returns ``(returncode, stdout_text, stderr_text, elapsed_s, meta)``.
    ``meta`` includes ``plateau`` when the process was stopped because unrouted
    count stopped improving.
    """
    stream_level = _freerouting_stream_log_level()
    heartbeat_s = _freerouting_heartbeat_s()
    plateau_n = _freerouting_plateau_passes()
    t0 = time.monotonic()
    out_chunks: list[str] = []
    err_chunks: list[str] = []
    lock = threading.Lock()
    last_activity = [t0]  # mutable box for reader threads
    progress: dict = {"best": None, "stale": 0, "stop": False, "plateau": False}

    def _note_unrouted(line: str) -> None:
        if plateau_n <= 0:
            return
        u = parse_freerouting_unrouted(line)
        if u is None:
            return
        with lock:
            best = progress["best"]
            if best is None or u < int(best):
                progress["best"] = u
                progress["stale"] = 0
            else:
                progress["stale"] = int(progress["stale"]) + 1
            if int(progress["stale"]) >= plateau_n and int(progress["best"] or 0) > 0:
                progress["stop"] = True
                progress["plateau"] = True

    def _pump(stream, *, label: str, sink: list[str]) -> None:
        try:
            for raw in iter(stream.readline, ""):
                if not raw:
                    break
                line = raw.rstrip("\n\r")
                with lock:
                    sink.append(raw)
                    last_activity[0] = time.monotonic()
                if line.strip():
                    logger.log(stream_level, "FreeRouting %s: %s", label, line)
                if label == "stdout":
                    _note_unrouted(line)
        finally:
            try:
                stream.close()
            except Exception:
                pass

    user_dir = _prepare_freerouting_user_dir(dsn_path)
    child_env = _freerouting_child_env(user_dir)
    logger.info(
        "FreeRouting running (dsn=%s → ses=%s; stop_pass=%s; heartbeat every %ss; timeout=%s)",
        dsn_path.name,
        ses_path.name,
        child_env.get("FREEROUTING__ROUTER__STOP_PASS_NO"),
        int(heartbeat_s) if heartbeat_s >= 1 else (f"{heartbeat_s:g}" if heartbeat_s else "off"),
        f"{timeout_s:g}s" if timeout_s else "none",
    )

    with subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        env=child_env,
    ) as proc:
        assert proc.stdout is not None and proc.stderr is not None
        t_out = threading.Thread(
            target=_pump, args=(proc.stdout,), kwargs={"label": "stdout", "sink": out_chunks}, daemon=True
        )
        t_err = threading.Thread(
            target=_pump, args=(proc.stderr,), kwargs={"label": "stderr", "sink": err_chunks}, daemon=True
        )
        t_out.start()
        t_err.start()

        try:
            while True:
                rc = proc.poll()
                if rc is not None:
                    break
                now = time.monotonic()
                elapsed = now - t0
                with lock:
                    want_stop = bool(progress["stop"])
                if want_stop:
                    logger.warning(
                        "FreeRouting plateau: unrouted stuck at %s for %s pass logs; stopping Java.",
                        progress.get("best"),
                        plateau_n,
                    )
                    _stop_java_for_ses(proc, ses_path)
                    break
                if timeout_s is not None and elapsed >= timeout_s:
                    try:
                        proc.kill()
                    except Exception:
                        pass
                    t_out.join(timeout=5)
                    t_err.join(timeout=5)
                    out = "".join(out_chunks)
                    err = "".join(err_chunks)
                    raise AutorouterFailedError(
                        "FreeRouting timed out after "
                        f"{timeout_s}s. stdout_tail={_tail(out)} stderr_tail={_tail(err)}"
                    )
                if heartbeat_s > 0:
                    quiet = now - last_activity[0]
                    ses_note = ""
                    try:
                        if ses_path.exists():
                            ses_note = f"; SES growing ({ses_path.stat().st_size} bytes)"
                        else:
                            ses_note = "; SES not written yet"
                    except OSError:
                        ses_note = ""
                    logger.info(
                        "FreeRouting still running… elapsed=%.0fs quiet=%.0fs "
                        "stdout_lines=%d stderr_lines=%d%s",
                        elapsed,
                        quiet,
                        len(out_chunks),
                        len(err_chunks),
                        ses_note,
                    )
                    # Sleep in short slices so timeout/exit react quickly.
                    deadline = now + heartbeat_s
                    while time.monotonic() < deadline:
                        if proc.poll() is not None:
                            break
                        with lock:
                            if progress["stop"]:
                                break
                        if timeout_s is not None and (time.monotonic() - t0) >= timeout_s:
                            break
                        time.sleep(min(0.5, deadline - time.monotonic()))
                else:
                    time.sleep(0.5)
        except AutorouterFailedError:
            raise
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
            raise

        t_out.join(timeout=30)
        t_err.join(timeout=30)
        rc = int(proc.returncode if proc.returncode is not None else -1)
        elapsed = time.monotonic() - t0
        meta = {
            "plateau": bool(progress.get("plateau")),
            "best_unrouted": progress.get("best"),
        }
        return rc, "".join(out_chunks), "".join(err_chunks), elapsed, meta


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


def export_dsn_with_ipc_widths(
    pcb_path: str | Path,
    *,
    required_netclass_widths_mm: dict[str, float] | None = None,
    require_dsn_widths: bool | None = None,
    dsn_path: str | Path | None = None,
) -> Path:
    """Write a Specctra DSN with IPC-2152 class/net widths patched in.

    Independent of FreeRouting. Callers can re-export after KiCad placement edits
    without running ``openhac compile`` (which would replace footprints).

    If *required_netclass_widths_mm* has no per-net map, widths are read from the
    saved ``.kicad_pcb`` / sibling ``.kicad_pro`` netclasses.
    """
    pcb = Path(pcb_path)
    out = Path(dsn_path) if dsn_path else pcb.with_suffix(".dsn")
    try:
        from openhac.compiler.project_gen import restore_kicad_pro_net_settings

        restore_kicad_pro_net_settings(pcb)
    except Exception as e:
        logger.debug("KiCad net_settings restore before DSN skipped: %s", e)
    logger.info("Exporting DSN from %s ...", pcb)
    try:
        _export_specctra_dsn(pcb, out)
    except AutorouterFailedError:
        raise
    except Exception as e:
        raise AutorouterFailedError(f"Specctra DSN export failed: {e}") from e

    try:
        from openhac.compiler.pcb_physics import (
            assert_dsn_netclass_widths,
            collect_net_widths_mm_from_pcb,
            patch_dsn_ipc_widths,
        )

        net_map = None
        class_map: dict[str, float] = {}
        if required_netclass_widths_mm:
            raw = required_netclass_widths_mm.get("__net_widths_mm__")
            if isinstance(raw, dict):
                net_map = {str(k): float(v) for k, v in raw.items()}
            class_map = {
                str(k): float(v)
                for k, v in required_netclass_widths_mm.items()
                if k != "__net_widths_mm__" and isinstance(v, (int, float))
            }
        if not net_map:
            collected = collect_net_widths_mm_from_pcb(pcb)
            if collected:
                net_map = collected
                logger.info(
                    "IPC/DSN: using %d net width(s) from saved PCB/project netclasses.",
                    len(collected),
                )
            else:
                logger.warning(
                    "IPC/DSN: no netclass widths found on %s, %s, or %s; "
                    "KiCad Specctra export may flatten everything to 0.2 mm.",
                    pcb.name,
                    pcb.with_suffix(".kicad_pro").name,
                    pcb.with_name(pcb.stem + ".openhac-netclasses.json").name,
                )
        if net_map:
            n = patch_dsn_ipc_widths(out, net_map)
            if n:
                logger.info("IPC/DSN: patched FreeRouting widths for %d net(s).", n)

        if require_dsn_widths is None:
            strict_dsn = (os.environ.get("OPENHAC_REQUIRE_DSN_WIDTHS") or "").strip().lower() in (
                "1",
                "true",
                "yes",
                "on",
                "force",
            )
        else:
            strict_dsn = bool(require_dsn_widths)
        if strict_dsn and not net_map and not class_map:
            raise AutorouterFailedError(
                "IPC/DSN: --strict requested but no compile-time netclass widths were found "
                f"(need {pcb.with_suffix('.kicad_pro').name} net_settings or "
                f"{pcb.with_name(pcb.stem + '.openhac-netclasses.json').name})."
            )
        assert_dsn_netclass_widths(
            out,
            required_widths_mm=class_map or None,
            net_widths_mm=net_map,
            strict=strict_dsn,
        )
    except AutorouterFailedError:
        raise
    except Exception as e:
        logger.debug("DSN width assert/patch skipped: %s", e)
    return out


def run_freerouting(
    pcb_path: str,
    freerouting_jar_path: str = None,
    *,
    required_netclass_widths_mm: dict[str, float] | None = None,
    require_dsn_widths: bool | None = None,
) -> None:
    """Run the FreeRouting autorouter on *pcb_path*.

    Args:
        pcb_path: Path to the .kicad_pcb file to route.
        freerouting_jar_path: Optional explicit path to the FreeRouting jar.
            Falls back to the FREEROUTING_JAR environment variable.
        required_netclass_widths_mm: Optional IPC class → min width (mm) to assert
            in the Specctra DSN before FreeRouting runs.
        require_dsn_widths: Override ``OPENHAC_REQUIRE_DSN_WIDTHS`` for hard-fail.

    Raises:
        FreeRoutingNotFoundError: Jar path cannot be resolved (DSN is still written first).
        AutorouterFailedError: DSN export, FreeRouting invocation, or SES import fails.
    """
    # --- 9.2: Export DSN (even if FreeRouting is missing), then resolve the router ---
    pcb = Path(pcb_path)
    dsn_path = pcb.with_suffix(".dsn")
    ses_path = pcb.with_suffix(".ses")

    export_dsn_with_ipc_widths(
        pcb_path,
        required_netclass_widths_mm=required_netclass_widths_mm,
        require_dsn_widths=require_dsn_widths,
    )

    backend_kind, backend_val = _resolve_freerouting_backend(freerouting_jar_path)

    # --- 9.3: Invoke FreeRouting with real-time stdout streaming ---
    cmd = None
    if backend_kind == "jar":
        logger.info(
            "Starting FreeRouting%s: java -jar %s ...",
            " (GUI)" if _freerouting_gui_enabled() else " (headless)",
            backend_val,
        )
        cmd = _freerouting_argv("jar", backend_val, dsn_path, ses_path)
    elif backend_kind == "cli":
        cmd = _freerouting_argv("cli", backend_val, dsn_path, ses_path)
        logger.info("Starting FreeRouting via CLI: %s ...", " ".join(cmd or []))
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
        # User provided an argv template (JSON list or shlex tokens). No shell.
        cmd = _freerouting_argv("cmd_tpl", backend_val, dsn_path, ses_path)
        logger.info("Starting FreeRouting via OPENHAC_FREEROUTING_CMD: %s", " ".join(cmd or []))

    if backend_kind == "api":
        # Proceed to SES import step below.
        cmd = None

    if cmd is not None:
        # Default timeout is 1800s (see ``_freerouting_subprocess_timeout``).
        # Set OPENHAC_FREEROUTING_TIMEOUT_S=unlimited for no wall-clock cap.
        timeout_s = _freerouting_subprocess_timeout()
        rc, out, err, dt, meta = _run_freerouting_subprocess(
            cmd,
            timeout_s=timeout_s,
            ses_path=ses_path,
            dsn_path=dsn_path,
        )
        plateau = bool((meta or {}).get("plateau"))
        if rc != 0 and not (plateau and ses_path.exists()):
            if plateau:
                logger.warning(
                    "FreeRouting stopped on plateau after %.1fs (rc=%s, best_unrouted=%s) with no SES.",
                    dt,
                    rc,
                    (meta or {}).get("best_unrouted"),
                )
            else:
                raise AutorouterFailedError(
                    f"FreeRouting exited with code {rc} after {dt:.1f}s:\n{_tail(err or out)}"
                )
        elif plateau:
            logger.info(
                "FreeRouting plateau-stop in %.1fs (rc=%s, best_unrouted=%s).",
                dt,
                rc,
                (meta or {}).get("best_unrouted"),
            )
        else:
            logger.info("FreeRouting process finished in %.1fs (exit 0).", dt)

    # --- 9.4: Verify SES and import ---
    if not ses_path.exists():
        if cmd is None:
            raise AutorouterFailedError(
                f"FreeRouting completed but no SES output was produced at {ses_path}"
            )
        logger.warning(
            "No SES at %s; skipping import (leftover A* can still route the PCB).",
            ses_path,
        )
        return

    logger.info(f"Importing SES {ses_path} into {pcb_path} ...")
    try:
        _import_specctra_ses(pcb, ses_path)
    except AutorouterFailedError:
        raise
    except Exception as e:
        raise AutorouterFailedError(f"Specctra SES import failed: {e}") from e

    logger.info(f"Autorouting complete: {pcb_path}")
