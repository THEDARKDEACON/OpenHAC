"""Reference designator prefix logic and MCU pin-name alias helpers.

Extracted from ``base.py`` so ``Component`` and tests can import without
pulling the entire module tree.
"""

from __future__ import annotations

import re


def component_pin_access_aliases(key: object) -> list[str]:
    """MCU pin-name shorthands (e.g. ``PA12_USB_DP`` → ``PA12``).

    Board code should use the same pin names as the KiCad symbol where possible;
    this helper only covers stable, non-ambiguous suffix stripping for STM32-style
    labels.
    """
    ks = str(key).strip()
    if not ks:
        return []
    alts: list[str] = []
    for rx in (
        r"^(P[A-Z]\d+)_[A-Z0-9][A-Z0-9_]*$",  # PA12_USB_DP, PB6_I2C1_SCL
        r"^(PH\d+)_[A-Z0-9][A-Z0-9_]*$",  # PH0_OSC_IN
        r"^(PC\d+)_[A-Z0-9][A-Z0-9_]*$",  # PC14_OSC32_IN
    ):
        m = re.match(rx, ks)
        if m:
            alts.append(m.group(1))
            break
    seen: set[str] = {ks}
    out: list[str] = []
    for a in alts:
        if a not in seen:
            seen.add(a)
            out.append(a)
    return out


# Legacy alias — base.py and external code may reference the underscore-prefixed name.
_component_pin_access_aliases = component_pin_access_aliases


#: Map from component category substrings to IEC 60617 reference designator prefixes.
CATEGORY_REFDES_MAP: dict[str, str] = {
    "resistor": "R",
    "capacitor": "C",
    "inductor": "L",
    "led": "D",
    "diode": "D",
    "transistor": "Q",
    "mosfet": "Q",
    "ic": "U",
    "mcu": "U",
    "microcontroller": "U",
    "connector": "J",
    "header": "J",
    "crystal": "X",
    "switch": "S",
    "button": "S",
    "relay": "K",
    "fuse": "F",
    "transformer": "T",
}

#: Generic-name prefixes that map to a known refdes letter.
_GENERIC_NAME_PREFIXES: tuple[tuple[str, str], ...] = (
    ("MCU_", "U"),
    ("IMU_", "U"),
    ("BARO_", "U"),
    ("MAG_", "U"),
    ("FLASH_", "U"),
    ("LDO_", "U"),
    ("BUCK_", "U"),
    ("ESD_", "U"),
    ("CONN_", "J"),
    ("USB_", "J"),
)


def get_refdes_prefix(
    category: str | None,
    *,
    generic_name: str | None = None,
    mpn: str | None = None,
) -> str:
    """Get reference designator prefix based on component category."""
    gn_u = str(generic_name or "").strip().upper()
    mpn_u = str(mpn or "").strip().upper()
    if gn_u == "CAN_TJA1051" or "TJA1051" in mpn_u:
        return "U"
    if gn_u.startswith("XTAL_"):
        return "X"
    for prefix, rfx in _GENERIC_NAME_PREFIXES:
        if gn_u.startswith(prefix):
            return rfx
    if gn_u.startswith("LED_"):
        return "D"
    if gn_u.startswith("SW_"):
        return "S"

    if not category:
        return "U"  # Default to IC prefix
    cat_lower = category.lower()
    # JLC / catalog motion-sensor categories (substring-safe before generic map).
    if any(
        m in cat_lower
        for m in ("accelerometer", "gyroscope", "barometer", "magnetometer")
    ):
        return "U"
    for key, prefix in CATEGORY_REFDES_MAP.items():
        if key in cat_lower:
            return prefix
    return "U"  # Default to IC prefix
