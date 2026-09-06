"""First-class power tree (PWR-010). No converter-efficiency claim."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PowerRail:
    name: str
    voltage_v: float
    max_amp: float | None = None


class PowerTree:
    """Named rails with optional current caps. Not a lossy converter model."""

    def __init__(self, board) -> None:
        self._board = board
        self.rails: dict[str, PowerRail] = {}

    def declare_rail(
        self,
        name: str,
        voltage_v: float,
        max_amp: float | None = None,
    ) -> PowerRail:
        nm = str(name or "").strip()
        if not nm:
            raise ValueError("declare_rail requires a non-empty rail name")
        rail = PowerRail(name=nm, voltage_v=float(voltage_v), max_amp=None if max_amp is None else float(max_amp))
        self.rails[nm] = rail
        board = self._board
        dsv = getattr(board, "declared_supply_voltages_v", None)
        if not isinstance(dsv, dict):
            dsv = {}
            board.declared_supply_voltages_v = dsv
        dsv[nm] = rail.voltage_v
        dsv[nm.lower()] = rail.voltage_v
        if bool(getattr(board, "spice_signoff", False)):
            try:
                board.declare_spice_rail(nm, rail.voltage_v)
            except Exception:
                pass
        return rail


def sync_spice_rails_from_power_tree(board) -> None:
    """Optional PWR-010: declared rails feed ``declare_spice_rail`` under spice_signoff."""
    if not bool(getattr(board, "spice_signoff", False)):
        return
    tree = getattr(board, "_power_tree", None)
    if tree is None:
        return
    existing = getattr(board, "_spice_rails", None) or {}
    for name, rail in (tree.rails or {}).items():
        if name not in existing:
            try:
                board.declare_spice_rail(name, rail.voltage_v)
            except Exception:
                pass
