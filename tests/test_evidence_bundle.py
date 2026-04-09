from __future__ import annotations

import json
from pathlib import Path

from openhac.compiler.evidence_bundle import write_attestation_json, write_evidence_markdown
from openhac.core.board import Board


def test_write_evidence_markdown(tmp_path: Path) -> None:
    b = Board((10, 10), board_class="digital_2layer")
    p = write_evidence_markdown(tmp_path, "p", b)
    assert p.is_file()
    assert "OpenHaC evidence bundle" in p.read_text(encoding="utf-8")


def test_attestation_is_optional(tmp_path: Path, monkeypatch) -> None:
    b = Board((10, 10))
    monkeypatch.delenv("OPENHAC_ATTEST_SIGNER", raising=False)
    assert write_attestation_json(tmp_path, "p", b) is None
    monkeypatch.setenv("OPENHAC_ATTEST_SIGNER", "test-signer")
    out = write_attestation_json(tmp_path, "p", b)
    assert out is not None and out.is_file()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["schema"] == "openhac.attestation.v1"
    assert data["signer"] == "test-signer"

