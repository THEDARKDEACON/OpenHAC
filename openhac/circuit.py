from __future__ import annotations

import builtins
from openhac.core.circuit import default_circuit as native_default_circuit


def get_default_circuit():
    """Return the current default circuit (Native OpenHaC Circuit)."""
    # Prefer builtins.default_circuit if it exists (legacy compatibility)
    if hasattr(builtins, "default_circuit"):
        return builtins.default_circuit
    
    # Fallback to native default circuit
    return native_default_circuit


def get_circuit():
    """Alias for :func:`get_default_circuit` — single public entry point (SW-005)."""
    return get_default_circuit()
