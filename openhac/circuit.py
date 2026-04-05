"""Single access point for the active SKiDL default circuit."""

from __future__ import annotations

import builtins


def get_default_circuit():
    """Return the current SKiDL default circuit (same object as ``skidl`` uses)."""
    try:
        return builtins.default_circuit
    except AttributeError as e:
        raise RuntimeError(
            "SKiDL default circuit is not initialized. Import skidl (or openhac.core) before "
            "generating netlists or schematics."
        ) from e


def get_circuit():
    """Alias for :func:`get_default_circuit` — single public entry point (SW-005)."""
    return get_default_circuit()
