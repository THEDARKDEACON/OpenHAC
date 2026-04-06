"""MFG-005: release zip of compile artifacts."""

from __future__ import annotations

import zipfile
from pathlib import Path

from openhac.compiler.release_bundle import zip_project_outputs


def test_zip_project_outputs_selects_known_suffixes(tmp_path):
    base = tmp_path
    (base / "myprj.net").write_text("x", encoding="utf-8")
    (base / "myprj.csv").write_text("x", encoding="utf-8")
    (base / "myprj.openhac-manifest.json").write_text("{}", encoding="utf-8")
    (base / "myprj.openhac-manifest.json.sha256").write_text("ab" * 32 + "\n", encoding="utf-8")
    (base / "myprj.openhac-netclass-hint.md").write_text("# nc", encoding="utf-8")
    (base / "myprj.openhac-diff-pair-constraints.json").write_text("{}", encoding="utf-8")
    (base / "myprj.openhac-no-autoroute-constraints.json").write_text("{}", encoding="utf-8")
    (base / "myprj.openhac-pcb-auxiliary-constraints.json").write_text("{}", encoding="utf-8")
    (base / "myprj.openhac-length-match-hint.md").write_text("# m", encoding="utf-8")
    (base / "myprj.openhac-length-match-constraints.json").write_text("{}", encoding="utf-8")
    (base / "myprj.openhac-mixed-signal-hint.md").write_text("# ms", encoding="utf-8")
    (base / "myprj.openhac-mixed-signal-constraints.json").write_text("{}", encoding="utf-8")
    (base / "myprj.openhac-pcb-routing-handoff.json").write_text("{}", encoding="utf-8")
    (base / "myprj.openhac-bom-alternates.json").write_text("{}", encoding="utf-8")
    (base / "myprj.openhac-bom-expand-hint.md").write_text("# be", encoding="utf-8")
    (base / "myprj.openhac-spice-model-hint.md").write_text("# sm", encoding="utf-8")
    (base / "myprj.openhac-autoroute-policy.md").write_text("# ar", encoding="utf-8")
    (base / "myprj.openhac-si-stackup-reminder.md").write_text("# si", encoding="utf-8")
    (base / "myprj.kicad_pcb").write_text("(", encoding="utf-8")
    (base / "other.txt").write_text("skip", encoding="utf-8")
    (base / "notmyprj.net").write_text("skip", encoding="utf-8")

    zout = base / "out.zip"
    zip_project_outputs(base, "myprj", zout)

    with zipfile.ZipFile(zout, "r") as zf:
        names = set(zf.namelist())
    assert names == {
        "myprj.net",
        "myprj.csv",
        "myprj.openhac-manifest.json",
        "myprj.openhac-manifest.json.sha256",
        "myprj.openhac-netclass-hint.md",
        "myprj.openhac-diff-pair-constraints.json",
        "myprj.openhac-no-autoroute-constraints.json",
        "myprj.openhac-pcb-auxiliary-constraints.json",
        "myprj.openhac-length-match-hint.md",
        "myprj.openhac-length-match-constraints.json",
        "myprj.openhac-mixed-signal-hint.md",
        "myprj.openhac-mixed-signal-constraints.json",
        "myprj.openhac-pcb-routing-handoff.json",
        "myprj.openhac-bom-alternates.json",
        "myprj.openhac-bom-expand-hint.md",
        "myprj.openhac-spice-model-hint.md",
        "myprj.openhac-autoroute-policy.md",
        "myprj.openhac-si-stackup-reminder.md",
        "myprj.kicad_pcb",
    }
