"""STR-002 stretch: deterministic manifest timestamp."""

from __future__ import annotations

import json

from openhac.compiler.compile_manifest import write_compile_manifest
from openhac.core.board import Board


def test_manifest_is_deterministic_when_env_enabled(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENHAC_DETERMINISTIC_MANIFEST", "1")

    project = "detmf"
    (tmp_path / f"{project}.net").write_text("(netlist)\n", encoding="utf-8")
    board = Board(size_mm=(10, 10))

    write_compile_manifest(project, board, generate_bom=False, export_schematic=False, output_dir=str(tmp_path))
    t1 = (tmp_path / f"{project}.openhac-manifest.json").read_text(encoding="utf-8")
    write_compile_manifest(project, board, generate_bom=False, export_schematic=False, output_dir=str(tmp_path))
    t2 = (tmp_path / f"{project}.openhac-manifest.json").read_text(encoding="utf-8")
    assert t1 == t2

    data = json.loads(t1)
    assert data.get("generated_utc") == "1980-01-01T00:00:00+00:00"
    assert data.get("build_environment") == {"deterministic": True}


def test_manifest_is_deterministic_with_umbrella_env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENHAC_DETERMINISTIC", "1")

    project = "detmf2"
    (tmp_path / f"{project}.net").write_text("(netlist)\n", encoding="utf-8")
    board = Board(size_mm=(10, 10))

    write_compile_manifest(project, board, generate_bom=False, export_schematic=False, output_dir=str(tmp_path))
    t1 = (tmp_path / f"{project}.openhac-manifest.json").read_text(encoding="utf-8")
    write_compile_manifest(project, board, generate_bom=False, export_schematic=False, output_dir=str(tmp_path))
    t2 = (tmp_path / f"{project}.openhac-manifest.json").read_text(encoding="utf-8")
    assert t1 == t2

    data = json.loads(t1)
    assert data.get("generated_utc") == "1980-01-01T00:00:00+00:00"
    assert data.get("build_environment") == {"deterministic": True}
