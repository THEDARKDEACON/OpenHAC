"""
Parametric logic component classes.

Level shifters, gates, and buffers.
"""

from openhac.core.base import Component, Module
from openhac.stdlib.passives import _ParametricMixin, Capacitor
from openhac.core.net import Net


class LevelShifter(Module, _ParametricMixin):
    """Parametric voltage level translator.

    Args:
        v_a: Voltage of domain A (V).
        v_b: Voltage of domain B (V).
        channels: Number of signal channels.
        bidirectional: If True, supports auto-direction sensing (e.g. TXB/TXS).
    """

    def __init__(self, v_a: float = 3.3, v_b: float = 5.0,
                 channels: int = 4, bidirectional: bool = True, **kwargs):
        super().__init__(f"LevelShifter_{channels}CH")

        from openhac.database.db_manager import DatabaseManager
        db = DatabaseManager()

        desc = f"LevelShifter(v_a={v_a}V, v_b={v_b}V, channels={channels})"

        comp_data, was_fallback = db.parametric_search(
            "logic_level_shifters",
            v_a=v_a,
            v_b=v_b,
            channels=channels,
            bidirectional=bidirectional
        )

        if comp_data is None:
            # Common parts: TXB0104 (4-ch), TXB0108 (8-ch)
            generic_name = f"TXB010{channels}" if channels in [4, 8] else "TXB0104"
            comp_data = db.get_component(generic_name)
            if comp_data is None:
                comp_data = Component._live_lookup(generic_name)
            if comp_data is None:
                self._raise_not_found(desc)
            was_fallback = True

        if was_fallback:
            self._warn_soft_fallback(desc, comp_data)

        self.ic = self.add(Component(comp_data["generic_name"], comp_data=comp_data, **kwargs))
        
        # Two bypass caps for the two voltage domains
        self.c_a = self.add(Capacitor(value="100nF", package="0402"))
        self.c_b = self.add(Capacitor(value="100nF", package="0402"))

        self.va = Net("VA")
        self.vb = Net("VB")
        self.gnd = Net("GND")

        self.ic["VCCA"] += self.va, self.c_a.p1
        self.ic["VCCB"] += self.vb, self.c_b.p1
        self.ic["GND"] += self.gnd, self.c_a.p2, self.c_b.p2

        # Interfaces
        self.side_a = self.declare_interface("side_a", self.va, self.gnd)
        self.side_b = self.declare_interface("side_b", self.vb, self.gnd)
