from __future__ import annotations

import json
import os
import warnings

import pytest

from openhac.database.db_manager import DatabaseManager
from openhac.core.base import Component, PartDatabaseWriteError


def test_parametric_search_db_write_failure_warns_non_strict(monkeypatch, tmp_path):
    db = DatabaseManager(db_path=str(tmp_path / "t.db"))

    monkeypatch.delenv("OPENHAC_COMPILE_GOAL", raising=False)
    monkeypatch.delenv("OPENHAC_STRICT_DB_WRITES", raising=False)

    monkeypatch.setattr(
        "openhac.database.api_fallback.fetch_and_map_part",
        lambda _q: {"generic_name": "X", "category": "resistor"},
    )

    def boom(_data, ignore_duplicate=False):  # noqa: ARG001
        raise RuntimeError("nope")

    monkeypatch.setattr(db, "insert_component", boom)

    with warnings.catch_warnings(record=True) as w:
        part, fallback = db.parametric_search(category="resistor", value="10k", package="0603")
        assert part is not None
        assert fallback is True
        assert any("JIT DB insert failed" in str(x.message) for x in w)


def test_parametric_search_db_write_failure_raises_in_strict(monkeypatch, tmp_path):
    db = DatabaseManager(db_path=str(tmp_path / "t.db"))
    monkeypatch.setenv("OPENHAC_COMPILE_GOAL", "fabrication")

    monkeypatch.setattr(
        "openhac.database.api_fallback.fetch_and_map_part",
        lambda _q: {"generic_name": "X", "category": "resistor"},
    )

    def boom(_data, ignore_duplicate=False):  # noqa: ARG001
        raise RuntimeError("nope")

    monkeypatch.setattr(db, "insert_component", boom)

    with pytest.raises(DatabaseManager.DatabaseWriteError):
        db.parametric_search(category="resistor", value="10k", package="0603")


def test_live_lookup_db_write_failure_warns_non_strict(monkeypatch, tmp_path):
    # Ensure Component class uses a DB we can control
    Component.db = DatabaseManager(db_path=str(tmp_path / "t.db"))
    monkeypatch.delenv("OPENHAC_COMPILE_GOAL", raising=False)
    monkeypatch.delenv("OPENHAC_STRICT_DB_WRITES", raising=False)

    # Fake HTTP response for urlopen
    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

        def read(self):
            payload = {
                "components": [
                    {"lcsc": "123", "mfr": "MPN", "package": "SOT-23", "description": "d"}
                ]
            }
            return json.dumps(payload).encode("utf-8")

    monkeypatch.setattr("openhac.core.base.urllib.request.urlopen", lambda *_a, **_k: _Resp())

    def boom(_data, ignore_duplicate=False):  # noqa: ARG001
        raise RuntimeError("nope")

    monkeypatch.setattr(Component.db, "insert_component", boom)

    with warnings.catch_warnings(record=True) as w:
        comp = Component._live_lookup("ANYTHING")
        assert comp is not None
        # warning for missing local db + warning for DB insert failure
        assert any("Run sync_catalog()" in str(x.message) for x in w)
        assert any("Could not store JIT-resolved component" in str(x.message) for x in w)


def test_live_lookup_db_write_failure_raises_in_strict(monkeypatch, tmp_path):
    Component.db = DatabaseManager(db_path=str(tmp_path / "t.db"))
    monkeypatch.setenv("OPENHAC_COMPILE_GOAL", "fabrication")

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

        def read(self):
            payload = {"components": [{"lcsc": "123", "mfr": "MPN"}]}
            return json.dumps(payload).encode("utf-8")

    monkeypatch.setattr("openhac.core.base.urllib.request.urlopen", lambda *_a, **_k: _Resp())

    def boom(_data, ignore_duplicate=False):  # noqa: ARG001
        raise RuntimeError("nope")

    monkeypatch.setattr(Component.db, "insert_component", boom)

    with pytest.raises(PartDatabaseWriteError):
        Component._live_lookup("ANYTHING")

