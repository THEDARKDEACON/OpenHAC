"""Graph ↔ schematic parity (SSO-001) and .kicad_sch parsers."""

from __future__ import annotations

import re

from openhac.schematic.util import (
    kicad_sch_unescape_label,
    net_name,
    part_ref,
    pin_num,
    sorted_net_pins,
)


_WIRE_RE = re.compile(
    r"\(wire\s+\(pts\s+\(xy\s+([-0-9.]+)\s+([-0-9.]+)\)\s+\(xy\s+([-0-9.]+)\s+([-0-9.]+)\)\)"
)
_LABEL_RE = re.compile(
    r'(?:global_label|hierarchical_label|label)\s+"([^"]+)"'
    r'(?:\s+\(shape\s+\w+\))?\s+\(at\s+([-0-9.]+)\s+([-0-9.]+)'
)
_POWER_SYM_RE = re.compile(
    r'\(symbol\s+\(lib_id\s+"power:([^"]+)"\)\s+\(at\s+([-0-9.]+)\s+([-0-9.]+)'
)
_PROP_VAL_RE = re.compile(r'\(property\s+"Value"\s+"([^"]*)"')


def parse_kicad_sch_wire_segments(text: str) -> list[tuple[float, float, float, float]]:
    return [
        (float(m.group(1)), float(m.group(2)), float(m.group(3)), float(m.group(4)))
        for m in _WIRE_RE.finditer(text)
    ]


def parse_kicad_sch_net_labels(text: str) -> list[tuple[str, float, float]]:
    return [
        (kicad_sch_unescape_label(m.group(1)), float(m.group(2)), float(m.group(3)))
        for m in _LABEL_RE.finditer(text)
    ]


def _circuit_nets(circuit) -> list:
    nets = list(getattr(circuit, "nets", []) or [])
    if nets:
        return nets
    parts = list(getattr(circuit, "parts", []) or [])
    from openhac.schematic.collect import collect_parts_and_nets, harvest_nets_from_parts

    if parts:
        return harvest_nets_from_parts(parts)
    _parts, nets = collect_parts_and_nets(None)
    return nets


def net_connectivity_signatures(circuit) -> dict[str, frozenset[tuple[str, str]]]:
    out: dict[str, frozenset[tuple[str, str]]] = {}
    for net in _circuit_nets(circuit):
        pins = sorted_net_pins(net)
        if not pins:
            continue
        name = net_name(net)
        sig = frozenset(
            (part_ref(p.part), pin_num(p))
            for p in pins
            if getattr(p, "part", None) is not None
        )
        out[name] = sig
    return out


def schematic_wire_endpoint_pairs(circuit) -> list[frozenset[tuple[str, str]]]:
    """Logical 2-pin edges for fanout-2 nets (labels used for fanout ≥ 3)."""
    from openhac.schematic.util import net_openhac_type, is_nc_net

    edges = []
    for net in sorted(_circuit_nets(circuit), key=net_name):
        if is_nc_net(net) or net_openhac_type(net) in ("power", "gnd"):
            continue
        pins = sorted_net_pins(net)
        if len(pins) != 2:
            continue
        pa, pb = pins[0], pins[1]
        edges.append(frozenset({
            (part_ref(pa.part), pin_num(pa)),
            (part_ref(pb.part), pin_num(pb)),
        }))
    return edges


def assert_graph_schematic_parity(circuit_or_nets, ir, *, include_power: bool = True) -> None:
    """SSO-001: every graph pin-net appears as a label, wire cluster, or power port."""
    from openhac.core.exceptions import SchematicGenerationError
    from openhac.schematic.util import is_nc_net, is_pwr_flag_part, net_openhac_type

    if hasattr(circuit_or_nets, "nets"):
        nets = list(getattr(circuit_or_nets, "nets", []) or [])
    else:
        nets = list(circuit_or_nets or [])
    power_nets = {p.net for p in ir.power_ports}

    for net in nets:
        if is_nc_net(net):
            continue
        pins = [p for p in sorted_net_pins(net) if not is_pwr_flag_part(getattr(p, "part", None))]
        if not pins:
            continue
        nn = net_name(net)
        ntype = net_openhac_type(net)
        members = {(part_ref(p.part), pin_num(p)) for p in pins}
        if ntype in ("power", "gnd"):
            if include_power and nn not in power_nets:
                raise SchematicGenerationError(
                    f"SSO-001: power net {nn!r} has no power port on the schematic."
                )
            continue
        if len(pins) >= 3:
            names_on_ir = {lb.name for lb in ir.labels}
            if nn not in names_on_ir:
                raise SchematicGenerationError(
                    f"SSO-001: fanout net {nn!r} has no schematic labels."
                )
            continue
        # fanout 2: wire or labels
        if len(pins) == 2:
            has_wire = bool(ir.wires)
            has_lab = any(lb.name == nn for lb in ir.labels)
            if not has_wire and not has_lab:
                raise SchematicGenerationError(
                    f"SSO-001: net {nn!r} {members} has neither wire nor label."
                )
