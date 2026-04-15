"""
Native Net and Bus classes to replace SKiDL dependency.

These classes provide the same API as SKiDL's Net/Bus but without
the SKiDL backend.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("openhac.core")


class Net:
    """Represents an electrical net/wire in the circuit.
    
    Replaces SKiDL's Net class. Tracks connected pins and generates
    netlist entries.
    """
    
    # Class-level counter for auto-naming
    _counter = 0
    
    def __init__(self, name: Optional[str] = None):
        if name is None:
            # Auto-generate name like SKiDL does: _1, _2, etc.
            Net._counter += 1
            name = f"_{Net._counter}"
        
        self.name = name
        self.pins: list[Pin] = []
        self.code: Optional[int] = None  # Assigned by Circuit
        
    def add_pin(self, pin: Pin):
        """Connect a pin to this net."""
        if pin not in self.pins:
            self.pins.append(pin)
            pin.net = self
    
    def __add__(self, other: Net | Pin) -> Net:
        """Merge two nets or add a pin using + operator."""
        if isinstance(other, Net):
            # Merge other net into this one
            for pin in other.pins:
                self.add_pin(pin)
            return self
        elif isinstance(other, Pin):
            self.add_pin(other)
            return self
        else:
            raise TypeError(f"Cannot add {type(other)} to Net")
    
    def __iadd__(self, other: Net | Pin) -> Net:
        """Merge nets or add pin using += operator."""
        return self.__add__(other)
    
    def is_connected(self) -> bool:
        """Check if any pins are connected to this net."""
        return len(self.pins) > 0
    
    def __repr__(self) -> str:
        return f"Net({self.name}, pins={len(self.pins)})"


class Bus:
    """Represents a bus (group of related nets).
    
    Replaces SKiDL's Bus class. Useful for data buses, address buses, etc.
    """
    
    def __init__(self, name: str, width: int = 8):
        self.name = name
        self.width = width
        self.nets: list[Net] = []
        
        # Create individual nets for each bus line
        for i in range(width):
            net = Net(f"{name}_{i}")
            self.nets.append(net)
    
    def __getitem__(self, index: int) -> Net:
        """Get a specific net from the bus by index."""
        if 0 <= index < self.width:
            return self.nets[index]
        raise IndexError(f"Bus index {index} out of range (0-{self.width-1})")
    
    def __len__(self) -> int:
        """Return bus width."""
        return self.width
    
    def __iter__(self):
        """Iterate over all nets in the bus."""
        return iter(self.nets)
    
    def __repr__(self) -> str:
        return f"Bus({self.name}, width={self.width})"


# Forward reference for type hints
from openhac.core.part import Pin  # noqa: E402
