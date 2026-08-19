"""Collect parts/nets for schematic emission."""

from __future__ import annotations

from openhac.schematic.util import is_pwr_flag_part, net_name, part_stable_key


def harvest_nets_from_parts(parts: list) -> list:
    nets: dict[int, object] = {}
    for part in parts:
        pins = []
        if hasattr(part, "get_pins"):
            try:
                pins = list(part.get_pins())
            except Exception:
                pins = []
        if not pins:
            raw = getattr(part, "pins", None)
            if isinstance(raw, dict):
                pins = list({id(p): p for p in raw.values()}.values())
            else:
                pins = list(raw or [])
        for pin in pins:
            n = getattr(pin, "net", None)
            if n is not None:
                nets[id(n)] = n
    return sorted(nets.values(), key=net_name)


def collect_parts_and_nets(board) -> tuple[list, list]:
    parts: list = []
    seen: set[int] = set()

    def _add(part) -> None:
        if part is None or id(part) in seen:
            return
        if is_pwr_flag_part(part):
            # Graph ERC anchors only; emitter places power:PWR_FLAG (SSO-021).
            return
        seen.add(id(part))
        parts.append(part)

    def _walk(node) -> None:
        from openhac.core.base import Component
        from openhac.core.module import Module

        if isinstance(node, Module):
            items = getattr(node, "components", []) or []
        elif hasattr(node, "modules"):
            items = getattr(node, "modules", []) or []
        else:
            items = []
        for item in items:
            if isinstance(item, Component):
                _add(getattr(item, "part", None))
            elif isinstance(item, Module):
                _walk(item)
            elif hasattr(item, "pins"):
                _add(item)

    if board is not None:
        _walk(board)

    if not parts:
        try:
            from openhac.circuit import get_default_circuit
            c = get_default_circuit()
            for p in list(getattr(c, "parts", []) or []):
                _add(p)
        except Exception:
            pass
    if not parts:
        try:
            import builtins
            sk = getattr(builtins, "default_circuit", None)
            if sk is not None:
                for p in list(getattr(sk, "parts", []) or []):
                    _add(p)
        except Exception:
            pass

    parts.sort(key=part_stable_key)
    return parts, harvest_nets_from_parts(parts)


def interface_nets_for_module(module) -> list:
    """Nets that cross a module boundary or are declared interfaces."""
    nets = []
    mod_parts = []
    if hasattr(module, "components"):
        for comp in getattr(module, "components", []) or []:
            part = getattr(comp, "part", None)
            if part:
                mod_parts.append(part)
    elif isinstance(module, list):
        mod_parts = module
    mod_part_ids = {id(p) for p in mod_parts}
    seen_nets: set[int] = set()
    if hasattr(module, "required_interfaces"):
        for ifaces in (
            getattr(module, "required_interfaces", {}),
            getattr(module, "optional_interfaces", {}),
        ):
            for iface in ifaces.values():
                for net in list(iface.signals) + list(iface.named_signals.values()):
                    if net and id(net) not in seen_nets:
                        seen_nets.add(id(net))
                        nets.append(net)
    for part in mod_parts:
        pins = []
        if hasattr(part, "get_pins"):
            try:
                pins = list(part.get_pins())
            except Exception:
                pins = []
        if not pins:
            raw = getattr(part, "pins", None)
            pins = list(raw.values()) if isinstance(raw, dict) else list(raw or [])
        for pin in pins:
            net = getattr(pin, "net", None)
            if not net or id(net) in seen_nets:
                continue
            net_pins = net.get_pins() if hasattr(net, "get_pins") else getattr(net, "pins", [])
            crosses = False
            for np in net_pins or []:
                p_other = getattr(np, "part", None)
                if p_other and id(p_other) not in mod_part_ids:
                    crosses = True
                    break
            if crosses:
                seen_nets.add(id(net))
                nets.append(net)
    nets.sort(key=net_name)
    return nets
