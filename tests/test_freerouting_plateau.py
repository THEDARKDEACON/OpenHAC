from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

from openhac.compiler.autoroute_cli import run_freerouting


def test_run_freerouting_stops_on_unrouted_plateau(monkeypatch, tmp_path: Path):
    pcb = tmp_path / "board.kicad_pcb"
    pcb.write_text("(kicad_pcb (version 20211014))\n", encoding="utf-8")

    def fake_run(args, capture_output, text):  # noqa: ARG001
        if args[:4] == ["kicad-cli", "pcb", "export-dsn", str(pcb)]:
            out_idx = args.index("--output") + 1
            Path(args[out_idx]).write_text("dsn\n", encoding="utf-8")
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")
        if len(args) >= 4 and args[0] == "kicad-cli" and "import-ses" in args:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")
        raise AssertionError(f"unexpected subprocess.run args: {args}")

    monkeypatch.setattr("openhac.compiler.autoroute_cli.subprocess.run", fake_run)
    monkeypatch.setattr(
        "openhac.compiler.autoroute_cli._resolve_freerouting_backend",
        lambda _p: ("jar", str(tmp_path / "ignored.jar")),
    )

    real_popen = subprocess.Popen

    def fake_popen(args, **kwargs):
        ses = str(pcb.with_suffix(".ses"))
        try:
            do_i = list(args).index("-do")
            ses = str(args[do_i + 1])
        except Exception:
            pass
        code = (
            "import signal, sys, time\n"
            "ses = sys.argv[1]\n"
            "def _flush(signum, frame):\n"
            "    open(ses, 'w', encoding='utf-8').write('(session dummy)\\n')\n"
            "    raise SystemExit(0)\n"
            "signal.signal(signal.SIGINT, _flush)\n"
            "signal.signal(signal.SIGTERM, _flush)\n"
            "for i in range(40):\n"
            "    print('Auto-router pass #%d score of 1.0 (12 unrouted)' % i, flush=True)\n"
            "    time.sleep(0.08)\n"
        )
        return real_popen([os.environ.get("PYTHON", "python3"), "-c", code, ses], **kwargs)

    monkeypatch.setattr("openhac.compiler.autoroute_cli.subprocess.Popen", fake_popen)
    monkeypatch.delenv("OPENHAC_FREEROUTING_GUI", raising=False)
    monkeypatch.setenv("OPENHAC_FREEROUTING_HEARTBEAT_S", "0.15")
    monkeypatch.setenv("OPENHAC_FREEROUTING_TIMEOUT_S", "8")
    monkeypatch.setenv("OPENHAC_FREEROUTING_PLATEAU_PASSES", "4")
    monkeypatch.setenv("OPENHAC_FREEROUTING_XMX", "off")
    monkeypatch.setenv("OPENHAC_FREEROUTING_SES_WAIT_S", "2")

    records: list[str] = []

    class _Probe(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record.getMessage())

    probe = _Probe()
    log = logging.getLogger("openhac.autoroute")
    log.addHandler(probe)
    prev = log.level
    log.setLevel(logging.DEBUG)
    try:
        run_freerouting(str(pcb), freerouting_jar_path="whatever.jar")
    finally:
        log.removeHandler(probe)
        log.setLevel(prev)

    text = "\n".join(records)
    assert "plateau" in text.lower()
    assert pcb.with_suffix(".ses").exists()
