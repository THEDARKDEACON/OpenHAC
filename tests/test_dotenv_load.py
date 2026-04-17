"""Tests for repo-root .env loading."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from openhac.core import dotenv_load


def test_load_repo_dotenv_sets_from_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "openhac").mkdir()
    (root / "openhac" / "core").mkdir()
    env_file = root / ".env"
    env_file.write_text("OPENHAC_DOTENV_TEST_XYZ=from_env\n", encoding="utf-8")

    monkeypatch.setattr(dotenv_load, "_repo_root", lambda: root)
    monkeypatch.delenv("OPENHAC_DOTENV_TEST_XYZ", raising=False)

    dotenv_load.load_repo_dotenv(quiet=True)
    assert os.environ.get("OPENHAC_DOTENV_TEST_XYZ") == "from_env"
