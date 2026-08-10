"""
Native Part and Pin classes to replace SKiDL dependency.

These classes provide the same API as SKiDL's Part but without requiring
KiCad symbol libraries at compile time.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger("openhac.core")


class Pin:
    """Represents a single pin on a component.
    
    Similar to SKiDL's Pin but simplified for native implementation.
    """
    
    def __init__(
        self,
        number: str,
        name: str,
        pin_type: str = "passive",
        logic_level: Optional[float] = None,
        voltage_rating: Optional[float] = None,
        current_limit: Optional[float] = None,
    ):
        self.number = number
        self.name = name
        self.pin_type = pin_type  # input, output, bidirectional, power, passive
        self.logic_level = logic_level        # Expected typical logic voltage (e.g., 3.3, 5.0)
        self.voltage_rating = voltage_rating  # Max absolute voltage for safety validation
        self.current_limit = current_limit    # Max continuous current draw/source for power budgets
        self.net: Optional[Net] = None
        self.part: Optional[Part] = None

    def set_semantics(
        self,
        logic_level: Optional[float] = None,
        voltage_rating: Optional[float] = None,
        current_limit: Optional[float] = None,
    ) -> Pin:
        """Chainable method to set electrical semantic properties for DRC."""
        if logic_level is not None:
            self.logic_level = logic_level
        if voltage_rating is not None:
            self.voltage_rating = voltage_rating
        if current_limit is not None:
            self.current_limit = current_limit
        return self

    @property
    def num(self) -> str:
        """Compatibility alias for SKiDL-like APIs."""
        return self.number
        
    def __add__(self, other) -> Pin:
        """Connect this pin to a net or another pin using + operator.

        Accepts both native ``openhac.core.net.Net`` objects and any duck-typed
        net-like object (e.g. ``skidl.net.Net``) that exposes a ``.pins`` list
        and an ``add_pin(pin)`` method.  This keeps the native Part/Pin API
        compatible with legacy SKiDL-based test fixtures during the migration.
        """
        from openhac.core.net import Net

        def _is_net_like(obj) -> bool:
            """True if *obj* looks like a Net (native or SKiDL duck-typed)."""
            return isinstance(obj, Net) or (
                hasattr(obj, "pins") and (hasattr(obj, "add_pin") or hasattr(obj, "connect"))
            )

        if isinstance(other, Pin):
            # Connecting pin-to-pin: use or create a net
            if self.net and other.net:
                # Both pins have nets - merge them
                if self.net is not other.net:
                    self.net += other.net
            elif self.net:
                # Only self has net - add other pin to it
                self.net.add_pin(other)
            elif other.net:
                # Only other has net - add self to it
                other.net.add_pin(self)
            else:
                # Neither has net - create one
                new_net = Net()
                new_net.add_pin(self)
                new_net.add_pin(other)
            return self
        elif _is_net_like(other):
            # Connecting pin to a net (native Net or any duck-typed net-like object).
            # Support both native .add_pin() and SKiDL-style .connect().
            if self.net:
                # Already on a net — merge the incoming net into ours if possible.
                try:
                    self.net += other
                except Exception:
                    # Fallback: register self on the foreign net via whatever API is available
                    try:
                        other.add_pin(self)
                    except AttributeError:
                        try:
                            other.connect(self)
                        except Exception:
                            pass
            else:
                self.net = other  # type: ignore[assignment]
                try:
                    other.add_pin(self)
                except AttributeError:
                    try:
                        other.connect(self)
                    except Exception:
                        pass
            return self
        else:
            raise TypeError(f"Cannot connect Pin to {type(other)}")
    
    def __iadd__(self, other: Net) -> Pin:
        """Connect this pin to a net using += operator."""
        return self.__add__(other)
    
    def is_connected(self) -> bool:
        """Check if this pin is connected to any net."""
        return self.net is not None
    
    def __repr__(self) -> str:
        return f"Pin({self.number}/{self.name})"


class Part:
    """Represents a component/part in the circuit.
    
    Replaces SKiDL's Part class. Does not require KiCad symbol libraries.
    All pin information comes from the component database.
    """
    
    _id_counter = 0
    
    def __init__(
        self,
        refdes: str,
        footprint: str,
        fields: dict[str, str],
        pins: list[Pin],
        value: str = "",
    ):
        Part._id_counter += 1
        self._part_id = Part._id_counter
        self.refdes = refdes  # Reference designator: "R1", "C2", "U3"
        self.footprint = footprint  # KiCad footprint: "Resistor_SMD:R_0603"
        self.fields = fields  # Manufacturer, MPN, Supplier_SKU, etc.
        self.value = value  # Component value: "10K", "100nF"
        self.pins: dict[str, Pin] = {}  # Map pin number/name -> Pin
        
        # Add pins and link back to this part
        for pin in pins:
            pin.part = self
            self.pins[pin.number] = pin
            # Also index by name if different from number
            if pin.name != pin.number:
                self.pins[pin.name] = pin


    @property
    def ref(self) -> str:
        """Compatibility alias for SKiDL-like APIs."""
        return self.refdes

    @ref.setter
    def ref(self, value: str):
        """Allow setting the reference designator via the 'ref' alias."""
        self.refdes = value

    @property
    def name(self) -> str:
        """Alias for value, used by ERC and other tooling."""
        return self.value

    def add_pin(self, pin: Pin) -> None:
        """Add one pin at runtime (used for implicit pins in handoff/dev mode)."""
        pin.part = self
        self.pins[pin.number] = pin
        if pin.name != pin.number:
            self.pins[pin.name] = pin
    
    def __getitem__(self, pin_id: str) -> Pin:
        """Get a pin by number or name.
        
        Example: part['1'] or part['VCC'] (ints are coerced to str).
        """
        key = pin_id if isinstance(pin_id, str) else str(pin_id)
        if key in self.pins:
            return self.pins[key]
        raise KeyError(f"Pin '{pin_id}' not found in {self.refdes}")
    
    def __setitem__(self, pin_id: str, net: Net):
        """Connect a pin to a net using [] = operator.
        
        Example: part['1'] = net_vcc
        """
        pin = self.__getitem__(pin_id)
        pin += net
    
    def get_pins(self) -> list[Pin]:
        """Return all pins on this part."""
        # Use set to avoid duplicates (pins indexed by both number and name)
        seen = set()
        pins = []
        for pin in self.pins.values():
            if id(pin) not in seen:
                seen.add(id(pin))
                pins.append(pin)
        return pins
    
    def is_connected(self) -> bool:
        """Check if any pin on this part is connected."""
        return any(pin.is_connected() for pin in self.get_pins())
    
    def __repr__(self) -> str:
        return f"Part({self.refdes}, {self.footprint})"


# Forward reference for type hints
from openhac.core.net import Net  # noqa: E402
