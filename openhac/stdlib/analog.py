"""
Parametric analog component classes.

OpAmps, ADCs, and DACs.
"""

from openhac.core.base import Component, Module
from openhac.stdlib.passives import _ParametricMixin, Capacitor
from openhac.core.net import Net


class OpAmp(Module, _ParametricMixin):
    """Parametric Operational Amplifier.

    Args:
        channels: Number of amps in package (1, 2, 4).
        gbp_mhz: Minimum Gain Bandwidth Product (MHz).
        v_rail: Minimum supply voltage (V).
        package: SMD package code (e.g. "SOT-23-5", "SOIC-8").
    """

    def __init__(self, channels: int = 1, gbp_mhz: float = 1.0,
                 v_rail: float = 5.0, package: str = "SOT-23-5", **kwargs):
        super().__init__(f"OPA_{channels}CH_{gbp_mhz}MHz")

        from openhac.database.db_manager import DatabaseManager
        db = DatabaseManager()

        desc = f"OpAmp(channels={channels}, gbp={gbp_mhz}MHz, v_rail={v_rail}V)"

        comp_data, was_fallback = db.parametric_search(
            "amplifiers_operational",
            channels=channels,
            gbp=gbp_mhz,
            v_rail=v_rail,
            package=package
        )

        if comp_data is None:
            # Common part: LM358 (dual), LM324 (quad)
            generic_name = f"OpAmp_{channels}CH"
            comp_data = db.get_component(generic_name)
            if comp_data is None:
                comp_data = Component._live_lookup(generic_name)
            if comp_data is None:
                self._raise_not_found(desc)
            was_fallback = True

        if was_fallback:
            self._warn_soft_fallback(desc, comp_data)

        self.ic = self.add(Component(comp_data["generic_name"], comp_data=comp_data, **kwargs))
        self.ic.lib = "Amplifier_Operational"

        self.vcc = Net("VCC")
        self.vee = Net("VEE") # GND or negative rail
        
        self.ic["V+"] += self.vcc
        self.ic["V-"] += self.vee

        self.power = self.declare_interface("power", self.vcc, self.vee)


class ADC(Module, _ParametricMixin):
    """Parametric Analog to Digital Converter.

    Args:
        resolution: Bits (8, 10, 12, 16, 24).
        sampling_rate: Samples per second (SPS).
        channels: Number of analog input channels.
        interface: "I2C" or "SPI".
    """

    def __init__(self, resolution: int = 12, sampling_rate: float = 1000,
                 channels: int = 1, interface: str = "I2C", **kwargs):
        super().__init__(f"ADC_{resolution}BIT")

        from openhac.database.db_manager import DatabaseManager
        db = DatabaseManager()

        desc = f"ADC(resolution={resolution}, rate={sampling_rate}, channels={channels})"

        comp_data, was_fallback = db.parametric_search(
            "analog_to_digital_converters",
            resolution=resolution,
            sampling_rate=sampling_rate,
            channels=channels,
            interface=interface
        )

        if comp_data is None:
            # Common parts: ADS1115 (16-bit I2C), MCP3008 (10-bit SPI)
            generic_name = "ADS1115" if interface == "I2C" else "MCP3008"
            comp_data = db.get_component(generic_name)
            if comp_data is None:
                comp_data = Component._live_lookup(generic_name)
            if comp_data is None:
                self._raise_not_found(desc)
            was_fallback = True

        if was_fallback:
            self._warn_soft_fallback(desc, comp_data)

        self.ic = self.add(Component(comp_data["generic_name"], comp_data=comp_data, **kwargs))
        self.ic.lib = "Analog_ADC"

        self.vcc = Net("VCC")
        self.gnd = Net("GND")
        
        self.ic["VDD"] += self.vcc
        self.ic["GND"] += self.gnd

        self.power = self.declare_interface("power", self.vcc, self.gnd)


