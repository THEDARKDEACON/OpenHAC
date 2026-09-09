"""
Native Circuit class to replace SKiDL dependency.

This class manages the collection of parts and nets, and generates
KiCad-compatible netlists and schematics.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Optional

from openhac.core.part import Part
from openhac.core.net import Net, Bus

logger = logging.getLogger("openhac.core")


class Circuit:
    """Container for all parts and nets in a design.
    
    Replaces SKiDL's Circuit class. Manages the complete circuit state
    and generates output files.
    """
    def __init__(self, name: str = "circuit"):
        self.name = name
        self.parts: list[Part] = []
        self.nets: list[Net] = []
        self.buses: list[Bus] = []
        self._net_counter = 1
        self._refdes_counters: dict[str, int] = {}
        
    def add_part(self, part: Part) -> Part:
        """Add a part to the circuit."""
        self.parts.append(part)
        return part
    
    def add_net(self, net: Net) -> Net:
        """Add a net to the circuit and assign a code."""
        if net.code is None:
            net.code = self._net_counter
            self._net_counter += 1
        if net not in self.nets:
            self.nets.append(net)
        return net
    
    def add_bus(self, bus: Bus) -> Bus:
        """Add a bus to the circuit."""
        if bus not in self.buses:
            self.buses.append(bus)
        # Also add all nets in the bus
        for net in bus:
            self.add_net(net)
        return bus
    
    def auto_generate_refdes(self, prefix: str) -> str:
        """Generate next reference designator for a prefix.
        
        Example: prefix="R" -> "R1", then "R2", etc.
        """
        if prefix not in self._refdes_counters:
            self._refdes_counters[prefix] = 0
        self._refdes_counters[prefix] += 1
        return f"{prefix}{self._refdes_counters[prefix]}"
    
    def get_nets(self) -> list[Net]:
        """Return all nets with connections."""
        return [n for n in self.nets if n.is_connected()]
    
    def get_unconnected_pins(self) -> list:
        """Return all pins that aren't connected to any net."""
        unconnected = []
        for part in self.parts:
            for pin in part.get_pins():
                if not pin.is_connected():
                    unconnected.append((part, pin))
        return unconnected
    
    def generate_netlist(self, filepath: str | Path) -> Path:
        """Generate KiCad netlist file.
        
        Creates a .net file in KiCad-compatible XML format.
        """
        from openhac.compiler.netlist_xml import generate_netlist
        
        return generate_netlist(self, filepath)
    
    def generate_schematic(self, filepath: str | Path) -> Path:
        """Generate KiCad schematic file.
        
        Creates a .kicad_sch file for documentation.
        """
        from openhac.compiler.schematic_writer import SchematicWriter
        
        writer = SchematicWriter()
        return writer.write(self, filepath)
    
    def erc(self) -> list[str]:
        """Run electrical rule checks.
        
        Returns list of error messages.
        """
        errors = []
        
        # Check for unconnected pins
        unconnected = self.get_unconnected_pins()
        if unconnected:
            for part, pin in unconnected:
                errors.append(f"Unconnected pin: {part.refdes} pin {pin.number}")
        
        # Check for single-pin nets
        for net in self.get_nets():
            if len(net.pins) == 1:
                errors.append(f"Single-pin net: {net.name}")
        
        return errors
    
    def __repr__(self) -> str:
        return f"Circuit({self.name}, parts={len(self.parts)}, nets={len(self.nets)})"


# Context management for scoped hardware compilation (Option A)
_fallback_default_circuit: Circuit = Circuit("default")
_active_context_var: ContextVar[Optional["DesignContext"]] = ContextVar("openhac_design_context", default=None)


class DesignContext:
    """Scoped context manager for hardware design isolation (Option A).

    Inside a ``with DesignContext() as ctx:`` block, all instantiated Components,
    Parts, and Nets automatically attach to ``ctx.circuit``. Exiting the block
    restores the prior context without polluting global state.
    """
    def __init__(self, name: str = "design", circuit: Optional[Circuit] = None):
        self.name = name
        self.circuit = circuit if circuit is not None else Circuit(name)
        self._token = None

    def __enter__(self) -> "DesignContext":
        self._token = _active_context_var.set(self)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._token is not None:
            _active_context_var.reset(self._token)
            self._token = None

    def reset(self) -> None:
        """Reset the circuit in this context."""
        self.circuit = Circuit(self.name)

    def __repr__(self) -> str:
        return f"DesignContext({self.name!r}, circuit={self.circuit!r})"


def get_active_design_context() -> Optional[DesignContext]:
    """Return the currently active DesignContext, or None."""
    return _active_context_var.get()


def get_active_circuit() -> Circuit:
    """Return the currently active Circuit (scoped context circuit or fallback)."""
    ctx = _active_context_var.get()
    if ctx is not None:
        return ctx.circuit
    return _fallback_default_circuit


class _CircuitProxy(Circuit):
    """Dynamic proxy forwarding operations to the active Circuit in ContextVar."""
    def __init__(self):
        # State lives on the target circuit returned by get_active_circuit()
        pass

    def __getattr__(self, name: str) -> Any:
        return getattr(get_active_circuit(), name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(get_active_circuit(), name, value)

    def __repr__(self) -> str:
        return repr(get_active_circuit())

    def __iter__(self):
        return iter(get_active_circuit().parts)

    def add_part(self, part: Part) -> Part:
        return get_active_circuit().add_part(part)

    def add_net(self, net: Net) -> Net:
        return get_active_circuit().add_net(net)

    def add_bus(self, bus: Bus) -> Bus:
        return get_active_circuit().add_bus(bus)

    def auto_generate_refdes(self, prefix: str) -> str:
        return get_active_circuit().auto_generate_refdes(prefix)

    def get_nets(self) -> list[Net]:
        return get_active_circuit().get_nets()

    def get_unconnected_pins(self) -> list:
        return get_active_circuit().get_unconnected_pins()

    def generate_netlist(self, filepath: str | Path) -> Path:
        return get_active_circuit().generate_netlist(filepath)

    def generate_schematic(self, filepath: str | Path) -> Path:
        return get_active_circuit().generate_schematic(filepath)

    def erc(self) -> list[str]:
        return get_active_circuit().erc()


# Transparent proxy providing backward compatibility with v1 syntax
default_circuit: Circuit = _CircuitProxy()


def reset_default_circuit():
    """Reset the active circuit (or the global fallback)."""
    global _fallback_default_circuit
    ctx = _active_context_var.get()
    if ctx is not None:
        ctx.reset()
    else:
        _fallback_default_circuit = Circuit("default")
    Net._counter = 0  # Reset net naming counter

