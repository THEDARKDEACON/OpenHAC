"""Compile profiles — named bundles of strictness toggles.

Instead of memorizing 15+ individual boolean flags, users pick a profile that
matches their intent:

    Board(profile="handoff")   # reviewable KiCad outputs, implicit pins OK
    Board(profile="production")  # strict symbols + JIT, no implicit pins
    Board(profile="fabrication") # all gates on, manufacturing-ready

Individual overrides still work::

    Board(profile="fabrication", strict_footprint_pin_pad_match=False)

CLI mapping:
    --compile-goal handoff      → profile="handoff"
    --compile-goal fabrication  → profile="fabrication"
    --production / --strict     → profile="production"
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CompileProfile:
    """Bundles all strictness toggles into a named preset."""

    name: str

    # KiCad / JIT
    strict_kicad: bool = False
    strict_jit_lookups: bool = False

    # Passive component gates
    require_passive_voltage_ratings: bool = False
    require_passive_power_ratings: bool = False
    require_inductor_voltage_ratings: bool = False
    require_resistor_voltage_ratings: bool = False
    strict_passive_catalog_fields: bool = False
    strict_passive_attributes_json: bool = False

    # Footprint
    strict_footprint_pin_pad_match: bool = False

    # Implicit pins
    allow_implicit_pins: bool = True


#: Built-in compile profiles ordered from most permissive to most strict.
PROFILES: dict[str, CompileProfile] = {
    "dev": CompileProfile(
        name="dev",
        allow_implicit_pins=True,
    ),
    "handoff": CompileProfile(
        name="handoff",
        strict_kicad=False,
        strict_jit_lookups=False,
        allow_implicit_pins=True,
    ),
    "production": CompileProfile(
        name="production",
        strict_kicad=True,
        strict_jit_lookups=True,
        require_passive_voltage_ratings=True,
        strict_passive_catalog_fields=True,
        strict_passive_attributes_json=True,
        allow_implicit_pins=False,
    ),
    "fabrication": CompileProfile(
        name="fabrication",
        strict_kicad=True,
        strict_jit_lookups=True,
        require_passive_voltage_ratings=True,
        require_passive_power_ratings=True,
        require_inductor_voltage_ratings=True,
        require_resistor_voltage_ratings=True,
        strict_passive_catalog_fields=True,
        strict_passive_attributes_json=True,
        strict_footprint_pin_pad_match=True,
        allow_implicit_pins=False,
    ),
}


def resolve_profile(name: str | None) -> CompileProfile | None:
    """Resolve a profile name to a :class:`CompileProfile`, or ``None`` if *name* is falsy."""
    if not name:
        return None
    key = str(name).strip().lower()
    if key not in PROFILES:
        raise ValueError(
            f"Unknown compile profile {name!r}. Available: {', '.join(sorted(PROFILES))}"
        )
    return PROFILES[key]
