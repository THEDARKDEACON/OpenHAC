from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from openhac.compiler.autoroute_cli import AutorouterFailedError, run_freerouting


def test_run_freerouting_does_not_deadlock_on_stderr(monkeypatch, tmp_path: Path):
    pcb = tmp_path / "board.kicad_pcb"
    pcb.write_text("(kicad_pcb (version 20211014))\n", encoding="utf-8")

    # 1) Stub kicad-cli calls to create expected DSN/SES files.
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

    # 2) Replace Popen with a real child that writes a lot to stderr quickly.
    real_popen = subprocess.Popen

    def fake_popen(_args, **kwargs):
        # Write ~1MB to stderr and exit nonzero.
        code = (
            "import sys\n"
            "sys.stderr.write('X' * (1024 * 1024))\n"
            "sys.stderr.flush()\n"
            "sys.exit(7)\n"
        )
        return real_popen([os.environ.get("PYTHON", "python3"), "-c", code], **kwargs)

    monkeypatch.setattr("openhac.compiler.autoroute_cli.subprocess.Popen", fake_popen)

    # Make sure test fails fast if something regresses.
    monkeypatch.setenv("OPENHAC_FREEROUTING_TIMEOUT_S", "2")

    with pytest.raises(AutorouterFailedError) as ei:
        run_freerouting(str(pcb), freerouting_jar_path="whatever.jar")

    # It should not hang and should include the captured stderr tail.
    msg = str(ei.value)
    assert "FreeRouting exited with code" in msg
    assert "X" in msg

