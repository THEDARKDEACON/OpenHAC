from __future__ import annotations


def test_cmd_compile_sets_skip_layout_and_db_path_and_verified_gate(tmp_path, monkeypatch):
    from argparse import Namespace
    import os

    from openhac import cli
    from openhac.core.board import Board

    design_py = tmp_path / "design.py"
    design_py.write_text(
        "from openhac.core.board import Board\n"
        "board = Board(size_mm=(10.0, 10.0))\n",
        encoding="utf-8",
    )

    prev_skip = os.environ.get("OPENHAC_SKIP_LAYOUT")
    prev_db = os.environ.get("OPENHAC_DB_PATH")
    prev_req = os.environ.get("OPENHAC_REQUIRE_VERIFIED_PARTS")
    prev_sym_dirs = os.environ.get("OPENHAC_KICAD_SYMBOL_DIRS")
    prev_sym = os.environ.get("KICAD8_SYMBOL_DIR")
    prev_fp = os.environ.get("KICAD8_FOOTPRINT_DIR")

    called = {"ok": False}

    def _fake_compile(self, **kwargs):
        assert kwargs.get("project_name") == "t"
        assert (os.environ.get("OPENHAC_SKIP_LAYOUT") or "") == "1"
        assert (os.environ.get("OPENHAC_DB_PATH") or "") == "X.db"
        assert (os.environ.get("OPENHAC_REQUIRE_VERIFIED_PARTS") or "") == "1"
        assert (os.environ.get("KICAD8_SYMBOL_DIR") or "") == "SYM"
        assert (os.environ.get("KICAD9_SYMBOL_DIR") or "") == "SYM"
        assert (os.environ.get("KICAD7_SYMBOL_DIR") or "") == "SYM"
        assert (os.environ.get("KICAD6_SYMBOL_DIR") or "") == "SYM"
        assert (os.environ.get("KICAD8_FOOTPRINT_DIR") or "") == "FP"
        assert (os.environ.get("KICAD9_FOOTPRINT_DIR") or "") == "FP"
        assert (os.environ.get("KICAD_FOOTPRINT_DIR") or "") == "FP"
        assert (os.environ.get("OPENHAC_KICAD_SYMBOL_DIRS") or "") == "/sym/a:/sym/b"
        called["ok"] = True

    monkeypatch.setattr(Board, "compile", _fake_compile, raising=True)

    args = Namespace(
        script=str(design_py),
        name="t",
        no_route=True,
        skip_layout=True,
        no_schematic=True,
        allow_risky_parts=False,
        kicad_erc=False,
        strict_kicad=False,
        strict_jit=False,
        production=False,
        require_verified_parts=True,
        strict=False,
        release_tag=None,
        build_profile=None,
        bom_profile=None,
        kicad_erc_json=False,
        zip_release=False,
        zip_release_path=None,
        output_dir=None,
        manifest_sha256_sidecar=False,
        deterministic=False,
        db_path="X.db",
        kicad_symbol_dirs="/sym/a:/sym/b",
        kicad_symbol_dir="SYM",
        kicad_footprint_dir="FP",
    )
    cli.cmd_compile(args)
    assert called["ok"] is True

    # Ensure env gets restored after run.
    assert os.environ.get("OPENHAC_SKIP_LAYOUT") == prev_skip
    assert os.environ.get("OPENHAC_DB_PATH") == prev_db
    assert os.environ.get("OPENHAC_REQUIRE_VERIFIED_PARTS") == prev_req
    assert os.environ.get("OPENHAC_KICAD_SYMBOL_DIRS") == prev_sym_dirs
    assert os.environ.get("KICAD8_SYMBOL_DIR") == prev_sym
    assert os.environ.get("KICAD8_FOOTPRINT_DIR") == prev_fp


