"""
First-class typed physical layout and DRC constraints for OpenHaC v2.

Allows hardware designers to declare high-level physical, electrical,
and geometric constraints directly in Python, replacing ad-hoc dictionaries.
Compiles down to KiCad 8/9 custom rules (.kicad_dru) and FreeRouting DSN rules.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

from openhac.ir.circuit_ir import ConstraintNode


class Constraint(ABC):
    """Abstract base class for all OpenHaC physical and electrical constraints."""

    @abstractmethod
    def to_circuit_ir_node(self) -> ConstraintNode:
        """Convert this constraint into an immutable CIR ConstraintNode."""
        pass

    @abstractmethod
    def to_kicad_dru_rule(self) -> str:
        """Render this constraint into a KiCad 8/9 custom DRC rule (.kicad_dru S-expression)."""
        pass

    def to_dict(self) -> Dict[str, Any]:
        return self.to_circuit_ir_node().to_dict()


@dataclass(frozen=True)
class DifferentialPairConstraint(Constraint):
    """Controlled impedance differential pair constraint."""
    net_p: str
    net_n: str
    target_impedance_ohms: float = 90.0
    tolerance_ohms: float = 5.0
    min_gap_mm: Optional[float] = None
    opt_gap_mm: Optional[float] = None
    max_gap_mm: Optional[float] = None
    max_skew_ps: Optional[float] = None
    max_skew_mm: Optional[float] = None
    name: Optional[str] = None

    def to_circuit_ir_node(self) -> ConstraintNode:
        params: Dict[str, Any] = {
            "net_p": self.net_p,
            "net_n": self.net_n,
            "target_impedance_ohms": self.target_impedance_ohms,
            "tolerance_ohms": self.tolerance_ohms,
        }
        if self.min_gap_mm is not None:
            params["min_gap_mm"] = self.min_gap_mm
        if self.opt_gap_mm is not None:
            params["opt_gap_mm"] = self.opt_gap_mm
        if self.max_gap_mm is not None:
            params["max_gap_mm"] = self.max_gap_mm
        if self.max_skew_ps is not None:
            params["max_skew_ps"] = self.max_skew_ps
        if self.max_skew_mm is not None:
            params["max_skew_mm"] = self.max_skew_mm

        return ConstraintNode(
            kind="differential_pair",
            target_ids=(self.net_p, self.net_n),
            parameters=params,
        )

    def to_kicad_dru_rule(self) -> str:
        rule_name = self.name or f"DiffPair_{self.net_p}_{self.net_n}"
        # Default gap estimation if not specified (e.g. 0.15mm - 0.25mm)
        min_g = self.min_gap_mm if self.min_gap_mm is not None else 0.15
        opt_g = self.opt_gap_mm if self.opt_gap_mm is not None else 0.18
        max_g = self.max_gap_mm if self.max_gap_mm is not None else 0.22

        lines = [
            f'(rule "{rule_name}"',
            f'  (constraint diff_pair_gap (min {min_g}mm) (opt {opt_g}mm) (max {max_g}mm))',
            f'  (condition "A.NetName == \'{self.net_p}\' && B.NetName == \'{self.net_n}\'"))',
        ]
        return "\n".join(lines)


@dataclass(frozen=True)
class ClearanceConstraint(Constraint):
    """Voltage clearance or net/netclass isolation constraint."""
    min_clearance_mm: float
    net_a: Optional[str] = None
    net_b: Optional[str] = None
    netclass_a: Optional[str] = None
    netclass_b: Optional[str] = None
    name: Optional[str] = None

    def to_circuit_ir_node(self) -> ConstraintNode:
        targets = []
        if self.net_a:
            targets.append(self.net_a)
        if self.net_b:
            targets.append(self.net_b)

        params: Dict[str, Any] = {"min_clearance_mm": self.min_clearance_mm}
        if self.netclass_a:
            params["netclass_a"] = self.netclass_a
        if self.netclass_b:
            params["netclass_b"] = self.netclass_b

        return ConstraintNode(
            kind="clearance",
            target_ids=tuple(targets),
            parameters=params,
        )

    def to_kicad_dru_rule(self) -> str:
        rule_name = self.name or f"Clearance_{int(self.min_clearance_mm * 1000)}um"
        if self.netclass_a and self.netclass_b:
            condition = f"A.hasNetclass('{self.netclass_a}') && B.hasNetclass('{self.netclass_b}')"
        elif self.netclass_a and not self.netclass_b:
            condition = f"A.hasNetclass('{self.netclass_a}') && !B.hasNetclass('{self.netclass_a}')"
        elif self.net_a and self.net_b:
            condition = f"(A.NetName == '{self.net_a}' && B.NetName == '{self.net_b}') || (A.NetName == '{self.net_b}' && B.NetName == '{self.net_a}')"
        elif self.net_a:
            condition = f"A.NetName == '{self.net_a}' && B.NetName != '{self.net_a}'"
        else:
            condition = "true"

        lines = [
            f'(rule "{rule_name}"',
            f'  (constraint clearance (min {self.min_clearance_mm}mm))',
            f'  (condition "{condition}"))',
        ]
        return "\n".join(lines)


@dataclass(frozen=True)
class TraceWidthConstraint(Constraint):
    """Trace width constraint for high-current or impedance control."""
    min_width_mm: float
    opt_width_mm: Optional[float] = None
    max_width_mm: Optional[float] = None
    net: Optional[str] = None
    netclass: Optional[str] = None
    name: Optional[str] = None

    def to_circuit_ir_node(self) -> ConstraintNode:
        targets = (self.net,) if self.net else ()
        params: Dict[str, Any] = {"min_width_mm": self.min_width_mm}
        if self.opt_width_mm is not None:
            params["opt_width_mm"] = self.opt_width_mm
        if self.max_width_mm is not None:
            params["max_width_mm"] = self.max_width_mm
        if self.netclass:
            params["netclass"] = self.netclass

        return ConstraintNode(
            kind="trace_width",
            target_ids=targets,
            parameters=params,
        )

    def to_kicad_dru_rule(self) -> str:
        rule_name = self.name or (f"Width_{self.net}" if self.net else f"Width_{self.netclass or 'Default'}")
        parts = [f"min {self.min_width_mm}mm"]
        if self.opt_width_mm is not None:
            parts.append(f"opt {self.opt_width_mm}mm")
        if self.max_width_mm is not None:
            parts.append(f"max {self.max_width_mm}mm")

        constraint_body = " ".join(parts)
        if self.net:
            condition = f"A.NetName == '{self.net}'"
        elif self.netclass:
            condition = f"A.hasNetclass('{self.netclass}')"
        else:
            condition = "true"

        lines = [
            f'(rule "{rule_name}"',
            f'  (constraint track_width ({constraint_body}))',
            f'  (condition "{condition}"))',
        ]
        return "\n".join(lines)


@dataclass(frozen=True)
class LengthMatchConstraint(Constraint):
    """Trace length matching constraint across a bus or group of signals."""
    nets: Tuple[str, ...]
    tolerance_mm: float = 0.5
    target_length_mm: Optional[float] = None
    name: Optional[str] = None

    def to_circuit_ir_node(self) -> ConstraintNode:
        params: Dict[str, Any] = {"tolerance_mm": self.tolerance_mm}
        if self.target_length_mm is not None:
            params["target_length_mm"] = self.target_length_mm
        return ConstraintNode(
            kind="length_match",
            target_ids=self.nets,
            parameters=params,
        )

    def to_kicad_dru_rule(self) -> str:
        rule_name = self.name or f"LengthMatch_{len(self.nets)}_nets"
        if self.target_length_mm is not None:
            min_l = max(0.0, self.target_length_mm - self.tolerance_mm)
            max_l = self.target_length_mm + self.tolerance_mm
            constraint_body = f"(constraint length (min {min_l:.3f}mm) (max {max_l:.3f}mm))"
        else:
            constraint_body = f"(constraint length (max {self.tolerance_mm:.3f}mm))"

        net_conditions = " || ".join(f"A.NetName == '{n}'" for n in self.nets)
        lines = [
            f'(rule "{rule_name}"',
            f'  {constraint_body}',
            f'  (condition "{net_conditions}"))',
        ]
        return "\n".join(lines)


@dataclass(frozen=True)
class KeepoutConstraint(Constraint):
    """Keepout zone restricting tracks, vias, or copper pour."""
    x_min: float
    y_min: float
    x_max: float
    y_max: float
    layers: Tuple[str, ...] = ("F.Cu", "B.Cu")
    disallow_tracks: bool = True
    disallow_vias: bool = True
    disallow_copperpour: bool = True
    name: Optional[str] = None

    def to_circuit_ir_node(self) -> ConstraintNode:
        return ConstraintNode(
            kind="keepout",
            target_ids=(),
            parameters={
                "x_min": self.x_min,
                "y_min": self.y_min,
                "x_max": self.x_max,
                "y_max": self.y_max,
                "layers": list(self.layers),
                "disallow_tracks": self.disallow_tracks,
                "disallow_vias": self.disallow_vias,
                "disallow_copperpour": self.disallow_copperpour,
            },
        )

    def to_kicad_dru_rule(self) -> str:
        rule_name = self.name or "KeepoutZone"
        disallows = []
        if self.disallow_tracks:
            disallows.append("track")
        if self.disallow_vias:
            disallows.append("via")
        if self.disallow_copperpour:
            disallows.append("copper_pour")

        disallow_str = " ".join(disallows)
        layers_str = " ".join(f"'{l}'" for l in self.layers)
        lines = [
            f'(rule "{rule_name}"',
            f'  (constraint disallow {disallow_str})',
            f'  (condition "A.intersectsArea([{self.x_min}mm, {self.y_min}mm, {self.x_max}mm, {self.y_max}mm]) && A.Layer.isMember({layers_str})"))',
        ]
        return "\n".join(lines)


# -------------------------------------------------------------------------
# @constraint Decorator & Discovery
# -------------------------------------------------------------------------

def constraint(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator marking a function or method as generating hardware layout constraints.
    
    Example:
        @constraint
        def usb_diff_pair(board):
            return DifferentialPairConstraint(
                net_p="USB_DP",
                net_n="USB_DM",
                target_impedance_ohms=90.0,
            )
    """
    fn._is_openhac_constraint = True  # type: ignore[attr-defined]
    return fn


def is_constraint_function(obj: Any) -> bool:
    """Check if a function or method was decorated with @constraint."""
    return getattr(obj, "_is_openhac_constraint", False) is True


def evaluate_constraints(container: Any) -> List[Constraint]:
    """Inspect an object (Board, Module, or function) and evaluate all @constraint hooks."""
    results: List[Constraint] = []

    # If it's a direct constraint function
    if callable(container) and is_constraint_function(container):
        res = container()
        if isinstance(res, (list, tuple)):
            results.extend([c for c in res if isinstance(c, Constraint)])
        elif isinstance(res, Constraint):
            results.append(res)
        return results

    # Inspect methods on the container (e.g. Board or Module)
    for attr_name in dir(container):
        if attr_name.startswith("__"):
            continue
        try:
            attr = getattr(container, attr_name)
            if callable(attr) and is_constraint_function(attr):
                res = attr()
                if isinstance(res, (list, tuple)):
                    results.extend([c for c in res if isinstance(c, Constraint)])
                elif isinstance(res, Constraint):
                    results.append(res)
        except Exception:
            continue

    return results
