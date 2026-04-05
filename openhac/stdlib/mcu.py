"""
Parametric MCU module.

Supports family-based lookup (e.g. MCU(family="STM32F407")) and
direct MPN lookup (e.g. MCU(mpn="ESP32-WROOM-32E")).
"""

from openhac.core.base import Component, Module
from openhac.stdlib.passives import _ParametricMixin
from skidl import Net


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

        from openhac.database.db_manager import DatabaseManager
        db = DatabaseManager()

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


# Backward-compatible pre-wired ESP32 module
class ESP32_WROOM(Module):
    def __init__(self):
        super().__init__()
        self.mcu = self.add(Component("ESP32_WROOM"))

        self.vcc = Net("3V3_VCC")
        self.gnd = Net("GND")

        self.mcu["2"] += self.vcc
        self.mcu["1"] += self.gnd
        self.mcu["15"] += self.gnd
        self.mcu["38"] += self.gnd

        self.power = self.declare_interface("power", self.vcc, self.gnd)