def test_cmd_simulate_sets_db_path(tmp_path, monkeypatch):
    from argparse import Namespace
    import os

    from openhac import cli
    from openhac.core.board import Board

    design_py = tmp_path / "design.py"
    design_py.write_text(
        "from openhac.core.board import Board\n"
        "board = Board(size_mm=(10.0, 10.0))\n",
        encoding="utf-8",
    )

    prev_sym = os.environ.get("KICAD8_SYMBOL_DIR")
    prev_fp = os.environ.get("KICAD8_FOOTPRINT_DIR")
    prev_db = os.environ.get("OPENHAC_DB_PATH")

    called = {"ok": False}

    def _fake_sim(self, **kwargs):
        assert kwargs.get("project_name") == "s"
        assert (os.environ.get("OPENHAC_DB_PATH") or "") == "Y.db"
        assert (os.environ.get("KICAD8_SYMBOL_DIR") or "") == "SYM2"
        assert (os.environ.get("KICAD8_FOOTPRINT_DIR") or "") == "FP2"
        called["ok"] = True

    monkeypatch.setattr(Board, "simulate", _fake_sim, raising=True)

    args = Namespace(
        script=str(design_py),
        name="s",
        allow_risky_parts=False,
        output_dir=None,
        spice_lines=None,
        spice_preset=None,
        spice_analysis_json=None,
        deterministic=False,
        db_path="Y.db",
        kicad_symbol_dir="SYM2",
        kicad_footprint_dir="FP2",
    )
    cli.cmd_simulate(args)
    assert called["ok"] is True

    assert os.environ.get("KICAD8_SYMBOL_DIR") == prev_sym
    assert os.environ.get("KICAD8_FOOTPRINT_DIR") == prev_fp
    assert os.environ.get("OPENHAC_DB_PATH") == prev_db


def test_cmd_compile_spice_signoff_calls_simulate(tmp_path, monkeypatch):
    from argparse import Namespace
    import os

    from openhac import cli
    from openhac.core.board import Board

    design_py = tmp_path / "design.py"
    design_py.write_text(
        "from openhac.core.board import Board\n"
        "board = Board(size_mm=(10.0, 10.0))\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("OPENHAC_SPICE_SIGNOFF", raising=False)

    compiled = {"ok": False}
    simulated = {}

    def _fake_compile(self, **kwargs):
        compiled["ok"] = True

    def _fake_sim(self, **kwargs):
        simulated.update(kwargs)

    monkeypatch.setattr(Board, "compile", _fake_compile, raising=True)
    monkeypatch.setattr(Board, "simulate", _fake_sim, raising=True)

    args = Namespace(
        script=str(design_py),
        name="t",
        no_route=True,
        skip_layout=True,
        no_schematic=True,
        allow_risky_parts=False,
        kicad_erc=False,
        strict_kicad=False,
        strict_jit=False,
        production=False,
        require_verified_parts=False,
        strict=False,
        release_tag=None,
        build_profile=None,
        bom_profile=None,
        kicad_erc_json=False,
        zip_release=False,
        zip_release_path=None,
        output_dir=str(tmp_path / "out"),
        manifest_sha256_sidecar=False,
        deterministic=False,
        db_path=None,
        spice_signoff=True,
        run_ngspice=False,
        spice_vendor_dir=None,
        allow_behavioral_spice_models=False,
        require_vendor_models=False,
        ngspice_log=None,
    )
    cli.cmd_compile(args)
    assert compiled["ok"] is True
    assert simulated.get("spice_signoff") is True
    assert simulated.get("project_name") == "t"
    assert simulated.get("output_dir") == str(tmp_path / "out")
    assert os.environ.get("OPENHAC_SPICE_SIGNOFF") is None


def test_compile_help_lists_spice_signoff():
    import subprocess
    import sys

    r = subprocess.run(
        [sys.executable, "-m", "openhac", "compile", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    assert "--spice-signoff" in r.stdout
    assert "--run-ngspice" in r.stdout
    assert "--spice-island" in r.stdout

