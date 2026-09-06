"""
Parametric MCU module.

Supports family-based lookup (e.g. MCU(family="STM32F407")) and
direct MPN lookup (e.g. MCU(mpn="ESP32-WROOM-32E")).
"""

from openhac.core.base import Component, Module
from openhac.stdlib.passives import _ParametricMixin
from openhac.core.net import Net


class MCU(Module, _ParametricMixin):
    """Parametric microcontroller module.

    Args:
        family: MCU family for fuzzy match, e.g. "STM32F407", "ESP32".
        mpn: Exact manufacturer part number.
        package: Package code (optional).
    """

    def __init__(self, family: str = None, mpn: str = None,
                 package: str = None, **kwargs):
        name = f"MCU_{mpn or family or 'Generic'}"
        super().__init__(name)

        db = Component.db

        desc = f"MCU(" + \
               (f"family={family}" if family else "") + \
               (f", mpn={mpn}" if mpn else "") + \
               (f", package={package}" if package else "") + ")"

        comp_data, was_fallback = db.parametric_search(
            "microcontrollers",
            family=family,
            mpn=mpn,
            package=package,
        )

        if comp_data is None:
            # Try direct generic_name lookup
            if mpn:
                comp_data = db.get_component(mpn)
            if comp_data is None and family:
                # Search for family in generic names
                results = db.search_components(query=family, category="microcontrollers")
                if results:
                    comp_data = results[0]
                    was_fallback = True
            if comp_data is None:
                lookup_term = mpn or family or "Generic_MCU"
                comp_data = Component._live_lookup(lookup_term)
                if comp_data:
                    was_fallback = True

        if comp_data is None:
            self._raise_not_found(desc)

        if was_fallback:
            self._warn_soft_fallback(desc, comp_data)

        self._comp = self.add(Component(comp_data["generic_name"], comp_data=comp_data, **kwargs))

        # Standard MCU nets
        self.vcc = Net(f"{name}_VCC")
        self.gnd = Net(f"{name}_GND")

        # Soft pin assignment: try labels, fallback to common numerical pins or skip
        import warnings as _warnings
        def _connect_soft(pins, net):
            for p in pins:
                try:
                    # Check if pin exists in SKiDL Part (avoid NoneType += Net)
                    p_obj = self._comp[p]
                    if p_obj:
                        p_obj += net
                        return True
                except (AttributeError, KeyError, TypeError):
                    continue
            return False

        if not _connect_soft(["VDD", "VCC", "3V3", "1"], self.vcc):
            _warnings.warn(f"Warning: Could not auto-wire VCC for {name}. Manual wiring may be required.")
            
        if not _connect_soft(["VSS", "GND", "2"], self.gnd):
            _warnings.warn(f"Warning: Could not auto-wire GND for {name}. Manual wiring may be required.")

        self.max_current_draw_ma = 250.0

        self.power = self.declare_interface("power", self.vcc, self.gnd)


# --- Specialized MCU Modules (Hard-wired for safety) ---

class ESP32_WROOM(Module):
    """Standard ESP32-WROOM-32E module wrapper."""
    def __init__(self, **kwargs):
        super().__init__("ESP32_WROOM")
        self.mcu = self.add(Component("ESP32-WROOM-32E", **kwargs))

        self.vcc = Net("3V3")
        self.gnd = Net("GND")
        self.en = Net("EN")
        self.io0 = Net("IO0")

        # Data-driven mapping: resolves VCC/GND via semantic logic
        self.mcu["VCC"] += self.vcc
        self.mcu["GND"] += self.gnd
        self.mcu["EN"] += self.en
        self.mcu["IO0"] += self.io0

        self.power = self.declare_interface("power", self.vcc, self.gnd)


class ESP32S3_WROOM(Module):
    """ESP32-S3-WROOM-1/1U module wrapper with AI acceleration."""
    def __init__(self, **kwargs):
        super().__init__("ESP32_S3_WROOM")
        self.mcu = self.add(Component("ESP32-S3-WROOM-1", **kwargs))

        self.vcc = Net("3V3")
        self.gnd = Net("GND")
        self.en = Net("EN")

        # Data-driven mapping: resolves VCC/GND/EN via semantic logic
        self.mcu["VCC"] += self.vcc
        self.mcu["GND"] += self.gnd
        self.mcu["EN"] += self.en

        self.power = self.declare_interface("power", self.vcc, self.gnd)


class Teensy41(Module):
    """Teensy 4.1 Development Board wrapper."""
    def __init__(self, **kwargs):
        super().__init__("Teensy41")
        self.board = self.add(Component("Teensy 4.1", **kwargs))

        self.vin = Net("VIN")
        self.v33 = Net("3V3")
        self.gnd = Net("GND")

        # Teensy 4.1 Pinout (Data-driven lookup)
        self.board["VIN"] += self.vin
        self.board["3V3"] += self.v33
        self.board["GND"] += self.gnd

        self.power_in = self.declare_interface("power_in", self.vin, self.gnd)
        self.power_out = self.declare_interface("power_3v3", self.v33, self.gnd)
