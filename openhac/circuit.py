from __future__ import annotations

import builtins
import os

def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def _legacy_skidl_enabled() -> bool:
    """Opt-in for SKiDL ``builtins.default_circuit`` (schematic / migration tooling)."""
    return _env_truthy("OPENHAC_LEGACY_SKIDL")


def legacy_skidl_enabled() -> bool:
    """Public alias for :func:`_legacy_skidl_enabled` (FAB-004 / SPS-007)."""
    return _legacy_skidl_enabled()


def empty_native_circuit_is_error(*, signoff: bool = False) -> bool:
    """True when an empty native graph must not fall through to SKiDL (FAB-004)."""
    if signoff:
        return True
    if _env_truthy("OPENHAC_SPICE_SIGNOFF") or _env_truthy("OPENHAC_SCHEMATIC_SIGNOFF"):
        return True
    goal = (os.environ.get("OPENHAC_COMPILE_GOAL") or "").strip().lower()
    return goal in ("fabrication", "fab", "push_button_fab", "push-button-fab", "pushbuttonfab")


def get_default_circuit():
    """Return the current default circuit (native OpenHaC Circuit).

    Native :mod:`openhac.core.circuit` is the source of truth. Legacy SKiDL's
    ``builtins.default_circuit`` is used only when ``OPENHAC_LEGACY_SKIDL=1``.
    """
    if _legacy_skidl_enabled() and hasattr(builtins, "default_circuit"):
        return builtins.default_circuit
    from openhac.core import circuit as _core_circuit

    return _core_circuit.default_circuit


def get_circuit():
    """Alias for :func:`get_default_circuit` — single public entry point (SW-005)."""
    return get_default_circuit()
