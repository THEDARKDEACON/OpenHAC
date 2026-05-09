"""
Parametric audio component classes.

Amplifiers and microphones.
"""

from openhac.core.base import Component, Module
from openhac.stdlib.passives import _ParametricMixin, Capacitor
from openhac.core.net import Net


class AudioAmp(Module, _ParametricMixin):
    """Parametric audio amplifier.

    Args:
        power_watts: Target output power (W).
        v_cc: Operating voltage (V).
        package: SMD package code (e.g. "MSOP-8").
    """

    def __init__(self, power_watts: float = 1.0, v_cc: float = 5.0,
                 package: str = "MSOP-8", **kwargs):
        super().__init__(f"AudioAmp_{power_watts}W")

        from openhac.database.db_manager import DatabaseManager
        db = DatabaseManager()

        desc = f"AudioAmp(power={power_watts}W, v_cc={v_cc}V)"

        comp_data, was_fallback = db.parametric_search(
            "amplifiers_audio",
            power_watts=power_watts,
            v_cc=v_cc,
            package=package
        )

        if comp_data is None:
            # Common parts: LM4871, PAM8302
            generic_name = "LM4871"
            comp_data = db.get_component(generic_name)
            if comp_data is None:
                comp_data = Component._live_lookup(generic_name)
            if comp_data is None:
                self._raise_not_found(desc)
            was_fallback = True

        if was_fallback:
            self._warn_soft_fallback(desc, comp_data)

        self.ic = self.add(Component(comp_data["generic_name"], comp_data=comp_data, **kwargs))
        self.ic.lib = "Amplifier_Audio"

        self.vcc = Net("VCC")
        self.gnd = Net("GND")
        
        self.ic["VDD"] += self.vcc
        self.ic["GND"] += self.gnd

        self.power = self.declare_interface("power", self.vcc, self.gnd)


class Microphone(Module, _ParametricMixin):
    """Parametric Microphone module (MEMS).

    Args:
        type: "analog" or "pdm".
        package: Package code.
    """

    def __init__(self, type: str = "analog", package: str = None, **kwargs):
        super().__init__(f"MIC_{type.upper()}")

        from openhac.database.db_manager import DatabaseManager
        db = DatabaseManager()

        desc = f"Microphone(type={type})"

        comp_data, was_fallback = db.parametric_search(
            "microphones",
            mic_type="MEMS",
            output_type=type,
            package=package
        )

        if comp_data is None:
            generic_name = f"Microphone_MEMS_{type.upper()}"
            comp_data = db.get_component(generic_name)
            if comp_data is None:
                comp_data = Component._live_lookup(generic_name)
            if comp_data is None:
                self._raise_not_found(desc)
            was_fallback = True

        if was_fallback:
            self._warn_soft_fallback(desc, comp_data)

        self.mic = self.add(Component(comp_data["generic_name"], comp_data=comp_data, **kwargs))
        self.mic.lib = "Audio"

        self.vcc = Net("VCC")
        self.gnd = Net("GND")
        
        self.mic["VDD"] += self.vcc
        self.mic["GND"] += self.gnd

        self.power = self.declare_interface("power", self.vcc, self.gnd)
