"""LIB-004: optional strict KiCad symbol loading (no synthetic fallback)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from openhac.core.base import Component, KicadLibraryLoadError, Module
from openhac.core.board import Board


def test_strict_mode_raises_when_symbol_load_fails(tmp_db):
    _, dm = tmp_db
    dm.insert_component({
        "generic_name": "R_strict_x",
        "kicad_symbol": "Device:R",
        "kicad_footprint": "Resistor_SMD:R_0805_2012Metric",
        "manufacturer": "",
        "mpn": "X",
        "supplier_sku": "",
        "description": "",
    })
    with patch.object(Component, "db", dm):
        with patch("openhac.core.base.Part", side_effect=RuntimeError("no lib")):
            with patch.object(Component, "require_kicad_symbols", True):
                with pytest.raises(KicadLibraryLoadError, match="strict KiCad"):
                    Component("R_strict_x")


def test_strict_via_openhac_strict_kicad_env(tmp_db, monkeypatch):
    _, dm = tmp_db
    dm.insert_component({
        "generic_name": "R_strict_y",
        "kicad_symbol": "Device:R",
        "kicad_footprint": "Resistor_SMD:R_0805_2012Metric",
        "manufacturer": "",
        "mpn": "Y",
        "supplier_sku": "",
        "description": "",
    })
    monkeypatch.setenv("OPENHAC_STRICT_KICAD", "1")
    with patch.object(Component, "db", dm):
        with patch("openhac.core.base.Part", side_effect=RuntimeError("no lib")):
            with pytest.raises(KicadLibraryLoadError):
                Component("R_strict_y")


def test_board_strict_kicad_does_not_mutate_component_class():
    prev = Component.require_kicad_symbols
    _ = Board(size_mm=(10, 10), strict_kicad=True)
    assert Component.require_kicad_symbols is prev


def test_board_strict_kicad_via_add_part_and_host_board(tmp_db):
    _, dm = tmp_db
    dm.insert_component(
        {
            "generic_name": "R_strict_z",
            "kicad_symbol": "Device:R",
            "kicad_footprint": "Resistor_SMD:R_0805_2012Metric",
            "manufacturer": "",
            "mpn": "Z",
            "supplier_sku": "",
            "description": "",
        }
    )
    with patch.object(Component, "db", dm):
        with patch("openhac.core.base.Part", side_effect=RuntimeError("no lib")):
            board = Board(size_mm=(10, 10), strict_kicad=True)

            class M(Module):
                def __init__(self):
                    super().__init__("M")

            m = M()
            board.add_module(m)
            with pytest.raises(KicadLibraryLoadError, match="strict KiCad"):
                m.add_part("R_strict_z")
