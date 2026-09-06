"""
Parametric connector subsystem classes.

Complex connectors like USB-C and SD slots that require supporting components.
"""

from openhac.core.base import Component, Module
from openhac.stdlib.passives import _ParametricMixin, Resistor, Capacitor
from openhac.core.net import Net


class USB_C_Connector(Module, _ParametricMixin):
    """Parametric USB-C Receptacle with CC pull-down resistors for 5V sinking.

    Args:
        type: "sink" (device) or "source" (host). Default "sink".
        data: "2.0" or "3.0" (USB 2.0 or 3.0/3.1).
        package: Package code (e.g. "HRO_TYPE-C-31-M-12").
    """

    def __init__(self, type: str = "sink", data: str = "2.0",
                 package: str = None, **kwargs):
        super().__init__(f"USB_C_{type.upper()}")

        db = Component.db

        desc = f"USB_C_Connector(type={type}, data={data})"

        comp_data, was_fallback = db.parametric_search(
            "connectors",
            connector_type="USB_C",
            package=package
        )

        if comp_data is None:
            # Common part: HRO TYPE-C-31-M-12 (USB 2.0 Sink)
            generic_name = "USB_C_Receptacle_USB2_Sink"
            comp_data = db.get_component(generic_name)
            if comp_data is None:
                comp_data = Component._live_lookup(generic_name)
            if comp_data is None:
                self._raise_not_found(desc)
            was_fallback = True

        if was_fallback:
            self._warn_soft_fallback(desc, comp_data)

        self.conn = self.add(Component(comp_data["generic_name"], comp_data=comp_data, **kwargs))
        
        # Explicitly set library to fix symbol resolution issues
        self.conn.lib = "Connector_USB"

        # Sink logic: CC1/CC2 must have 5.1k resistors to GND to request 5V from host
        if type == "sink":
            self.r_cc1 = self.add(Resistor(value="5.1k", package="0402"))
            self.r_cc2 = self.add(Resistor(value="5.1k", package="0402"))
            
            self.gnd = Net("GND")
            self.cc1 = Net("CC1")
            self.cc2 = Net("CC2")
            
            self.r_cc1.p1 += self.cc1
            self.r_cc1.p2 += self.gnd
            self.r_cc2.p1 += self.cc2
            self.r_cc2.p2 += self.gnd
            
            self.conn["CC1"] += self.cc1
            self.conn["CC2"] += self.cc2
            self.conn["GND"] += self.gnd

        # Nets
        self.vbus = Net("VBUS")
        self.dm = Net("D-")
        self.dp = Net("D+")
        
        self.conn["VBUS"] += self.vbus
        self.conn["D-"] += self.dm
        self.conn["D+"] += self.dp

        self.power = self.declare_interface("power", self.vbus, self.gnd)
        self.usb2 = self.declare_interface("usb2", self.dp, self.dm)


class SD_Slot(Module, _ParametricMixin):
    """Parametric microSD card slot.

    Args:
        type: "micro" or "standard".
        package: Package code.
    """

    def __init__(self, type: str = "micro", package: str = None, **kwargs):
        super().__init__(f"SD_{type.upper()}")

        db = Component.db

        desc = f"SD_Slot(type={type})"

        comp_data, was_fallback = db.parametric_search(
            "connectors",
            connector_type=f"{type}_SD",
            package=package
        )

        if comp_data is None:
            generic_name = f"MicroSD_Slot"
            comp_data = db.get_component(generic_name)
            if comp_data is None:
                comp_data = Component._live_lookup(generic_name)
            if comp_data is None:
                self._raise_not_found(desc)
            was_fallback = True

        if was_fallback:
            self._warn_soft_fallback(desc, comp_data)

        self.conn = self.add(Component(comp_data["generic_name"], comp_data=comp_data, **kwargs))
        self.conn.lib = "Connector"

        # SD cards need decoupling
        self.c_bypass = self.add(Capacitor(value="10uF", package="0603"))

        self.vcc = Net("VCC")
        self.gnd = Net("GND")
        
        self.conn["VDD"] += self.vcc, self.c_bypass.p1
        self.conn["VSS"] += self.gnd, self.c_bypass.p2

        self.p_in = self.declare_interface("p_in", self.pin1, self.pin2, self.pin3, self.pin4)


