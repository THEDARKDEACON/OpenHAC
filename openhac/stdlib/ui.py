"""
Parametric UI component classes.

LEDs (with auto-resistor calculation) and Buttons.
"""

from openhac.core.base import Component, Module
from openhac.stdlib.passives import _ParametricMixin, Resistor
from openhac.core.net import Net


class IndicatorLED(Module, _ParametricMixin):
    """Parametric LED with integrated current-limiting resistor.

    Args:
        color: LED color, e.g. "red", "green", "blue", "white".
        current_ma: Desired forward current in milliamps.
        v_supply: Voltage of the driving rail (V) for resistor calculation.
        package: LED SMD package (e.g. "0603", "0805").
    """

    def __init__(self, color: str = "green", current_ma: float = 10.0,
                 v_supply: float = 3.3, package: str = "0603", **kwargs):
        super().__init__(f"LED_{color.upper()}")

        from openhac.database.db_manager import DatabaseManager
        db = DatabaseManager()

        desc = f"IndicatorLED(color={color}, current={current_ma}mA, v_supply={v_supply}V)"

        comp_data, was_fallback = db.parametric_search(
            "leds",
            color=color,
            package=package
        )

        if comp_data is None:
            generic_name = f"LED_{color.upper()}_{package}"
            comp_data = db.get_component(generic_name)
            if comp_data is None:
                comp_data = Component._live_lookup(generic_name)
            if comp_data is None:
                self._raise_not_found(desc)
            was_fallback = True

        if was_fallback:
            self._warn_soft_fallback(desc, comp_data)

        self.led = self.add(Component(comp_data["generic_name"], comp_data=comp_data, **kwargs))

        # Calculate resistor value
        # Vf (Forward Voltage) is ideally in comp_data. Fallback to common values.
        v_f = float(comp_data.get("v_f") or comp_data.get("forward_voltage") or 2.0)
        
        if v_supply <= v_f:
            # Supply too low, warning
            import logging
            logging.getLogger("openhac").warning(
                f"IndicatorLED {color}: Supply voltage {v_supply}V is <= Forward Voltage {v_f}V. "
                "LED may not illuminate."
            )
            r_val_ohms = 10.0 # fallback
        else:
            r_val_ohms = (v_supply - v_f) / (current_ma / 1000.0)

        # Pick nearest E12 value (Resistor class handles parametric search for closest match)
        r_str = f"{int(r_val_ohms)}R" if r_val_ohms < 1000 else f"{round(r_val_ohms/1000, 1)}k"
        self.res = self.add(Resistor(value=r_str, package=package))

        # Internal wiring: [Supply] -> [Resistor] -> [LED Anode] | [LED Cathode] -> [GND]
        self.vin = Net("VIN")
        self.gnd = Net("GND")
        self._inter = Net("LED_ANODE")

        self.res.p1 += self.vin
        self.res.p2 += self._inter
        self.led["1"] += self._inter # Anode
        self.led["2"] += self.gnd    # Cathode

        self.power = self.declare_interface("power", self.vin, self.gnd)


class Button(Module, _ParametricMixin):
    """Parametric tactile switch.

    Args:
        type: "tactile", "pushbutton".
        package: Package code (e.g. "SMD_3x6mm").
    """

    def __init__(self, type: str = "tactile", package: str = None, **kwargs):
        super().__init__(f"BTN_{type.upper()}")

        from openhac.database.db_manager import DatabaseManager
        db = DatabaseManager()

        desc = f"Button(type={type})"

        comp_data, was_fallback = db.parametric_search(
            "switches",
            switch_type=type,
            package=package
        )

        if comp_data is None:
            generic_name = f"SW_{type.upper()}"
            comp_data = db.get_component(generic_name)
            if comp_data is None:
                comp_data = Component._live_lookup(generic_name)
            if comp_data is None:
                self._raise_not_found(desc)
            was_fallback = True

        if was_fallback:
            self._warn_soft_fallback(desc, comp_data)

        self._comp = self.add(Component(comp_data["generic_name"], comp_data=comp_data, **kwargs))

        # Standard 2-pin switch
        self.p1 = Net("P1")
        self.p2 = Net("P2")
        self._comp["1"] += self.p1
        self._comp["2"] += self.p2
