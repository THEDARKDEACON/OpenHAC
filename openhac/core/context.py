"""DesignContext management for scoped, hermetic hardware builds (Option A)."""

from __future__ import annotations

from openhac.core.circuit import (
    DesignContext,
    get_active_circuit,
    get_active_design_context,
)

__all__ = [
    "DesignContext",
    "get_active_circuit",
    "get_active_design_context",
]
