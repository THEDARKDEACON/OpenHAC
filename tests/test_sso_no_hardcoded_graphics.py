"""SSO-042: compiler must not contain part-type schematic graphics."""

from __future__ import annotations

from pathlib import Path

_FORBIDDEN = (
    "_resistor_graphic",
    "_capacitor_graphic",
    "_led_graphic",
    "_detect_symbol_type",
    "_transistor_graphic",
    "_diode_graphic",
    "_inductor_graphic",
)

_ROOT = Path(__file__).resolve().parents[1] / "openhac"


def test_sso042_no_hardcoded_part_graphics() -> None:
    hits: list[str] = []
    for path in _ROOT.rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="replace")
        for name in _FORBIDDEN:
            if name in text:
                hits.append(f"{path.relative_to(_ROOT.parent)}:{name}")
    assert hits == [], "SSO-042: hardcoded part graphics returned:\n" + "\n".join(hits)
