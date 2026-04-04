"""Tests for openhac.core.board — Board constraints, validation, compile pipeline."""

from unittest.mock import patch, MagicMock

import pytest
from skidl import Net

from openhac.core.base import (
    Module,
    Component,
    Interface,
    UnconnectedInterfaceError,
)
from openhac.core.board import Board


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_module(name, dm, *, with_interface=True):
    """Create a Module with a single component and an optional interface."""
    mod = Module(name)
    with patch.object(Component, "db", dm):
        comp = Component("R_10k_0805")
        mod.add(comp)
    if with_interface:
        n1, n2 = Net(f"{name}_VCC"), Net(f"{name}_GND")
        comp["1"] += n1
        comp["2"] += n2
        mod.declare_interface("power", n1, n2)
    return mod


def _seed_db(dm):
    dm.insert_component({
        "generic_name": "R_10k_0805",
        "kicad_symbol": "Device:R",
        "kicad_footprint": "Resistor_SMD:R_0805_2012Metric",
        "manufacturer": "", "mpn": "X", "description": "",
    })


# ---------------------------------------------------------------------------
# Board basics
# ---------------------------------------------------------------------------


class TestBoardCreation:

    def test_defaults(self):
        board = Board(size_mm=(60, 40))
        assert board.size_mm == (60, 40)
        assert board.layers == 2
        assert board.modules == []
        assert board.constraints == []

    def test_custom_layers(self):
        board = Board(size_mm=(100, 80), layers=4)
        assert board.layers == 4


# ---------------------------------------------------------------------------
# Module management
# ---------------------------------------------------------------------------


class TestBoardModules:

    def test_add_module(self, tmp_db):
        _, dm = tmp_db
        _seed_db(dm)
        board = Board(size_mm=(60, 40))
        mod = _make_module("A", dm)
        board.add_module(mod)
        assert len(board.modules) == 1

    def test_connect_interfaces(self, tmp_db):
        _, dm = tmp_db
        _seed_db(dm)
        board = Board(size_mm=(60, 40))
        mod_a = _make_module("A", dm)
        mod_b = _make_module("B", dm)
        board.add_module(mod_a)
        board.add_module(mod_b)
        # Should not raise
        board.connect(
            mod_a.expose_interface("power"),
            mod_b.expose_interface("power"),
        )


# ---------------------------------------------------------------------------
# Constraints
# ---------------------------------------------------------------------------


class TestBoardConstraints:

    def test_constrain_distance_min(self, tmp_db):
        _, dm = tmp_db
        _seed_db(dm)
        board = Board(size_mm=(60, 40))
        a = _make_module("A", dm)
        b = _make_module("B", dm)
        board.add_module(a)
        board.add_module(b)
        board.constrain_distance_min(a, b, 10)
        assert len(board.constraints) == 1
        assert board.constraints[0]["type"] == "distance_min"

    def test_constrain_distance_max(self, tmp_db):
        _, dm = tmp_db
        _seed_db(dm)
        board = Board(size_mm=(60, 40))
        a = _make_module("A", dm)
        b = _make_module("B", dm)
        board.add_module(a)
        board.add_module(b)
        board.constrain_distance_max(a, b, 20)
        assert board.constraints[0]["type"] == "distance_max"

    def test_constrain_edge(self, tmp_db):
        _, dm = tmp_db
        _seed_db(dm)
        board = Board(size_mm=(60, 40))
        a = _make_module("A", dm)
        board.add_module(a)
        board.constrain_edge(a, "TOP")
        assert board.constraints[0]["type"] == "edge"


# ---------------------------------------------------------------------------
# Interface validation
# ---------------------------------------------------------------------------


class TestInterfaceValidation:

    def test_validate_passes_when_connected(self, tmp_db):
        _, dm = tmp_db
        _seed_db(dm)
        board = Board(size_mm=(60, 40))
        mod_a = _make_module("A", dm)
        mod_b = _make_module("B", dm)
        board.add_module(mod_a)
        board.add_module(mod_b)
        board.connect(
            mod_a.expose_interface("power"),
            mod_b.expose_interface("power"),
        )
        # Should not raise
        board._validate_interfaces()

    def test_validate_raises_when_unconnected(self, tmp_db):
        _, dm = tmp_db
        _seed_db(dm)
        board = Board(size_mm=(60, 40))
        # Module with interface that has nets with <2 pins
        mod = Module("lonely")
        n1 = Net("LONELY_NET")
        # Only 1 pin connected — validation should fail
        mod.declare_interface("data", n1)
        board.add_module(mod)
        with pytest.raises(UnconnectedInterfaceError):
            board._validate_interfaces()
