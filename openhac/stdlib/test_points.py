"""Mechanical test-point modules for ICT / bring-up (REL-003)."""

from openhac.core.base import Component, Module


class MechTestPoint1mm(Module):
    """1 mm pad test point using seeded generic ``TP_Mech_1mm``."""

    def __init__(self):
        super().__init__("MechTestPoint1mm")
        tp = self.add(Component("TP_Mech_1mm"))
        self.declare_interface("pad", tp["1"])
