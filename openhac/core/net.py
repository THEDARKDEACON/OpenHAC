"""
Native Net and Bus classes for OpenHaC.

These classes manage electrical connectivity and grouping without external EDA dependencies.
"""

from __future__ import annotations

import logging
from typing import Optional, TYPE_CHECKING
if TYPE_CHECKING:
    from openhac.core.part import Pin

logger = logging.getLogger("openhac.core")


class Net:
    """Represents an electrical net/wire in the circuit.
    
    Replaces SKiDL's Net class. Tracks connected pins and generates
    netlist entries.
    """
    
    # Class-level counter for auto-naming
    _counter = 0
    
    def __new__(cls, name: Optional[str] = None):
        """Enable name-based singleton lookup in the default circuit."""
        if name is not None:
            try:
                from openhac.core.circuit import default_circuit
                for n in default_circuit.nets:
                    if n.name == name:
                        return n
            except (ImportError, AttributeError):
                pass
        return super().__new__(cls)

    def __init__(self, name: Optional[str] = None):
        if hasattr(self, "_initialized"):
            return
            
        if name is None:
            # Auto-generate name like SKiDL does: _1, _2, etc.
            Net._counter += 1
            name = f"_{Net._counter}"
        
        self.name = name
        self.pins: list[Pin] = []
        self.code: Optional[int] = None  # Assigned by Circuit
        self.current_a: float = 0.0  # Current in Amperes for IPC-2152 trace width
        self.guard_net: Optional[Net] = None
        self._initialized = True
        
        # Auto-register with default circuit if possible
        try:
            from openhac.core.circuit import default_circuit
            default_circuit.add_net(self)
        except (ImportError, AttributeError):
            pass
        
    def set_current(self, amps: float) -> Net:
        """Define the expected maximum current on this net (in Amperes).
        Used for physics-based DRC trace width generation via IPC-2152.
        """
        self.current_a = float(amps)
        return self

    def wrap_guard_ring(self, guard_net: "Net") -> Net:
        """Declare an intent to synthesize a grounded copper guard ring tightly coupled to this net.
        
        This prevents leakage currents in precision analog circuits (SIG-006 / PCB-004).
        """
        self.guard_net = guard_net
        return self
        
    def add_pin(self, pin: Pin):
        """Connect a pin to this net."""
        if pin not in self.pins:
            self.pins.append(pin)
            pin.net = self
            
    def get_pins(self) -> list[Pin]:
        """Compatibility alias for SKiDL-like APIs."""
        return self.pins
    
    def __add__(self, other: Net | Pin) -> Net:
        """Merge two nets or add a pin using + operator."""
        if isinstance(other, Net):
            # Resolve aliases to prevent circular references (A->B and B->A)
            self_true = self
            while getattr(self_true, "merged_into", None) is not None:
                self_true = self_true.merged_into  # type: ignore

            other_true = other
            while getattr(other_true, "merged_into", None) is not None:
                other_true = other_true.merged_into  # type: ignore

            if self_true is other_true:
                return self_true

            # Merge other_true into self_true, but skip NC pins
            if getattr(other_true, "name", "") == "__NOCONNECT":
                return self_true
            
            for pin in list(other_true.pins):
                self_true.add_pin(pin)
            other_true.pins.clear()
            other_true.merged_into = self_true  # type: ignore[attr-defined]
            return self_true
        elif type(other).__name__ == "Pin":
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


# TYPE_CHECKING guard avoids a runtime circular import (net → part → net).
# The 'from __future__ import annotations' at the top makes all annotations
# strings at runtime, so Pin is only needed by type-checkers (STYLE-006 fix).
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from openhac.core.part import Pin  # noqa: F401


class _NCNet(Net):
    """Special net representing a 'No Connect' explicitly.
    
    Pins connected to this net are ignored in DRC checks for unconnected pins.
    """
    def __init__(self):
        super().__init__(name="__NOCONNECT")
    
    def __add__(self, other: Net | Pin) -> Net:
        if isinstance(other, Pin):
            other.net = self
            if other not in self.pins:
                self.pins.append(other)
            return self
        elif isinstance(other, Net):
            # Special case: NC net should NEVER merge with or swallow other nets.
            # If someone tries to connect a net to NC, we just return the other net
            # or ignore it depending on the direction. 
            # In OpenHaC, if a pin is already on NC and then connected to a Net,
            # we should move the pin to the Net instead of merging NC into the Net.
            return other
        return super().__add__(other)


# Singleton No Connect net
NC = _NCNet()
