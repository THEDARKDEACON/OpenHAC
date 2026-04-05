"""Example ERC hooks for :meth:`openhac.core.board.Board.register_erc_hook` (SCH-005).

These are **illustrative** checks only; tune or replace for your design rules.
"""

from __future__ import annotations

_RAIL_NAME_HINTS = ("vcc", "3v3", "5v", "1v8", "2v5", "vdd", "vin", "vbat", "vbus")


def _pins_on_net(net):
    try:
        return list(net.get_pins())
    except Exception:
        try:
            return list(getattr(net, "pins", ()) or ())
        except Exception:
            return []


def _net_name_lower(net) -> str:
    return str(getattr(net, "name", "") or "").lower()


def _looks_like_supply_net(net) -> bool:
    n = _net_name_lower(net)
    return any(n.startswith(p) for p in _RAIL_NAME_HINTS)


def _part_is_resistor_symbol(part) -> bool:
    """KiCad ``Device:R`` is a resistor even when SKiDL uses ref_prefix ``U`` (synthetic symbol)."""
    if str(getattr(part, "ref_prefix", "") or "").upper() == "R":
        return True
    return (getattr(part, "name", None) or "").strip().upper() == "R"


def net_has_resistor_pullup_to_rail(net) -> bool:
    """True if some resistor part connects *net* to a net whose name looks like a supply rail."""
    for pin in _pins_on_net(net):
        part = getattr(pin, "part", None)
        if part is None:
            continue
        if not _part_is_resistor_symbol(part):
            continue
        try:
            part_pins = list(part.pins)
        except Exception:
            continue
        for pp in part_pins:
            if pp is pin:
                continue
            other = getattr(pp, "net", None)
            if other is None or other is net:
                continue
            if _looks_like_supply_net(other):
                return True
    return False


def one_wire_pullup_erc_hook(dq_net):
    """Build ``fn(board)`` that requires a pull-up resistor from *dq_net* to a supply-named net (1-Wire, SCH-005)."""

    def _hook(board):
        _ = board
        msgs = []
        if not net_has_resistor_pullup_to_rail(dq_net):
            msgs.append(
                f"1-Wire DQ net {getattr(dq_net, 'name', '?')!r}: expected a pull-up resistor to a supply rail "
                f"(SCH-005 example rule; see openhac.stdlib.erc_rules)."
            )
        return msgs

    return _hook


def uart_rx_pullup_erc_hook(rx_net):
    """Build ``fn(board)`` that expects *rx_net* to have a pull-up to a supply-named net (idle-high UART RX, SCH-005)."""

    def _hook(board):
        _ = board
        msgs = []
        if not net_has_resistor_pullup_to_rail(rx_net):
            msgs.append(
                f"UART RX net {getattr(rx_net, 'name', '?')!r}: expected a pull-up resistor to a supply rail "
                f"(SCH-005 example rule; see openhac.stdlib.erc_rules)."
            )
        return msgs

    return _hook


def i2c_pullup_erc_hook(sda_net, scl_net):
    """Build ``fn(board)`` that requires pull-up resistors from *sda_net* / *scl_net* to a supply-named net."""

    def _hook(board):
        _ = board
        msgs = []
        if not net_has_resistor_pullup_to_rail(sda_net):
            msgs.append(
                f"I2C SDA net {getattr(sda_net, 'name', '?')!r}: expected a resistor to a supply rail "
                f"(SCH-005 example rule; see openhac.stdlib.erc_rules)."
            )
        if not net_has_resistor_pullup_to_rail(scl_net):
            msgs.append(
                f"I2C SCL net {getattr(scl_net, 'name', '?')!r}: expected a resistor to a supply rail "
                f"(SCH-005 example rule; see openhac.stdlib.erc_rules)."
            )
        return msgs

    return _hook


def reset_pullup_erc_hook(rst_n_net):
    """Build ``fn(board)`` for active-low reset: resistor to a supply rail (SCH-005)."""

    def _hook(board):
        _ = board
        msgs = []
        if not net_has_resistor_pullup_to_rail(rst_n_net):
            msgs.append(
                f"Reset net {getattr(rst_n_net, 'name', '?')!r}: expected a pull-up resistor to a supply rail "
                f"(SCH-005 example rule; see openhac.stdlib.erc_rules)."
            )
        return msgs

    return _hook


def mdio_pullup_erc_hook(mdio_net):
    """Build ``fn(board)`` expecting MDIO to have a pull-up to a supply-looking rail (SCH-005)."""

    def _hook(board):
        _ = board
        msgs = []
        if not net_has_resistor_pullup_to_rail(mdio_net):
            msgs.append(
                f"MDIO net {getattr(mdio_net, 'name', '?')!r}: expected a pull-up resistor to a supply rail "
                f"(SCH-005 example rule; see openhac.stdlib.erc_rules)."
            )
        return msgs

    return _hook


def spi_cs_pullup_erc_hook(cs_n_net):
    """Build ``fn(board)`` that expects an active-low CS net to have a resistor to a supply-looking rail (SCH-005)."""

    def _hook(board):
        _ = board
        msgs = []
        if not net_has_resistor_pullup_to_rail(cs_n_net):
            msgs.append(
                f"SPI CS net {getattr(cs_n_net, 'name', '?')!r}: expected a pull-up resistor to a supply rail "
                f"(SCH-005 example rule; see openhac.stdlib.erc_rules)."
            )
        return msgs

    return _hook


def missing_footprint_erc_hook(board):
    """``fn(board)`` that flags SKiDL parts with an empty footprint (SCH-005 example).

    Skips typical schematic-only power symbols (``power`` lib / ``PWR_FLAG``).
    """
    _ = board
    try:
        from openhac.circuit import get_default_circuit
    except Exception:
        return []

    try:
        circuit = get_default_circuit()
    except Exception:
        return []

    msgs: list[str] = []
    for part in circuit.parts:
        fp = str(getattr(part, "footprint", "") or "").strip()
        if fp:
            continue
        lib = str(getattr(part, "lib", "") or getattr(part, "lib_id", "") or "")
        name = str(getattr(part, "name", "") or "").strip().upper()
        if lib == "power" or name == "PWR_FLAG":
            continue
        ref = getattr(part, "ref", "?")
        msgs.append(
            f"Part {ref!r} has no footprint (SCH-005 example rule; see openhac.stdlib.erc_rules)."
        )
    return msgs
