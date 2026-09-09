"""Tests for universal KiCad version agnosticism (v6 through v10)."""

import os
from pathlib import Path
import tempfile
import pytest

from openhac.core.kicad_version import (
    KiCadVersion,
    detect_kicad_version,
    parse_kicad_version_str,
    resolve_target_kicad_version,
    apply_universal_kicad_env,
)
from openhac.core.board import Board


def test_parse_kicad_version_strings():
    """Verify semantic parsing of various KiCad version formats."""
    v9 = parse_kicad_version_str("kicad-cli 9.0.9")
    assert v9 is not None
    assert v9.major == 9 and v9.minor == 0 and v9.patch == 9
    assert v9.sch_format_date == 20241209
    assert v9.pcb_format_date == 20240108
    assert v9.supports_cli is True
    assert v9.swig_deprecated is True
    assert v9.supports_ipc_api is False

    v10 = parse_kicad_version_str("KiCad 10.0.6~ubuntu24.04.1")
    assert v10 is not None
    assert v10.major == 10 and v10.minor == 0 and v10.patch == 6
    assert v10.sch_format_date == 20250101
    assert v10.pcb_format_date == 20250101
    assert v10.supports_ipc_api is True

    v7 = parse_kicad_version_str("7.0.10-unknown")
    assert v7 is not None
    assert v7.major == 7 and v7.minor == 0 and v7.patch == 10
    assert v7.sch_format_date == 20230121
    assert v7.pcb_format_date == 20221018

    v6 = parse_kicad_version_str("6.0.11")
    assert v6 is not None
    assert v6.major == 6 and v6.minor == 0 and v6.patch == 11
    assert v6.sch_format_date == 20211123
    assert v6.pcb_format_date == 20211014
    assert v6.supports_cli is False


def test_detect_kicad_version_host():
    """Verify host detection returns a valid version on a configured environment."""
    detected = detect_kicad_version()
    # If kicad-cli is installed (as it is in this environment), it should detect 9
    if detected:
        assert detected.major in (6, 7, 8, 9, 10)
        assert detected.sch_format_date > 20200000


def test_resolve_target_kicad_version_precedence(monkeypatch):
    """Test resolution priority: explicit > board > env > detected > default."""
    # 1. Explicit target wins unconditionally
    t = resolve_target_kicad_version(explicit_target=7)
    assert t.major == 7
    assert t.sch_format_date == 20230121

    # 2. Board configuration
    b = Board((50, 50), target_kicad=10)
    t = resolve_target_kicad_version(board=b)
    assert t.major == 10
    assert t.sch_format_date == 20250101

    # Explicit override over board
    t = resolve_target_kicad_version(explicit_target=6, board=b)
    assert t.major == 6
    assert t.sch_format_date == 20211123

    # 3. Environment variable OPENHAC_TARGET_KICAD
    monkeypatch.setenv("OPENHAC_TARGET_KICAD", "8")
    t = resolve_target_kicad_version()
    assert t.major == 8
    assert t.sch_format_date == 20231120

    # Board beats env
    t = resolve_target_kicad_version(board=b)
    assert t.major == 10

    # 4. Fallback to default when nothing set and detection mocked out
    monkeypatch.delenv("OPENHAC_TARGET_KICAD", raising=False)
    monkeypatch.setattr("openhac.core.kicad_version.detect_kicad_version", lambda: None)
    t = resolve_target_kicad_version()
    assert t.major == 8  # universal default
    assert t.sch_format_date == 20231120


def test_apply_universal_kicad_env(monkeypatch):
    """Verify that universal env aliasing distributes paths across KICAD 6 through 10."""
    with tempfile.TemporaryDirectory() as tmp:
        sym_dir = Path(tmp) / "symbols"
        sym_dir.mkdir()
        monkeypatch.setenv("KICAD_SYMBOL_DIR", str(sym_dir))
        # Clear versioned keys
        for v in (6, 7, 8, 9, 10):
            monkeypatch.delenv(f"KICAD{v}_SYMBOL_DIR", raising=False)

        apply_universal_kicad_env()

        for v in (6, 7, 8, 9, 10):
            assert os.environ.get(f"KICAD{v}_SYMBOL_DIR") == str(sym_dir)


