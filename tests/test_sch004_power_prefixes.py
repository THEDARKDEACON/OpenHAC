"""SCH-004: optional Board.power_net_prefixes extends heuristic power-net detection."""

from __future__ import annotations

from openhac.compiler.rule_check import _net_requires_power_flag, _power_prefixes_for_board


def test_power_prefixes_include_board_extra():
    class B:
        power_net_prefixes = ("vdd", "1v8")
        _explicit_power_net_ids = set()

    pfx = _power_prefixes_for_board(B())
    assert "vdd" in pfx and "gnd" in pfx


def test_vdd_sense_matches_custom_prefix():
    class B:
        power_net_prefixes = ("vdd",)
        _explicit_power_net_ids = set()

    class N:
        name = "VDD_SENSE_LINE"

    assert _net_requires_power_flag(B(), N()) is True
