"""
Parametric clock and timing component classes.

Active oscillators, MEMS clocks, and VCOs.
"""

from openhac.core.base import Component, Module
from openhac.stdlib.passives import _ParametricMixin
from openhac.core.net import Net


class MEMS_Oscillator(Module, _ParametricMixin):
    """Parametric MEMS active oscillator.

    Args:
        freq_mhz: Output frequency in MHz.
        v_cc: Supply voltage.
    """

    def __init__(self, freq_mhz: float = 24.0, v_cc: float = 3.3, **kwargs):
        super().__init__(f"MEMS_{freq_mhz}MHz")

        from openhac.database.db_manager import DatabaseManager
        db = DatabaseManager()

        desc = f"MEMS_Oscillator(freq={freq_mhz}MHz, v_cc={v_cc}V)"

        comp_data, was_fallback = db.parametric_search(
            "clocks_mems",
            frequency=freq_mhz,
            voltage=v_cc
        )

        if comp_data is None:
            # Common part: SiT8008 or SIT1602
            generic_name = "SIT8008"
            comp_data = db.get_component(generic_name)
            if comp_data is None:
                comp_data = Component._live_lookup(generic_name)
            if comp_data is None:
                self._raise_not_found(desc)
            was_fallback = True

        if was_fallback:
            self._warn_soft_fallback(desc, comp_data)

        self.ic = self.add(Component(comp_data["generic_name"], comp_data=comp_data, **kwargs))
        self.ic.lib = "Device:Oscillator_Active"


class VCO(Module, _ParametricMixin):
    """Parametric Voltage Controlled Oscillator.

    Args:
        freq_min: Minimum frequency (MHz).
        freq_max: Maximum frequency (MHz).
    """

    def __init__(self, freq_min: float, freq_max: float, **kwargs):
        super().__init__(f"VCO_{freq_min}-{freq_max}MHz")

        from openhac.database.db_manager import DatabaseManager
        db = DatabaseManager()

        desc = f"VCO(freq_range={freq_min}-{freq_max}MHz)"

        comp_data, was_fallback = db.parametric_search(
            "clocks_vco",
            frequency_min=freq_min,
            frequency_max=freq_max
        )

        if comp_data is None:
            # Common part: POS-100 or similar
            generic_name = "POS-100"
            comp_data = db.get_component(generic_name)
            if comp_data is None:
                comp_data = Component._live_lookup(generic_name)
            if comp_data is None:
                self._raise_not_found(desc)
            was_fallback = True

        if was_fallback:
            self._warn_soft_fallback(desc, comp_data)

        self.ic = self.add(Component(comp_data["generic_name"], comp_data=comp_data, **kwargs))
        self.ic.lib = "Device:Oscillator_VCO"
