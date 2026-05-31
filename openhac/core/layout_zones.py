"""Semantic Layout Zones and Precision Analog Constructs for OpenHaC."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from openhac.core.net import Net

logger = logging.getLogger("openhac.layout_zones")


class LayoutZone:
    """A semantic physical region on the PCB used for isolation or grouped placement.
    
    LayoutZones instruct the layout engine (e.g., KiCad) to create Keep-Out areas
    or isolated rooms. Useful for isolating high-voltage domains or sensitive
    precision analog front-ends from noisy digital circuits.
    """
    
    def __init__(self, name: str, clearance_mm: float = 1.0):
        self.name = name
        self.clearance_mm = clearance_mm
        self.members: list[Any] = []  # Modules or Components assigned to this zone
        
    def add_member(self, member: Any) -> None:
        """Assign a module or component to this zone."""
        if member not in self.members:
            self.members.append(member)

    def to_manifest_dict(self) -> dict[str, Any]:
        """Serialize for the layout intent manifest."""
        return {
            "name": self.name,
            "clearance_mm": self.clearance_mm,
            "members": [str(getattr(m, "name", getattr(m, "refdes", "?"))) for m in self.members]
        }


class StarGround:
    """A computational primitive that forces multiple ground nets to connect at exactly one point.
    
    Prevents ground loops by linking isolated grounds (e.g., AGND and DGND)
    at a single physical coordinate or via a specific component (like a zero-ohm resistor or net-tie).
    """
    
    def __init__(self, name: str, nets: list[Net]):
        self.name = name
        self.nets = nets
        
    def to_manifest_dict(self) -> dict[str, Any]:
        """Serialize for the layout intent manifest."""
        return {
            "name": self.name,
            "nets": [str(n.name) for n in self.nets]
        }
