"""CAT-004 / CAT-013: named pin tables vs warehouse numeric placeholders.

Two-terminal passives may use a generic 1/2 (or A/K) table. MOSFET rows in the
FET category may use D/G/S. MCU / regulator / IC / multi-pin connector rows
must not persist numeric-only pinouts (name == num for every pin).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

# KiCad lib ids that are placeholders, not a pin-name oracle (CAT-013).
GENERIC_KICAD_SYMBOL_IDS = frozenset(
    {
        "Device:IC",
        "MCU_Module:Generic_MCU",
        "Sensor_Motion:Generic_Accelerometer",
        "Sensor:Generic",
        "Device:Q",
    }
)

TWO_TERMINAL_CATEGORIES = frozenset(
    {
        "resistors",
        "resistor",
        "capacitors",
        "capacitor",
        "inductors",
        "inductor",
        "leds",
        "led",
        "diodes",
        "diode",
        "fuses",
        "fuse",
        "beads",
        "bead",
        "ferrite_beads",
        "ferrite",
    }
)

FET_CATEGORIES = frozenset({"mosfets", "mosfet", "fet", "transistor_fet"})

IC_LIKE_CATEGORIES = frozenset(
    {
        "microcontrollers",
        "microcontroller",
        "mcu",
        "voltage_regulators",
        "voltage_regulator",
        "regulators",
        "regulator",
        "ic",
        "ics",
        "connectors",
        "connector",
        "accelerometers",
        "switches",
        "bjts",
        "bjt",
        "transistors",
        "flash",
        "buck_converters",
        "module",
        "modules",
    }
)

_TWO_TERMINAL_NAME_PREFIXES = ("R_", "C_", "L_", "LED_", "DIODE_", "D_", "FUSE_", "BEAD_")


def parse_pinout(raw: Any) -> list[dict] | None:
    if raw is None:
        return None
    if isinstance(raw, list):
        return [p for p in raw if isinstance(p, dict)] or None
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return None
        try:
            data = json.loads(s)
        except (json.JSONDecodeError, TypeError):
            return None
        if isinstance(data, list):
            return [p for p in data if isinstance(p, dict)] or None
    return None


def _norm_cat(category: str | None) -> str:
    return str(category or "").strip().lower().replace(" ", "_")


def is_two_terminal_category(category: str | None, generic_name: str | None = None) -> bool:
    cat = _norm_cat(category)
    if cat in TWO_TERMINAL_CATEGORIES:
        return True
    gn = str(generic_name or "")
    return any(gn.startswith(p) for p in _TWO_TERMINAL_NAME_PREFIXES)


def is_fet_category(category: str | None) -> bool:
    return _norm_cat(category) in FET_CATEGORIES


def is_ic_like_category(category: str | None, generic_name: str | None = None) -> bool:
    cat = _norm_cat(category)
    if cat in IC_LIKE_CATEGORIES:
        return True
    gn = str(generic_name or "").upper()
    return gn.startswith("MCU_") or gn.startswith("LDO_") or gn.startswith("CONN_")


def pinout_is_numeric_only(pinout: Any) -> bool:
    pins = parse_pinout(pinout)
    if not pins:
        return False
    named_diff = 0
    for p in pins:
        num = str(p.get("num") or "").strip()
        name = str(p.get("name") or "").strip()
        if not num:
            continue
        if name and name != num and name not in ("~",):
            named_diff += 1
    return named_diff == 0


def pinout_is_named(pinout: Any, *, category: str | None = None, generic_name: str | None = None) -> bool:
    """True when the table is a real named pinout (CAT-001).

    Two-terminal passives: a 2-pin 1/2 (or A/K) table counts as named.
    ICs: every pin must have a name distinct from its number (except ``~``
    on 2-pin Device:R-style parts already classified as two-terminal).
    """
    pins = parse_pinout(pinout)
    if not pins:
        return False
    if is_two_terminal_category(category, generic_name):
        if len(pins) != 2:
            return False
        nums = {str(p.get("num") or "").strip() for p in pins}
        names = {str(p.get("name") or "").strip().upper() for p in pins}
        if nums <= {"1", "2"} or names <= {"A", "K", "1", "2", "~", ""}:
            return True
        return True
    if is_fet_category(category) and len(pins) == 3:
        names = {str(p.get("name") or "").strip().upper() for p in pins}
        if names == {"D", "G", "S"}:
            return True
    for p in pins:
        num = str(p.get("num") or "").strip()
        name = str(p.get("name") or "").strip()
        if not num:
            return False
        if not name or name == num:
            return False
    return True


def two_terminal_pinout(*, diode: bool = False) -> list[dict]:
    if diode:
        return [
            {"num": "1", "name": "K", "type": "passive"},
            {"num": "2", "name": "A", "type": "passive"},
        ]
    return [
        {"num": "1", "name": "1", "type": "passive"},
        {"num": "2", "name": "2", "type": "passive"},
    ]


def mosfet_dgs_pinout() -> list[dict]:
    return [
        {"num": "1", "name": "D", "type": "passive"},
        {"num": "2", "name": "G", "type": "input"},
        {"num": "3", "name": "S", "type": "passive"},
    ]


def pinout_for_sync_category(category: str) -> list[dict] | None:
    """Return a pin table to write during catalog sync, or None to leave empty."""
    cat = _norm_cat(category)
    if cat in ("diodes", "diode"):
        return two_terminal_pinout(diode=True)
    if cat in TWO_TERMINAL_CATEGORIES:
        return two_terminal_pinout(diode=False)
    if cat in FET_CATEGORIES:
        return mosfet_dgs_pinout()
    return None


def should_store_vendor_pinout(
    pinout: Any,
    *,
    category: str | None = None,
    generic_name: str | None = None,
) -> bool:
    """CAT-004: refuse numeric-only IC pinouts (hard skip, do not persist)."""
    pins = parse_pinout(pinout)
    if not pins:
        return False
    if is_two_terminal_category(category, generic_name):
        return True
    if is_fet_category(category) and not pinout_is_numeric_only(pins):
        return True
    if pinout_is_numeric_only(pins):
        return False
    return True


def kicad_symbol_is_pin_name_oracle(kicad_symbol: str | None) -> bool:
    """CAT-013: real ``Library:Name`` ids may fill names; placeholders must not."""
    ks = str(kicad_symbol or "").strip()
    if not ks or ":" not in ks:
        return False
    if ks in GENERIC_KICAD_SYMBOL_IDS:
        return False
    lib, _, name = ks.partition(":")
    if not lib or not name:
        return False
    if name.upper() in {"GENERIC_MCU", "GENERIC", "IC", "Q"}:
        return False
    return True


def pinout_hash(pinout: Any) -> str:
    """Canonical sha256 of a pin table (LOCK-001 / PIN-001). Empty table → empty string."""
    pins = parse_pinout(pinout) or []
    canon = sorted(
        (
            {
                "num": str(p.get("num") or "").strip(),
                "name": str(p.get("name") or "").strip(),
                "type": str(p.get("type") or "").strip(),
            }
            for p in pins
        ),
        key=lambda d: (d["num"], d["name"], d["type"]),
    )
    if not canon:
        return ""
    blob = json.dumps(canon, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()
