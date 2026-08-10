from __future__ import annotations

import builtins
import os

from openhac.core.circuit import default_circuit as native_default_circuit


def _legacy_skidl_enabled() -> bool:
    """Opt-in for SKiDL ``builtins.default_circuit`` (schematic / migration tooling)."""
    return os.environ.get("OPENHAC_LEGACY_SKIDL", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def get_default_circuit():
    """Return the current default circuit (native OpenHaC Circuit).

    Native :mod:`openhac.core.circuit` is the source of truth. Legacy SKiDL's
    ``builtins.default_circuit`` is used only when ``OPENHAC_LEGACY_SKIDL=1``.
    """
    if _legacy_skidl_enabled() and hasattr(builtins, "default_circuit"):
        return builtins.default_circuit
    return native_default_circuit


def get_circuit():
    """Alias for :func:`get_default_circuit` — single public entry point (SW-005)."""
    return get_default_circuit()
