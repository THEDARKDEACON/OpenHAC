"""Circuit Elaboration Engine (AST/Circuit -> CircuitIR) (Phase 3).

Walks the active DesignContext, Circuit graph, and Board hierarchy to elaborate
a mutable hardware model into a frozen, immutable CircuitIR data structure.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from openhac.circuit import get_default_circuit
from openhac.core.base import Module
from openhac.core.board import Board
from openhac.core.circuit import Circuit
from openhac.core.dnp import part_is_dnp
from openhac.core.domains import DomainKind, ElectricalDomain, PowerDomain
from openhac.core.protocol import SignalDirection
from openhac.core.constraints import Constraint, evaluate_constraints
from openhac.ir.circuit_ir import (
    BusNode,
    CircuitIR,
    ComponentNode,
    ConstraintNode,
    ModuleNode,
    NetNode,
    PinNode,
)

logger = logging.getLogger("openhac.elaborator")

_PIN_TYPE_TO_DIR = {
    "input": SignalDirection.INPUT,
    "output": SignalDirection.OUTPUT,
    "inout": SignalDirection.INOUT,
    "bidirectional": SignalDirection.INOUT,
    "passive": SignalDirection.PASSIVE,
    "power": SignalDirection.POWER_IN,
    "power_in": SignalDirection.POWER_IN,
    "power_out": SignalDirection.POWER_OUT,
    "tristate": SignalDirection.TRISTATE,
    "open_drain": SignalDirection.OPEN_DRAIN,
}


def _infer_direction(pin_type: str, pin_name: str) -> SignalDirection:
    ptype_lower = str(pin_type or "passive").lower()
    if ptype_lower in _PIN_TYPE_TO_DIR:
        base_dir = _PIN_TYPE_TO_DIR[ptype_lower]
        # Refine power if name indicates source
        if base_dir == SignalDirection.POWER_IN:
            pname_upper = str(pin_name or "").upper()
            if any(x in pname_upper for x in ["OUT", "VOUT", "REG_OUT"]):
                return SignalDirection.POWER_OUT
        return base_dir
    return SignalDirection.PASSIVE


def _infer_rail_voltage(net_name: str) -> Optional[float]:
    m = re.search(r"(\d+)[Vv](\d+)?", net_name)
    if m:
        v_str = m.group(1) + ("." + m.group(2) if m.group(2) else "")
        try:
            return float(v_str)
        except ValueError:
            pass
    return None


def elaborate(
    circuit: Optional[Circuit] = None,
    board: Optional[Board] = None,
    *,
    name: Optional[str] = None,
) -> CircuitIR:
    """Elaborate a Circuit and/or Board design into an immutable CircuitIR.

    Args:
        circuit: Circuit instance containing parts and nets. If None, resolves
                 from active DesignContext / default_circuit.
        board: Optional Board container providing module hierarchy and layout constraints.
        name: Override design name in the CircuitIR root.

    Returns:
        Frozen, fully-resolved CircuitIR graph.
    """
    if circuit is None:
        circuit = get_default_circuit()

    design_name = name or (board.name if board and hasattr(board, "name") else circuit.name)
    modules: Dict[str, ModuleNode] = {}
    components: Dict[str, ComponentNode] = {}
    nets: Dict[str, NetNode] = {}
    buses: Dict[str, BusNode] = {}
    constraints: List[ConstraintNode] = []
    metadata: Dict[str, Any] = {}

    part_to_fq_path: Dict[int, str] = {}

    # 1. Traverse Module Hierarchy if Board or modules available
    if board is not None and hasattr(board, "modules"):
        metadata["board_size_mm"] = getattr(board, "size_mm", None)
        metadata["layers"] = getattr(board, "layers", 2)

        def traverse_module(mod: Any, parent_path: str = "root") -> str:
            mod_name = getattr(mod, "name", mod.__class__.__name__)
            fq_path = f"{parent_path}.{mod_name}" if parent_path != "root" else mod_name
            child_paths = []
            comp_paths = []

            # Process child components
            for item in getattr(mod, "components", []):
                if isinstance(item, Module):
                    child_path = traverse_module(item, fq_path)
                    child_paths.append(child_path)
                else:
                    part_ref = getattr(item, "refdes", getattr(item, "ref", None))
                    if part_ref:
                        comp_fq = f"{fq_path}.{part_ref}"
                        comp_paths.append(comp_fq)
                        part_obj = getattr(item, "part", item)
                        part_to_fq_path[id(part_obj)] = comp_fq
                        if hasattr(part_obj, "fields") and isinstance(part_obj.fields, dict):
                            part_obj.fields.setdefault("OpenHaC_Module", str(mod_name))

            iface_bindings: dict[str, str] = {}
            for ifaces in (
                getattr(mod, "required_interfaces", {}) or {},
                getattr(mod, "optional_interfaces", {}) or {},
            ):
                for iface_name, iface in ifaces.items():
                    for sig_name, net in (getattr(iface, "named_signals", {}) or {}).items():
                        if net:
                            nn = getattr(net, "name", str(net))
                            iface_bindings[f"{iface_name}.{sig_name}"] = nn
                    for i, net in enumerate(getattr(iface, "signals", []) or []):
                        if net:
                            nn = getattr(net, "name", str(net))
                            iface_bindings[f"{iface_name}_{i}"] = nn
            try:
                from openhac.core.protocol import Protocol
                for attr_name, attr_val in getattr(mod, "__dict__", {}).items():
                    if isinstance(attr_val, Protocol):
                        for sig in attr_val.signals():
                            if sig.net:
                                nn = getattr(sig.net, "name", str(sig.net))
                                iface_bindings[f"{attr_name}.{sig.name}"] = nn
            except Exception:
                pass

            modules[fq_path] = ModuleNode(
                fq_path=fq_path,
                name=mod_name,
                parent_path=parent_path if parent_path != "root" else None,
                child_module_paths=tuple(child_paths),
                component_paths=tuple(comp_paths),
                interface_bindings=iface_bindings,
            )
            return fq_path

        for top_mod in getattr(board, "modules", []):
            traverse_module(top_mod)

    # 2. Elaborate Parts into ComponentNodes
    parts = list(getattr(circuit, "parts", []) or [])
    for part in parts:
        refdes = str(getattr(part, "refdes", getattr(part, "ref", "?")))
        value = str(getattr(part, "value", ""))
        footprint = str(getattr(part, "footprint", ""))
        fields = dict(getattr(part, "fields", {}) or {})
        mpn = str(fields.get("mpn", fields.get("MPN", refdes)))
        symbol = str(fields.get("kicad_symbol", fields.get("symbol", "")))
        dnp = part_is_dnp(part)
        fq_path = part_to_fq_path.get(id(part), refdes)

        pins: Dict[str, PinNode] = {}
        part_pins = getattr(part, "get_pins", lambda: getattr(part, "pins", []))()
        if isinstance(part_pins, dict):
            part_pins = list(part_pins.values())

        for pin in part_pins:
            p_num = str(getattr(pin, "number", getattr(pin, "num", "?")))
            p_name = str(getattr(pin, "name", p_num))
            p_type = getattr(pin, "pin_type", "passive")
            p_dir = getattr(pin, "direction", None) or _infer_direction(p_type, p_name)
            p_domain = getattr(pin, "domain", None)
            p_net = getattr(pin, "net", None)
            net_id = str(p_net.name) if p_net is not None and getattr(p_net, "name", None) else None

            pins[p_num] = PinNode(
                number=p_num,
                name=p_name,
                direction=p_dir,
                domain=p_domain,
                connected_net_id=net_id,
                is_connected=pin.is_connected() if hasattr(pin, "is_connected") else bool(p_net),
                logic_level=getattr(pin, "logic_level", None),
                voltage_rating=getattr(pin, "voltage_rating", None),
                current_limit=getattr(pin, "current_limit", None),
            )

        components[refdes] = ComponentNode(
            fq_path=fq_path,
            refdes=refdes,
            mpn=mpn,
            value=value,
            footprint=footprint,
            symbol=symbol,
            pins=pins,
            attributes=fields,
            dnp=dnp,
        )

    # 3. Elaborate Nets into NetNodes
    circuit_nets = list(getattr(circuit, "nets", []) or [])
    known_net_ids = {id(n) for n in circuit_nets}
    for part in parts:
        pins_dict = getattr(part, "pins", {})
        pin_list = pins_dict.values() if isinstance(pins_dict, dict) else pins_dict
        for pin in pin_list:
            p_net = getattr(pin, "net", None)
            if p_net is not None and id(p_net) not in known_net_ids:
                known_net_ids.add(id(p_net))
                circuit_nets.append(p_net)

    for net in circuit_nets:
        # Skip alias-merged nets
        if getattr(net, "merged_into", None) is not None:
            continue
        net_name = str(getattr(net, "name", ""))
        if not net_name or net_name == "__NOCONNECT":
            continue

        # Gather pin connections
        connected_pins = []
        net_pins = getattr(net, "pins", [])
        for pin in net_pins:
            part = getattr(pin, "part", None)
            if part:
                p_ref = getattr(part, "refdes", getattr(part, "ref", "?"))
                p_num = getattr(pin, "number", getattr(pin, "num", "?"))
                connected_pins.append(f"{p_ref}.{p_num}")

        # Classify power and ground
        net_name_lower = net_name.lower()
        ntype = getattr(net, "_openhac_net_type", None)
        is_power = (
            ntype == "power"
            or any(net_name_lower.startswith(p) for p in ["vcc", "vin", "3v3", "5v", "12v", "vbat", "vbus"])
        )
        is_ground = (
            ntype == "gnd"
            or any(net_name_lower.startswith(g) for g in ["gnd", "vss", "ground", "com"])
        )

        voltage = None
        if board is not None and hasattr(board, "declared_supply_voltages_v"):
            voltages = getattr(board, "declared_supply_voltages_v", {}) or {}
            voltage = voltages.get(net_name) or voltages.get(net_name_lower)
        if voltage is None and is_power:
            voltage = _infer_rail_voltage(net_name)

        net_domain = getattr(net, "domain", None)
        if net_domain is None and is_power and voltage is not None:
            net_domain = PowerDomain(voltage, name=net_name)

        nets[net_name] = NetNode(
            net_id=net_name,
            name=net_name,
            domain=net_domain,
            connected_pin_paths=tuple(sorted(connected_pins)),
            net_class="Power" if is_power else ("Ground" if is_ground else "Default"),
            is_power=is_power,
            is_ground=is_ground,
            voltage=voltage,
        )

    # 4. Elaborate Buses
    circuit_buses = list(getattr(circuit, "buses", []) or [])
    for bus in circuit_buses:
        bus_name = str(getattr(bus, "name", "BUS"))
        member_ids = [n.name for n in bus if hasattr(n, "name")]
        buses[bus_name] = BusNode(
            bus_id=bus_name,
            name=bus_name,
            width=len(bus),
            member_net_ids=tuple(member_ids),
        )

    # 5. Extract Constraints if board provided
    if board is not None:
        if hasattr(board, "min_trace_width_mm") and board.min_trace_width_mm:
            constraints.append(
                ConstraintNode(
                    kind="min_trace_width",
                    target_ids=("*",),
                    parameters={"min_width_mm": board.min_trace_width_mm},
                )
            )
        if hasattr(board, "min_clearance_mm") and board.min_clearance_mm:
            constraints.append(
                ConstraintNode(
                    kind="min_clearance",
                    target_ids=("*",),
                    parameters={"clearance_mm": board.min_clearance_mm},
                )
            )

        # Inspect @constraint decorated methods on board and modules
        eval_constraints: List[Constraint] = evaluate_constraints(board)
        for mod in getattr(board, "modules", []):
            eval_constraints.extend(evaluate_constraints(mod))

        for c_obj in eval_constraints:
            constraints.append(c_obj.to_circuit_ir_node())

        # Inspect board.constraints list
        for c in getattr(board, "constraints", []) or []:
            if isinstance(c, Constraint):
                constraints.append(c.to_circuit_ir_node())
            elif isinstance(c, dict):
                c_type = str(c.get("type", "")).lower()
                c_args = c.get("args", ())
                if c_type in ("diff_pair", "differential_pair") and len(c_args) >= 2:
                    p = getattr(c_args[0], "name", str(c_args[0]))
                    n = getattr(c_args[1], "name", str(c_args[1]))
                    z0 = float(c_args[2]) if len(c_args) > 2 else 90.0
                    constraints.append(
                        ConstraintNode(
                            kind="differential_pair",
                            target_ids=(p, n),
                            parameters={"target_impedance_ohms": z0, "net_p": p, "net_n": n},
                        )
                    )
                elif c_type == "distance_min" and len(c_args) >= 3:
                    a = getattr(c_args[0], "name", getattr(c_args[0], "refdes", str(c_args[0])))
                    b = getattr(c_args[1], "name", getattr(c_args[1], "refdes", str(c_args[1])))
                    constraints.append(
                        ConstraintNode(
                            kind="distance_min",
                            target_ids=(a, b),
                            parameters={"min_distance_mm": float(c_args[2])},
                        )
                    )
                elif c_type == "distance_max" and len(c_args) >= 3:
                    a = getattr(c_args[0], "name", getattr(c_args[0], "refdes", str(c_args[0])))
                    b = getattr(c_args[1], "name", getattr(c_args[1], "refdes", str(c_args[1])))
                    constraints.append(
                        ConstraintNode(
                            kind="distance_max",
                            target_ids=(a, b),
                            parameters={"max_distance_mm": float(c_args[2])},
                        )
                    )
                elif c_type == "exact_center" and len(c_args) >= 1:
                    item = getattr(c_args[0], "name", getattr(c_args[0], "refdes", str(c_args[0])))
                    constraints.append(
                        ConstraintNode(
                            kind="exact_center",
                            target_ids=(item,),
                            parameters={},
                        )
                    )
                elif c_type == "edge" and len(c_args) >= 2:
                    mod = getattr(c_args[0], "name", getattr(c_args[0], "refdes", str(c_args[0])))
                    edge = str(c_args[1])
                    constraints.append(
                        ConstraintNode(
                            kind="edge",
                            target_ids=(mod,),
                            parameters={"edge": edge},
                        )
                    )
                else:
                    constraints.append(
                        ConstraintNode(
                            kind=c_type or "unknown",
                            target_ids=(),
                            parameters={"raw": str(c)},
                        )
                    )

    cir = CircuitIR(
        name=design_name,
        modules=modules,
        components=components,
        nets=nets,
        buses=buses,
        constraints=tuple(constraints),
        metadata=metadata,
    )
    logger.info(
        f"Elaborated CircuitIR '{design_name}' with "
        f"{len(components)} components, {len(nets)} nets, {len(buses)} buses."
    )
    return cir