class DSub_Connector(Module, _ParametricMixin):
    """Parametric D-Sub Connector (DB9, DB15, etc.).

    Args:
        pins: Number of pins (9, 15, 25, etc.).
        type: "male" or "female".
    """

    def __init__(self, pins: int = 9, type: str = "female", **kwargs):
        super().__init__(f"DB{pins}_{type.upper()[0]}")

        db = Component.db

        desc = f"DSub(pins={pins}, type={type})"

        comp_data, was_fallback = db.parametric_search(
            "connectors_dsub",
            pins=pins,
            gender=type
        )

        if comp_data is None:
            # Common part: generic DB9
            generic_name = f"DB{pins}"
            comp_data = db.get_component(generic_name)
            if comp_data is None:
                comp_data = Component._live_lookup(generic_name)
            if comp_data is None:
                self._raise_not_found(desc)
            was_fallback = True

        if was_fallback:
            self._warn_soft_fallback(desc, comp_data)

        self.ic = self.add(Component(comp_data["generic_name"], comp_data=comp_data, **kwargs))
        self.ic.lib = "Connector"


class TerminalBlock(Module, _ParametricMixin):
    """Parametric Screw or Push-in Terminal Block.

    Args:
        pins: Number of poles.
        pitch: Pin spacing in mm (e.g., 5.08, 3.5).
    """

    def __init__(self, pins: int = 2, pitch: float = 5.08, **kwargs):
        super().__init__(f"TERM_{pins}P_{pitch}mm")

        db = Component.db

        desc = f"TerminalBlock(pins={pins}, pitch={pitch}mm)"

        comp_data, was_fallback = db.parametric_search(
            "connectors_termblock",
            pins=pins,
            pitch=pitch
        )

        if comp_data is None:
            # Common part: Phoenix Contact style
            generic_name = f"MKDS-3-{pins}"
            comp_data = db.get_component(generic_name)
            if comp_data is None:
                comp_data = Component._live_lookup(generic_name)
            if comp_data is None:
                self._raise_not_found(desc)
            was_fallback = True

        if was_fallback:
            self._warn_soft_fallback(desc, comp_data)

        self.ic = self.add(Component(comp_data["generic_name"], comp_data=comp_data, **kwargs))
        self.ic.lib = "Connector"


class Mezzanine_Connector(Module, _ParametricMixin):
    """Parametric High-Density Board-to-Board Connector.

    Args:
        pins: Total pin count.
        pitch: Pin spacing (e.g., 0.5, 0.8).
        stack_height: Height of the mated boards (mm).
    """

    def __init__(self, pins: int = 60, pitch: float = 0.5,
                 stack_height: float = 5.0, **kwargs):
        super().__init__(f"MEZZ_{pins}P_{stack_height}mm")

        db = Component.db

        desc = f"Mezzanine(pins={pins}, pitch={pitch}mm, height={stack_height}mm)"

        comp_data, was_fallback = db.parametric_search(
            "connectors_mezzanine",
            pins=pins,
            pitch=pitch,
            height=stack_height
        )

        if comp_data is None:
            # Common part: Hirose DF40 or similar
            generic_name = "DF40"
            comp_data = db.get_component(generic_name)
            if comp_data is None:
                comp_data = Component._live_lookup(generic_name)
            if comp_data is None:
                self._raise_not_found(desc)
            was_fallback = True

        if was_fallback:
            self._warn_soft_fallback(desc, comp_data)

        self.ic = self.add(Component(comp_data["generic_name"], comp_data=comp_data, **kwargs))
        self.ic.lib = "Connector"

        self.spi = self.declare_interface("spi", self.conn["MOSI"], self.conn["MISO"], self.conn["SCK"], self.conn["CS"])
