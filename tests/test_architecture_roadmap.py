"""Tests for architecture-roadmap placement / schematic / timeout fixes."""

from __future__ import annotations

from pathlib import Path

import pytest

from openhac.compiler.cluster_affinity import (
    apply_cluster_affinity,
    apply_satellite_offsets_after_z3,
    discover_cluster_pairs,
    z3_modules,
)
from openhac.compiler.schematic_gen import _want_multi_sheet, generate_schematic
from openhac.core.board import Board
from openhac.core.module import Module


class _Ic(Module):
    def __init__(self, name="Esp32S3Module"):
        super().__init__(name)
        self.width = 20.0
        self.height = 15.0


class _Caps(Module):
    def __init__(self, name="EspLocalCaps"):
        super().__init__(name)
        self.width = 12.0
        self.height = 10.0


def test_discover_and_merge_cluster_pairs():
    b = Board((100, 100))
    ic = _Ic()
    caps = _Caps()
    b.add_module(ic)
    b.add_module(caps)
    pairs = discover_cluster_pairs(b)
    assert any(p[0] is ic and p[1] is caps for p in pairs)

    stats = apply_cluster_affinity(b)
    assert stats["merged"] >= 1
    assert caps._z3_skip is True
    assert caps in [m for m in b._get_all_modules()]
    assert caps not in z3_modules(b)
    assert ic in z3_modules(b)
    # Parent AABB grew to absorb satellite
    assert ic.width >= 20.0 + 2.0 + 12.0 - 0.01
    grown = ic.width
    apply_cluster_affinity(b)
    assert ic.width == grown


def test_explicit_cluster_with():
    b = Board((80, 80))
    a = _Ic("Core")
    c = _Caps("DecapIsland")
    c.cluster_with(a)
    b.add_module(a)
    b.add_module(c)
    apply_cluster_affinity(b)
    assert c._z3_skip
    a.placed_x, a.placed_y = 10, 20
    apply_satellite_offsets_after_z3(b)
    assert c.placed_x is not None
    assert c.placed_x > a.placed_x


def test_want_multi_sheet_env_policy(monkeypatch):
    monkeypatch.delenv("OPENHAC_SCHEMATIC_MULTI_SHEET", raising=False)
    monkeypatch.delenv("OPENHAC_SCHEMATIC_SINGLE_SHEET", raising=False)
    monkeypatch.setenv("OPENHAC_SCHEMATIC_MULTI_SHEET_MIN_PARTS", "25")
    parts = [object()] * 10
    assert _want_multi_sheet(parts, ["A", "B"]) is False
    parts = [object()] * 25
    assert _want_multi_sheet(parts, ["A"]) is True

    monkeypatch.setenv("OPENHAC_SCHEMATIC_SINGLE_SHEET", "1")
    assert _want_multi_sheet(parts, ["A"]) is False
    monkeypatch.delenv("OPENHAC_SCHEMATIC_SINGLE_SHEET", raising=False)
    monkeypatch.setenv("OPENHAC_SCHEMATIC_MULTI_SHEET", "1")
    assert _want_multi_sheet([object()], ["A"]) is True


def test_schematic_does_not_multisheet_on_module_alone(tmp_path, monkeypatch):
    """Two tagged modules with few parts stay flat unless MULTI_SHEET / MIN_PARTS trip."""
    from skidl import Part, Net

    monkeypatch.delenv("OPENHAC_SCHEMATIC_MULTI_SHEET", raising=False)
    monkeypatch.delenv("OPENHAC_SCHEMATIC_SINGLE_SHEET", raising=False)
    monkeypatch.setenv("OPENHAC_SCHEMATIC_MULTI_SHEET_MIN_PARTS", "25")
    monkeypatch.setenv("OPENHAC_SCHEMATIC_STUB_ONLY", "1")

    n = Net("N1")
    p1 = Part("Device", "R", value="10k", footprint="Resistor_SMD:R_0603_1608Metric")
    p2 = Part("Device", "R", value="10k", footprint="Resistor_SMD:R_0603_1608Metric")
    p1.fields["OpenHaC_Module"] = "MOD_A"
    p2.fields["OpenHaC_Module"] = "MOD_B"
    n += p1[1]
    n += p2[1]

    out = tmp_path / "flat.kicad_sch"
    generate_schematic(str(out), Board((10, 10)))
    assert out.is_file()
    assert not (tmp_path / "flat.MOD_A.kicad_sch").is_file()
    assert not (tmp_path / "flat.MOD_B.kicad_sch").is_file()


def test_sch_sheet_field_decouples_hierarchy(tmp_path, monkeypatch):
    from skidl import Part, Net

    monkeypatch.setenv("OPENHAC_SCHEMATIC_MULTI_SHEET", "1")
    monkeypatch.setenv("OPENHAC_SCHEMATIC_STUB_ONLY", "1")

    n = Net("N2")
    p1 = Part("Device", "R", value="1k", footprint="Resistor_SMD:R_0603_1608Metric")
    p2 = Part("Device", "R", value="1k", footprint="Resistor_SMD:R_0603_1608Metric")
    p1.fields["OpenHaC_Module"] = "Esp32S3Module"
    p2.fields["OpenHaC_Module"] = "EspLocalCaps"
    # Same schematic sheet despite different placement modules
    p1.fields["OpenHaC_SchSheet"] = "ESP_CORE"
    p2.fields["OpenHaC_SchSheet"] = "ESP_CORE"
    n += p1[1]
    n += p2[1]

    out = tmp_path / "grouped.kicad_sch"
    generate_schematic(str(out), Board((10, 10)))
    assert (tmp_path / "grouped.ESP_CORE.kicad_sch").is_file()
    assert not (tmp_path / "grouped.EspLocalCaps.kicad_sch").is_file()


def test_freerouting_default_timeout(monkeypatch):
    from openhac.compiler.autoroute_cli import _freerouting_subprocess_timeout

    monkeypatch.delenv("OPENHAC_FREEROUTING_TIMEOUT_S", raising=False)
    monkeypatch.delenv("OPENHAC_FREEROUTING_GUI", raising=False)
    assert _freerouting_subprocess_timeout() == 1800.0
    monkeypatch.setenv("OPENHAC_FREEROUTING_TIMEOUT_S", "unlimited")
    assert _freerouting_subprocess_timeout() is None


def test_autosize_prefers_module_aabb(monkeypatch):
    from openhac.compiler.autosize_board import maybe_autosize_board

    monkeypatch.delenv("OPENHAC_AUTO_BOARD_ALSO_FP_PACK", raising=False)
    b = Board(size_mm=None)
    assert b._size_mm_unspecified
    a = _Ic("A")
    a.width, a.height = 30, 20
    c = _Caps("C")
    c.width, c.height = 10, 10
    b.add_module(a)
    b.add_module(c)
    apply_cluster_affinity(b)
    assert maybe_autosize_board(b) is True
    w, h = b.size_mm
    assert w >= 40 and h >= 20
