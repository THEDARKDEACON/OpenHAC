from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

from openhac.compiler.autoroute_cli import run_freerouting


def test_run_freerouting_emits_heartbeat_and_streams_stdout(monkeypatch, tmp_path: Path):
    pcb = tmp_path / "board.kicad_pcb"
    pcb.write_text("(kicad_pcb (version 20211014))\n", encoding="utf-8")

    def fake_run(args, capture_output, text):  # noqa: ARG001
        if args[:4] == ["kicad-cli", "pcb", "export-dsn", str(pcb)]:
            out_idx = args.index("--output") + 1
            Path(args[out_idx]).write_text("dsn\n", encoding="utf-8")
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")
        if args[:4] == ["kicad-cli", "pcb", "import-ses", str(pcb)]:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")
        raise AssertionError(f"unexpected subprocess.run args: {args}")

    monkeypatch.setattr("openhac.compiler.autoroute_cli.subprocess.run", fake_run)
    monkeypatch.setattr(
        "openhac.compiler.autoroute_cli._resolve_freerouting_backend",
        lambda _p: ("jar", str(tmp_path / "ignored.jar")),
    )

    real_popen = subprocess.Popen

    def fake_popen(_args, **kwargs):
        # Slow child so at least one heartbeat fires; also prints a progress line.
        code = (
            "import sys, time\n"
            "print('autoroute pass 1', flush=True)\n"
            "time.sleep(1.2)\n"
            "open(sys.argv[1], 'w').write('ses')\n"
        )
        ses = str(pcb.with_suffix(".ses"))
        return real_popen([os.environ.get("PYTHON", "python3"), "-c", code, ses], **kwargs)

    monkeypatch.setattr("openhac.compiler.autoroute_cli.subprocess.Popen", fake_popen)
    monkeypatch.setenv("OPENHAC_FREEROUTING_HEARTBEAT_S", "0.4")
    monkeypatch.setenv("OPENHAC_FREEROUTING_TIMEOUT_S", "10")

    # Capture on the autoroute logger directly (pytest caplog/root filtering is unreliable
    # with ROS/ament logging plugins in this environment).
    records: list[str] = []

    class _Probe(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record.getMessage())

    probe = _Probe()
    probe.setLevel(logging.DEBUG)
    log = logging.getLogger("openhac.autoroute")
    prev_level = log.level
    log.addHandler(probe)
    log.setLevel(logging.DEBUG)
    try:
        run_freerouting(str(pcb), freerouting_jar_path="whatever.jar")
    finally:
        log.removeHandler(probe)
        log.setLevel(prev_level)

    text = "\n".join(records)
    assert "FreeRouting still running" in text
    assert "FreeRouting stdout: autoroute pass 1" in text
    assert "FreeRouting process finished" in text
