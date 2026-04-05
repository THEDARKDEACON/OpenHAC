"""Unit tests for openhac.compiler.pcb_placement (no KiCad pcbnew required)."""

import pytest

from openhac.compiler.pcb_placement import (
    collect_skidl_part_positions,
    footprint_search_roots,
    kicad_mod_pad_numbers,
    parse_footprint_id,
    pin_pad_coverage_warnings,
)
from openhac.core.base import Component, Module
from openhac.core.board import Board


class TestParseFootprintId:

    def test_valid(self):
        assert parse_footprint_id("Resistor_SMD:R_0805_2012Metric") == (
            "Resistor_SMD",
            "R_0805_2012Metric",
        )

    def test_empty(self):
        assert parse_footprint_id("") is None
        assert parse_footprint_id(None) is None

    def test_no_colon(self):
        assert parse_footprint_id("R_0805") is None


class TestFootprintSearchRoots:

    def test_env_override(self, monkeypatch, tmp_path):
        fp_root = tmp_path / "fp"
        fp_root.mkdir()
        monkeypatch.setenv("KICAD8_FOOTPRINT_DIR", str(fp_root))
        roots = footprint_search_roots()
        assert str(fp_root.resolve()) in roots


class TestCollectSkidlPartPositions:

    def test_places_components_under_module(self, tmp_db, monkeypatch):
        _, dm = tmp_db
        dm.insert_component(
            {
                "generic_name": "R_10k_0805",
                "kicad_symbol": "Device:R",
                "kicad_footprint": "Resistor_SMD:R_0805_2012Metric",
                "manufacturer": "",
                "mpn": "X",
                "description": "",
            }
        )

        class M(Module):
            def __init__(self):
                super().__init__("M1")
                self.placed_x = 20
                self.placed_y = 30
                with monkeypatch.context() as m:
                    m.setattr(Component, "db", dm)
                    self.c = self.add(Component("R_10k_0805"))

        board = Board(size_mm=(100, 100))
        board.all_modules = [M()]
        pos = collect_skidl_part_positions(board)
        assert len(pos) == 1
        (x, y) = next(iter(pos.values()))
        assert x == 20.0 and y == 30.0


class TestKicadModPadNumbers:
    def test_quoted_and_numeric_pad_tokens(self):
        body = (
            '(footprint "X" '
            '(pad "1" smd roundrect (at 0 0) (size 1 1) (layers F.Cu)) '
            "(pad 2 smd rect (at 1 0) (size 1 1) (layers F.Cu)))"
        )
        assert kicad_mod_pad_numbers(body) == {"1", "2"}


class TestPinPadCoverageWarnings:
    def test_warns_when_pin_net_has_no_matching_pad(self, tmp_path, monkeypatch):
        import openhac.core  # noqa: F401
        from skidl import Net, Part

        root = tmp_path / "fp"
        pretty = root / "Resistor_Test.pretty"
        pretty.mkdir(parents=True)
        (pretty / "R2.kicad_mod").write_text(
            '(footprint "R2" '
            '(pad "1" smd roundrect (at 0 0) (size 1 1) (layers F.Cu F.Mask F.Paste)))',
            encoding="utf-8",
        )
        monkeypatch.setenv("KICAD8_FOOTPRINT_DIR", str(root))

        n = Net("N")
        r = Part("Device", "R", value="1k", ref="RX", footprint="Resistor_Test:R2")
        r[1] += n
        r[2] += n

        from openhac.circuit import get_default_circuit

        msgs = pin_pad_coverage_warnings(get_default_circuit())
        assert any("RX" in m and "2" in m and "pad" in m.lower() for m in msgs)
