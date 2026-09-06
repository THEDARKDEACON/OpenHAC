"""
Parametric electromechanical component classes.

Relays, Buzzers, and Motor Drivers.
"""

from openhac.core.base import Component, Module
from openhac.stdlib.passives import _ParametricMixin
from openhac.core.net import Net


class Relay(Module, _ParametricMixin):
    """Parametric mechanical relay.

    Includes an automatic flyback diode across the coil.

    Args:
        coil_v: Coil voltage (V).
        contact_a: Contact current rating (A).
        configuration: "SPDT", "DPDT", etc.
    """

    def __init__(self, coil_v: float = 5.0, contact_a: float = 10.0,
                 configuration: str = "SPDT", **kwargs):
        super().__init__(f"RELAY_{configuration}")

        from openhac.stdlib.discretes import Diode
        db = Component.db

        desc = f"Relay(coil={coil_v}V, contact={contact_a}A)"

        comp_data, was_fallback = db.parametric_search(
            "relays",
            coil_voltage=coil_v,
            contact_current=contact_a,
            configuration=configuration
        )

        if comp_data is None:
            # Common part: SRD-05VDC-SL-C
            generic_name = f"Relay_{configuration}_{coil_v}V"
            comp_data = db.get_component(generic_name)
            if comp_data is None:
                comp_data = Component._live_lookup(generic_name)
            if comp_data is None:
                self._raise_not_found(desc)
            was_fallback = True

        if was_fallback:
            self._warn_soft_fallback(desc, comp_data)

        self.relay = self.add(Component(comp_data["generic_name"], comp_data=comp_data, **kwargs))
        self.relay.lib = "Relay"

        # Automatic Flyback Diode
        self.diode = self.add(Diode(type="rectifier", v_r=coil_v*2, i_f=1.0))

        # Coil Nets
        self.coil_pos = Net("COIL_POS")
        self.coil_neg = Net("COIL_NEG")
        
        self.relay["COIL_1"] += self.coil_pos
        self.relay["COIL_1"] += self.diode.cathode
        self.relay["COIL_2"] += self.coil_neg
        self.relay["COIL_2"] += self.diode.anode

        self.coil = self.declare_interface("coil", self.coil_pos, self.coil_neg)


class Buzzer(Module, _ParametricMixin):
    """Parametric Piezo or Magnetic Buzzer.

    Args:
        type: "piezo" or "magnetic".
        v_rated: Rated voltage (V).
    """

    def __init__(self, type: str = "piezo", v_rated: float = 5.0, **kwargs):
        super().__init__(f"BUZZER_{type.upper()}")

        db = Component.db

        desc = f"Buzzer(type={type}, voltage={v_rated}V)"

        comp_data, was_fallback = db.parametric_search(
            "buzzers",
            buzzer_type=type,
            v_rated=v_rated
        )

        if comp_data is None:
            generic_name = f"Buzzer_{type.upper()}"
            comp_data = db.get_component(generic_name)
            if comp_data is None:
                comp_data = Component._live_lookup(generic_name)
            if comp_data is None:
                self._raise_not_found(desc)
            was_fallback = True

        if was_fallback:
            self._warn_soft_fallback(desc, comp_data)

        self.buzzer = self.add(Component(comp_data["generic_name"], comp_data=comp_data, **kwargs))
        self.buzzer.lib = "Device"

        self.p1 = Net("P1")
        self.p2 = Net("P2")
        self.buzzer["1"] += self.p1
        self.buzzer["2"] += self.p2


class MotorDriver(Module, _ParametricMixin):
    """Parametric H-Bridge Motor Driver.

    Args:
        v_motor: Maximum motor supply voltage (V).
        i_peak: Peak output current (A).
        channels: Number of bridges (1 or 2).
    """

    def __init__(self, v_motor: float = 12.0, i_peak: float = 2.0,
                 channels: int = 2, **kwargs):
        super().__init__(f"Driver_{channels}CH")

        db = Component.db

        desc = f"MotorDriver(v_motor={v_motor}V, i_peak={i_peak}A)"

        comp_data, was_fallback = db.parametric_search(
            "motor_drivers",
            v_max=v_motor,
            i_peak=i_peak,
            channels=channels
        )

        if comp_data is None:
            # Common parts: L298, DRV8833
            generic_name = "DRV8833"
            comp_data = db.get_component(generic_name)
            if comp_data is None:
                comp_data = Component._live_lookup(generic_name)
            if comp_data is None:
                self._raise_not_found(desc)
            was_fallback = True

        if was_fallback:
            self._warn_soft_fallback(desc, comp_data)

        self.ic = self.add(Component(comp_data["generic_name"], comp_data=comp_data, **kwargs))
        self.ic.lib = "Driver_Motor"
