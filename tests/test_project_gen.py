"""SCH-001: deterministic KiCad .kicad_pro generation."""

from __future__ import annotations

import json

from openhac.compiler.project_gen import generate_project_file


def test_generate_project_file_is_deterministic(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    p = tmp_path / "proj.kicad_pro"
    generate_project_file(str(p))
    t1 = p.read_text(encoding="utf-8")
    generate_project_file(str(p))
    t2 = p.read_text(encoding="utf-8")
    assert t1 == t2
    data = json.loads(t1)
    assert data.get("meta", {}).get("version") == 3
