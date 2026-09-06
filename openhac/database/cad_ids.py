"""Identify stock KiCad lib ids vs EasyEDA / JLC2KiCAD generated CAD."""

from __future__ import annotations

_GENERATED_LIBS = ("easyeda_generated", "jlc2kicad_generated")


def is_generated_cad_id(value: str | None) -> bool:
    s = str(value or "")
    return any(lib in s for lib in _GENERATED_LIBS)


def is_stock_kicad_id(value: str | None) -> bool:
    s = str(value or "").strip()
    return ":" in s and not is_generated_cad_id(s)
