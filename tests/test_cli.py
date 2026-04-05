"""Tests for openhac.cli — board discovery and project naming."""

import types

from openhac.cli import _default_project_name, _find_board_instance
from openhac.core.board import Board


def test_find_board_prefers_name_board():
    m = types.ModuleType("t")
    b = Board(size_mm=(10, 10))
    m.board = b
    m.other = Board(size_mm=(5, 5))
    assert _find_board_instance(m) is b


def test_find_board_falls_back_to_single_export():
    m = types.ModuleType("t")
    b = Board(size_mm=(8, 8))
    m.my_design = b
    assert _find_board_instance(m) is b


def test_find_board_none_when_missing():
    m = types.ModuleType("t")
    m.x = 1
    assert _find_board_instance(m) is None


def test_default_project_name():
    assert _default_project_name("/foo/bar/my_board.py") == "my_board"
