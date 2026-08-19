"""
Native Circuit class to replace SKiDL dependency.

This class manages the collection of parts and nets, and generates
KiCad-compatible netlists and schematics.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

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


# Global default circuit (like SKiDL's default_circuit)
default_circuit = Circuit("default")


def reset_default_circuit():
    """Reset the global default circuit."""
    global default_circuit
    default_circuit = Circuit("default")
    Net._counter = 0  # Reset net naming counter
