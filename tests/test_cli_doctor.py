from __future__ import annotations


def test_openhac_doctor_runs_json():
    import subprocess
    import sys
    import json

    cp = subprocess.run(
        [sys.executable, "-m", "openhac", "doctor", "--json"],
        check=True,
        capture_output=True,
        text=True,
    )
    data = json.loads(cp.stdout)
    assert "python_executable" in data
    assert "kicad_cli_path" in data
    assert "kicad_cli_version" in data
    assert "kicad_cli_ok" in data
    assert "kicad_symbol_search_paths" in data
    assert isinstance(data["kicad_symbol_search_paths"], list)
    assert "ok" in data
    assert "missing" in data
    assert isinstance(data["missing"], list)
    assert "pcbnew_present" in data
    assert "pcbnew_import_ok" in data
    assert "java_present" in data
    assert "freerouting_jar_exists" in data
    assert "vendor_apis_configured" in data
    assert "vendor_api_env_present" in data
    assert isinstance(data["vendor_api_env_present"], dict)
    assert "fp_lib_table_present" in data
    assert "sym_lib_table_present" in data
    assert "openhac_allow_risky_parts" in data
    assert "openhac_require_verified_parts" in data
    assert "kicad_env" in data
    assert isinstance(data["kicad_env"], dict)
    assert isinstance(data.get("fp_lib_table_candidates"), list)
    assert isinstance(data.get("sym_lib_table_candidates"), list)
    assert "fp_lib_table_present" in data
    assert "sym_lib_table_present" in data
