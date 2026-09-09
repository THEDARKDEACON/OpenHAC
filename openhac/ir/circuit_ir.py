"""Circuit Intermediate Representation (CIR) Data Schema (Phase 3).

Defines strongly-typed, immutable dataclasses representing the compiled
hardware graph, completely decoupled from Python AST execution, live database
sessions, or backend CAD tools (KiCad, SPICE, etc.).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union

from openhac.core.domains import DomainKind, ElectricalDomain
from openhac.core.protocol import SignalDirection


def _domain_to_dict(domain: Optional[ElectricalDomain]) -> Optional[Dict[str, Any]]:
    if domain is None:
        return None
    d = asdict(domain)
    if isinstance(domain.kind, DomainKind):
        d["kind"] = domain.kind.value
    elif isinstance(d.get("kind"), Enum):
        d["kind"] = d["kind"].value
    return d


@dataclass(frozen=True)
class PinNode:
    """Immutable representation of a component pin/terminal."""
    number: str
    name: str
    direction: SignalDirection = SignalDirection.PASSIVE
    domain: Optional[ElectricalDomain] = None
    connected_net_id: Optional[str] = None
    is_connected: bool = False
    logic_level: Optional[float] = None
    voltage_rating: Optional[float] = None
    current_limit: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "number": self.number,
            "name": self.name,
            "direction": self.direction.value if isinstance(self.direction, SignalDirection) else str(self.direction),
            "domain": _domain_to_dict(self.domain),
            "connected_net_id": self.connected_net_id,
            "is_connected": self.is_connected,
            "logic_level": self.logic_level,
            "voltage_rating": self.voltage_rating,
            "current_limit": self.current_limit,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> PinNode:
        domain_data = data.get("domain")
        domain = None
        if domain_data:
            kind_val = domain_data.get("kind")
            kind = DomainKind(kind_val) if isinstance(kind_val, str) else kind_val
            domain = ElectricalDomain(
                kind=kind,
                nominal_voltage=domain_data.get("nominal_voltage"),
                voltage_tolerance_pct=domain_data.get("voltage_tolerance_pct", 5.0),
                min_voltage=domain_data.get("min_voltage"),
                max_voltage=domain_data.get("max_voltage"),
                max_current_a=domain_data.get("max_current_a"),
                impedance_target_ohms=domain_data.get("impedance_target_ohms"),
                logic_standard=domain_data.get("logic_standard"),
                name=domain_data.get("name", ""),
            )
        dir_val = data.get("direction", "passive")
        direction = SignalDirection(dir_val) if isinstance(dir_val, str) else dir_val
        return cls(
            number=str(data.get("number", "?")),
            name=str(data.get("name", "?")),
            direction=direction,
            domain=domain,
            connected_net_id=data.get("connected_net_id"),
            is_connected=bool(data.get("is_connected", False)),
            logic_level=data.get("logic_level"),
            voltage_rating=data.get("voltage_rating"),
            current_limit=data.get("current_limit"),
        )


@dataclass(frozen=True)
class ComponentNode:
    """Immutable representation of a physical electronic component or chip."""
    fq_path: str  # Fully qualified hierarchical path, e.g. 'root.power.regulator'
    refdes: str   # Reference designator, e.g. 'U1', 'R1'
    mpn: str
    value: str
    footprint: str
    symbol: str = ""
    pins: Dict[str, PinNode] = field(default_factory=dict)
    attributes: Dict[str, Any] = field(default_factory=dict)
    dnp: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fq_path": self.fq_path,
            "refdes": self.refdes,
            "mpn": self.mpn,
            "value": self.value,
            "footprint": self.footprint,
            "symbol": self.symbol,
            "pins": {k: p.to_dict() for k, p in self.pins.items()},
            "attributes": dict(self.attributes),
            "dnp": self.dnp,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ComponentNode:
        pins = {k: PinNode.from_dict(v) for k, v in data.get("pins", {}).items()}
        return cls(
            fq_path=data.get("fq_path", data.get("refdes", "")),
            refdes=data.get("refdes", ""),
            mpn=data.get("mpn", ""),
            value=data.get("value", ""),
            footprint=data.get("footprint", ""),
            symbol=data.get("symbol", ""),
            pins=pins,
            attributes=dict(data.get("attributes", {})),
            dnp=bool(data.get("dnp", False)),
        )


@dataclass(frozen=True)
class NetNode:
    """Immutable representation of an electrical net connecting pins."""
    net_id: str
    name: str
    domain: Optional[ElectricalDomain] = None
    connected_pin_paths: Tuple[str, ...] = field(default_factory=tuple)  # e.g. ('U1.1', 'U2.4')
    net_class: str = "Default"
    is_power: bool = False
    is_ground: bool = False
    voltage: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "net_id": self.net_id,
            "name": self.name,
            "domain": _domain_to_dict(self.domain),
            "connected_pin_paths": list(self.connected_pin_paths),
            "net_class": self.net_class,
            "is_power": self.is_power,
            "is_ground": self.is_ground,
            "voltage": self.voltage,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> NetNode:
        domain_data = data.get("domain")
        domain = None
        if domain_data:
            kind_val = domain_data.get("kind")
            kind = DomainKind(kind_val) if isinstance(kind_val, str) else kind_val
            domain = ElectricalDomain(
                kind=kind,
                nominal_voltage=domain_data.get("nominal_voltage"),
                voltage_tolerance_pct=domain_data.get("voltage_tolerance_pct", 5.0),
                min_voltage=domain_data.get("min_voltage"),
                max_voltage=domain_data.get("max_voltage"),
                max_current_a=domain_data.get("max_current_a"),
                impedance_target_ohms=domain_data.get("impedance_target_ohms"),
                logic_standard=domain_data.get("logic_standard"),
                name=domain_data.get("name", ""),
            )
        return cls(
            net_id=str(data.get("net_id", data.get("name", ""))),
            name=str(data.get("name", "")),
            domain=domain,
            connected_pin_paths=tuple(data.get("connected_pin_paths", ())),
            net_class=data.get("net_class", "Default"),
            is_power=bool(data.get("is_power", False)),
            is_ground=bool(data.get("is_ground", False)),
            voltage=data.get("voltage"),
        )


@dataclass(frozen=True)
class BusNode:
    """Immutable representation of a multi-bit net bus."""
    bus_id: str
    name: str
    width: int
    member_net_ids: Tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "bus_id": self.bus_id,
            "name": self.name,
            "width": self.width,
            "member_net_ids": list(self.member_net_ids),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> BusNode:
        return cls(
            bus_id=str(data.get("bus_id", "")),
            name=str(data.get("name", "")),
            width=int(data.get("width", 0)),
            member_net_ids=tuple(data.get("member_net_ids", ())),
        )


@dataclass(frozen=True)
class ConstraintNode:
    """Physical/electrical layout or DRC constraint attached to circuit elements."""
    kind: str  # e.g., 'differential_pair', 'length_match', 'trace_width', 'keepout'
    target_ids: Tuple[str, ...] = field(default_factory=tuple)
    parameters: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "target_ids": list(self.target_ids),
            "parameters": dict(self.parameters),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ConstraintNode:
        return cls(
            kind=str(data.get("kind", "")),
            target_ids=tuple(data.get("target_ids", ())),
            parameters=dict(data.get("parameters", {})),
        )


@dataclass(frozen=True)
class ModuleNode:
    """Hierarchical module structural node."""
    fq_path: str
    name: str
    parent_path: Optional[str] = None
    child_module_paths: Tuple[str, ...] = field(default_factory=tuple)
    component_paths: Tuple[str, ...] = field(default_factory=tuple)
    interface_bindings: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fq_path": self.fq_path,
            "name": self.name,
            "parent_path": self.parent_path,
            "child_module_paths": list(self.child_module_paths),
            "component_paths": list(self.component_paths),
            "interface_bindings": dict(self.interface_bindings),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ModuleNode:
        return cls(
            fq_path=str(data.get("fq_path", "")),
            name=str(data.get("name", "")),
            parent_path=data.get("parent_path"),
            child_module_paths=tuple(data.get("child_module_paths", ())),
            component_paths=tuple(data.get("component_paths", ())),
            interface_bindings=dict(data.get("interface_bindings", {})),
        )


@dataclass(frozen=True)
class CircuitIR:
    """Root Circuit Intermediate Representation (CIR) for an entire board or module design."""
    name: str
    modules: Dict[str, ModuleNode] = field(default_factory=dict)
    components: Dict[str, ComponentNode] = field(default_factory=dict)
    nets: Dict[str, NetNode] = field(default_factory=dict)
    buses: Dict[str, BusNode] = field(default_factory=dict)
    constraints: Tuple[ConstraintNode, ...] = field(default_factory=tuple)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def get_component(self, refdes_or_path: str) -> Optional[ComponentNode]:
        """Lookup component by reference designator or fully-qualified path."""
        if refdes_or_path in self.components:
            return self.components[refdes_or_path]
        for comp in self.components.values():
            if comp.refdes == refdes_or_path:
                return comp
        return None

    def get_net(self, net_id_or_name: str) -> Optional[NetNode]:
        """Lookup net by net_id or net name."""
        if net_id_or_name in self.nets:
            return self.nets[net_id_or_name]
        for net in self.nets.values():
            if net.name == net_id_or_name:
                return net
        return None

    def find_pins_on_net(self, net_id_or_name: str) -> List[Tuple[ComponentNode, PinNode]]:
        """Return all (ComponentNode, PinNode) pairs connected to a net."""
        net = self.get_net(net_id_or_name)
        if not net:
            return []
        results = []
        for pin_path in net.connected_pin_paths:
            # pin_path e.g. 'U1.1' or 'root.power.u1.1'
            if '.' in pin_path:
                comp_ref, pin_num = pin_path.rsplit('.', 1)
                comp = self.get_component(comp_ref)
                if comp and pin_num in comp.pins:
                    results.append((comp, comp.pins[pin_num]))
        return results

    def stats(self) -> Dict[str, int]:
        """Return summary element counts."""
        total_pins = sum(len(c.pins) for c in self.components.values())
        return {
            "modules": len(self.modules),
            "components": len(self.components),
            "nets": len(self.nets),
            "buses": len(self.buses),
            "pins": total_pins,
            "constraints": len(self.constraints),
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": "2.0.0",
            "name": self.name,
            "modules": {k: m.to_dict() for k, m in self.modules.items()},
            "components": {k: c.to_dict() for k, c in self.components.items()},
            "nets": {k: n.to_dict() for k, n in self.nets.items()},
            "buses": {k: b.to_dict() for k, b in self.buses.items()},
            "constraints": [c.to_dict() for c in self.constraints],
            "metadata": dict(self.metadata),
        }

    def to_json(self, indent: int = 2) -> str:
        """Serialize the entire CircuitIR to a JSON string."""
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CircuitIR:
        """Deserialize a CircuitIR from a dictionary."""
        modules = {k: ModuleNode.from_dict(v) for k, v in data.get("modules", {}).items()}
        components = {k: ComponentNode.from_dict(v) for k, v in data.get("components", {}).items()}
        nets = {k: NetNode.from_dict(v) for k, v in data.get("nets", {}).items()}
        buses = {k: BusNode.from_dict(v) for k, v in data.get("buses", {}).items()}
        constraints = tuple(ConstraintNode.from_dict(c) for c in data.get("constraints", []))
        return cls(
            name=str(data.get("name", "Circuit")),
            modules=modules,
            components=components,
            nets=nets,
            buses=buses,
            constraints=constraints,
            metadata=dict(data.get("metadata", {})),
        )

    @classmethod
    def from_json(cls, json_str: str) -> CircuitIR:
        """Deserialize a CircuitIR from a JSON string."""
        return cls.from_dict(json.loads(json_str))
