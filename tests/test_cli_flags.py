from __future__ import annotations


def test_openhac_compile_help_includes_new_flags():
    import subprocess
    import sys

    cp = subprocess.run(
        [sys.executable, "-m", "openhac", "compile", "--help"],
        check=True,
        capture_output=True,
        text=True,
    )
    out = cp.stdout
    assert "--skip-layout" in out
    assert "--require-verified-parts" in out
    assert "--deterministic" in out


def test_openhac_doctor_supports_db_path_override():
    import subprocess
    import sys
    import json
    from pathlib import Path

    p = Path("/tmp/openhac_test_db_override.db")
    cp = subprocess.run(
        [sys.executable, "-m", "openhac", "--db-path", str(p), "doctor", "--json"],
        check=True,
        capture_output=True,
        text=True,
    )
    data = json.loads(cp.stdout)
    assert data.get("openhac_db_path") == str(p)