def test_schematic_emission_target_version():
    """Verify that targeting a specific KiCad version emits the correct S-expression format date."""
    from openhac.schematic.layout import build_ir
    from openhac.schematic.emit_kicad import generate_schematic

    with tempfile.TemporaryDirectory() as tmp:
        # Target KiCad 7
        b7 = Board((50, 50), target_kicad=7)
        ir7 = build_ir([], [], b7)
        assert ir7.kicad_format_date == 20230121
        out_sch7 = Path(tmp) / "board_v7.kicad_sch"
        generate_schematic(str(out_sch7), b7)
        content7 = out_sch7.read_text(encoding="utf-8")
        assert "(version 20230121)" in content7

        # Target KiCad 8
        b8 = Board((50, 50), target_kicad=8)
        ir8 = build_ir([], [], b8)
        assert ir8.kicad_format_date == 20231120
        out_sch8 = Path(tmp) / "board_v8.kicad_sch"
        generate_schematic(str(out_sch8), b8)
        content8 = out_sch8.read_text(encoding="utf-8")
        assert "(version 20231120)" in content8

        # Target KiCad 10
        b10 = Board((50, 50), target_kicad=10)
        ir10 = build_ir([], [], b10)
        assert ir10.kicad_format_date == 20250101
        out_sch10 = Path(tmp) / "board_v10.kicad_sch"
        generate_schematic(str(out_sch10), b10)
        content10 = out_sch10.read_text(encoding="utf-8")
        assert "(version 20250101)" in content10


def test_pcb_io_sexp_plugin_resolves_on_kicad10():
    """KiCad 10 renamed PluginFind → FindPlugin; OpenHaC must resolve either."""
    import pcbnew

    from openhac.compiler.pcb_placement import _get_kicad_sexp_plugin

    plugin = _get_kicad_sexp_plugin(pcbnew)
    assert plugin is not None
    assert hasattr(plugin, "FootprintLoad")


def test_kicad_ipc_placement_backend_env(monkeypatch):
    from openhac.compiler import kicad_ipc_placement as ipc

    monkeypatch.setenv("OPENHAC_PLACEMENT_BACKEND", "ipc")
    assert ipc.placement_backend() == "ipc"
    monkeypatch.setenv("OPENHAC_PLACEMENT_BACKEND", "swig")
    assert ipc.placement_backend() == "swig"
    monkeypatch.delenv("OPENHAC_PLACEMENT_BACKEND", raising=False)
    assert ipc.placement_backend() == "auto"


def test_cea_farm_controller_builds():
    """Smoke: CEA example elaborates without importing pcbnew layout."""
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "examples" / "complex_cea_farm_controller.py"
    spec = importlib.util.spec_from_file_location("cea_farm", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    b = mod.board
    assert b.target_kicad_version.major == 10
    n = sum(len(m.components) for m in b._get_all_modules())
    assert n >= 80
    assert len(b._get_all_modules()) >= 40


def test_board_compile_target_kicad_kwarg():
    """Verify that Board.compile(target_kicad=...) overrides the default target version."""
    b = Board((50, 50))
    # Initially defaults to detected or 8
    b.compile(
        project_name="test_target_kwarg",
        export_schematic=False,
        auto_route=False,
        target_kicad=7,
        compile_profile="logic",
    )
    assert b.target_kicad_version.major == 7
    assert b.target_kicad_version.sch_format_date == 20230121


def test_cli_compile_target_kicad_flag(tmp_path):
    """Verify CLI --target-kicad flag emits the targeted KiCad format date."""
    import openhac.cli as cli

    script = tmp_path / "board_simple.py"
    script.write_text(
        """from openhac.core.board import Board
board = Board((40, 40))
""",
        encoding="utf-8",
    )

    out_v7 = tmp_path / "out_v7"
    cli.main([
        "compile",
        str(script),
        "--name", "board_simple",
        "-o", str(out_v7),
        "--target-kicad", "7",
        "--compile-profile", "preview",
        "--no-board-sidecars",
    ])
    sch7 = out_v7 / "board_simple.kicad_sch"
    assert sch7.is_file()
    assert "(version 20230121)" in sch7.read_text(encoding="utf-8")

    out_v10 = tmp_path / "out_v10"
    cli.main([
        "compile",
        str(script),
        "--name", "board_simple",
        "-o", str(out_v10),
        "--target-kicad", "10",
        "--compile-profile", "preview",
        "--no-board-sidecars",
    ])
    sch10 = out_v10 / "board_simple.kicad_sch"
    assert sch10.is_file()
    assert "(version 20250101)" in sch10.read_text(encoding="utf-8")

