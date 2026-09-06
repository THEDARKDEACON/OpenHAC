"""Board variants / DNP application (VAR-001). Does not clone pinouts."""

from __future__ import annotations

from openhac.core.dnp import disconnect_part_from_nets, mark_part_dnp


def _norm_variant(v: str | None) -> str:
    return str(v or "").strip()


def module_included_in_variant(mod, variant: str) -> bool:
    names = tuple(getattr(mod, "_variants", None) or ())
    if not names or not variant:
        return True
    return variant in names


def _dnp_names(obj) -> tuple[str, ...]:
    return tuple(getattr(obj, "_dnp_in_variants", None) or ())


def apply_board_variant(board) -> None:
    """Mark excluded / DNP parts: BOM keeps them, ERC/placement do not net them."""
    variant = _norm_variant(getattr(board, "variant", None))
    from openhac.core.base import Component
    from openhac.core.module import Module

    def walk(mod) -> None:
        exclude = bool(variant) and not module_included_in_variant(mod, variant)
        mod_dnp = bool(variant) and variant in _dnp_names(mod)
        for item in list(getattr(mod, "components", None) or []):
            if isinstance(item, Module):
                walk(item)
                continue
            if not isinstance(item, Component):
                continue
            want_dnp = exclude or mod_dnp or (bool(variant) and variant in _dnp_names(item))
            if not want_dnp:
                continue
            part = getattr(item, "part", None) or item
            mark_part_dnp(part)
            mark_part_dnp(item)
            disconnect_part_from_nets(part)

    for top in list(getattr(board, "modules", None) or []):
        if isinstance(top, Module):
            walk(top)
