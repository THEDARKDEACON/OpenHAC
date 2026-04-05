"""SCH-001: alphanumeric pin ordering (A2 before A10)."""

from __future__ import annotations

from openhac.compiler.schematic_gen import _pin_sort_key


def _pin(ref: str, num: str):
    part = type("Part", (), {"ref": ref})()
    return type("Pin", (), {"part": part, "num": num})()


def test_pin_sort_natural_order_bga_style():
    pins = [_pin("U1", "A10"), _pin("U1", "A2"), _pin("U1", "B1")]
    ordered = sorted(pins, key=_pin_sort_key)
    assert [p.num for p in ordered] == ["A2", "A10", "B1"]


def test_pin_sort_numeric_still_numeric():
    pins = [_pin("R1", "10"), _pin("R1", "2")]
    ordered = sorted(pins, key=_pin_sort_key)
    assert [p.num for p in ordered] == ["2", "10"]