class InstrumentationAmp(Module, _ParametricMixin):
    """Parametric Instrumentation Amplifier.

    Args:
        v_offset: Maximum input offset voltage (uV).
        cmrr: Minimum Common Mode Rejection Ratio (dB).
        gain_fixed: If True, searches for fixed-gain amps.
    """

    def __init__(self, v_offset: float = 100, cmrr: float = 100, **kwargs):
        super().__init__("InstAmp")

        from openhac.database.db_manager import DatabaseManager
        db = DatabaseManager()

        desc = f"InstrumentationAmp(v_offset={v_offset}uV, cmrr={cmrr}dB)"

        comp_data, was_fallback = db.parametric_search(
            "amplifiers_instrumentation",
            v_offset=v_offset,
            cmrr=cmrr
        )

        if comp_data is None:
            generic_name = "AD8221" # common example
            comp_data = db.get_component(generic_name)
            if comp_data is None:
                comp_data = Component._live_lookup(generic_name)
            if comp_data is None:
                self._raise_not_found(desc)
            was_fallback = True

        if was_fallback:
            self._warn_soft_fallback(desc, comp_data)

        self.ic = self.add(Component(comp_data["generic_name"], comp_data=comp_data, **kwargs))
        self.ic.lib = "Amplifier_Instrumentation"


class AnalogSwitch(Module, _ParametricMixin):
    """Parametric Analog Switch / Multiplexer.

    Args:
        channels: Number of channels (e.g. 8 for 8:1 MUX).
        configuration: "SPST", "SPDT", "MUX".
    """

    def __init__(self, channels: int = 1, configuration: str = "SPDT", **kwargs):
        super().__init__(f"AnalogSwitch_{configuration}")

        from openhac.database.db_manager import DatabaseManager
        db = DatabaseManager()

        desc = f"AnalogSwitch(channels={channels}, config={configuration})"

        comp_data, was_fallback = db.parametric_search(
            "analog_switches_multiplexers",
            channels=channels,
            configuration=configuration
        )

        if comp_data is None:
            generic_name = "74HC4051" if channels > 1 else "TS5A3159"
            comp_data = db.get_component(generic_name)
            if comp_data is None:
                comp_data = Component._live_lookup(generic_name)
            if comp_data is None:
                self._raise_not_found(desc)
            was_fallback = True

        if was_fallback:
            self._warn_soft_fallback(desc, comp_data)

        self.ic = self.add(Component(comp_data["generic_name"], comp_data=comp_data, **kwargs))
        self.ic.lib = "Analog_Switch"


class Comparator(Module, _ParametricMixin):
    """Parametric Analog Comparator.

    Args:
        channels: Number of comparators in package.
        response_time_ns: Maximum response time (ns).
    """

    def __init__(self, channels: int = 1, response_time_ns: float = 100, **kwargs):
        super().__init__(f"Comparator_{channels}CH")

        from openhac.database.db_manager import DatabaseManager
        db = DatabaseManager()

        desc = f"Comparator(channels={channels}, speed={response_time_ns}ns)"

        comp_data, was_fallback = db.parametric_search(
            "analog_comparators",
            channels=channels,
            response_time_ns=response_time_ns
        )

        if comp_data is None:
            generic_name = "LM393" if channels == 2 else "TLV3201"
            comp_data = db.get_component(generic_name)
            if comp_data is None:
                comp_data = Component._live_lookup(generic_name)
            if comp_data is None:
                self._raise_not_found(desc)
            was_fallback = True

        if was_fallback:
            self._warn_soft_fallback(desc, comp_data)

        self.ic = self.add(Component(comp_data["generic_name"], comp_data=comp_data, **kwargs))
        self.ic.lib = "Analog_Comparator"


class VoltageToFrequency(Module, _ParametricMixin):
    """Parametric Voltage-to-Frequency Converter."""

    def __init__(self, **kwargs):
        super().__init__("VFC")
