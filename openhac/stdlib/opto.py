"""
Parametric optoelectronics component classes.

Photo-interrupters, LED Drivers, SSRs, and Infrared links.
"""

from openhac.core.base import Component, Module
from openhac.stdlib.passives import _ParametricMixin
from openhac.core.net import Net


class PhotoInterrupter(Module, _ParametricMixin):
    """Parametric slotted optical switch.

    Args:
        gap_mm: Width of the slot in mm.
        type: "transmissive" or "reflective".
    """

    def __init__(self, gap_mm: float = 5.0, type: str = "transmissive", **kwargs):
        super().__init__(f"OPTO_SLOT_{gap_mm}mm")

        db = Component.db

        desc = f"PhotoInterrupter(gap={gap_mm}mm, type={type})"

        comp_data, was_fallback = db.parametric_search(
            "opto_interrupters",
            gap=gap_mm,
            opto_type=type
        )

        if comp_data is None:
            # Common part: ITR9608-F
            generic_name = "ITR9608-F"
            comp_data = db.get_component(generic_name)
            if comp_data is None:
                comp_data = Component._live_lookup(generic_name)
            if comp_data is None:
                self._raise_not_found(desc)
            was_fallback = True

        if was_fallback:
            self._warn_soft_fallback(desc, comp_data)

        self.ic = self.add(Component(comp_data["generic_name"], comp_data=comp_data, **kwargs))
        self.ic.lib = "Sensor_Optical"


class LED_Driver(Module, _ParametricMixin):
    """Parametric Constant-Current LED Driver.

    Args:
        channels: Number of LED channels.
        current_ma: Maximum current per channel.
        interface: "PWM", "I2C", or "SPI".
    """

    def __init__(self, channels: int = 1, current_ma: float = 20.0,
                 interface: str = "PWM", **kwargs):
        super().__init__(f"LED_DRV_{channels}CH")

        db = Component.db

        desc = f"LED_Driver(channels={channels}, current={current_ma}mA)"

        comp_data, was_fallback = db.parametric_search(
            "led_drivers",
            channels=channels,
            current=current_ma,
            interface=interface
        )

        if comp_data is None:
            # Common part: AL8843 (Buck), PT4115
            generic_name = "PT4115"
            comp_data = db.get_component(generic_name)
            if comp_data is None:
                comp_data = Component._live_lookup(generic_name)
            if comp_data is None:
                self._raise_not_found(desc)
            was_fallback = True

        if was_fallback:
            self._warn_soft_fallback(desc, comp_data)

        self.ic = self.add(Component(comp_data["generic_name"], comp_data=comp_data, **kwargs))
        self.ic.lib = "Driver_LED"


class Opto_Relay(Module, _ParametricMixin):
    """Parametric Solid State Relay (SSR) / Opto-Isolated Switch.

    Args:
        load_v: Maximum load voltage (V).
        load_a: Maximum load current (A).
        type: "AC" or "DC".
    """

    def __init__(self, load_v: float = 60.0, load_a: float = 1.0,
                 type: str = "DC", **kwargs):
        super().__init__(f"SSR_{load_v}V_{load_a}A")

        db = Component.db

        desc = f"OptoRelay(v={load_v}V, i={load_a}A, type={type})"

        comp_data, was_fallback = db.parametric_search(
            "opto_relays",
            v_max=load_v,
            i_max=load_a,
            relay_type=type
        )

        if comp_data is None:
            # Common part: TLP172A
            generic_name = "TLP172A"
            comp_data = db.get_component(generic_name)
            if comp_data is None:
                comp_data = Component._live_lookup(generic_name)
            if comp_data is None:
                self._raise_not_found(desc)
            was_fallback = True

        if was_fallback:
            self._warn_soft_fallback(desc, comp_data)

        self.ic = self.add(Component(comp_data["generic_name"], comp_data=comp_data, **kwargs))
        self.ic.lib = "Relay_Opto"


class Infrared_TX_RX(Module, _ParametricMixin):
    """Parametric Infrared Transmitter/Receiver.

    Args:
        type: "TX" (Emitter), "RX" (Receiver/Demodulator), or "Transceiver".
        wavelength_nm: e.g., 940.
    """

    def __init__(self, type: str = "RX", wavelength_nm: int = 940, **kwargs):
        super().__init__(f"IR_{type.upper()}")

        db = Component.db

        desc = f"Infrared(type={type}, wavelength={wavelength_nm}nm)"

        comp_data, was_fallback = db.parametric_search(
            "opto_infrared",
            opto_type=type,
            wavelength=wavelength_nm
        )

        if comp_data is None:
            # Common part: TSOP38238 (RX), IR908-7C (TX)
            generic_name = "TSOP38238" if type == "RX" else "IR908-7C"
            comp_data = db.get_component(generic_name)
            if comp_data is None:
                comp_data = Component._live_lookup(generic_name)
            if comp_data is None:
                self._raise_not_found(desc)
            was_fallback = True

        if was_fallback:
            self._warn_soft_fallback(desc, comp_data)

        self.ic = self.add(Component(comp_data["generic_name"], comp_data=comp_data, **kwargs))
        self.ic.lib = "Interface_Optical"
