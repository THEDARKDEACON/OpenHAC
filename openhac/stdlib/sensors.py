"""
Parametric sensor modules.

IMU and other sensor classes that resolve to real components
from the database using parametric search.
"""

from openhac.core.base import Component, Module
from openhac.stdlib.passives import _ParametricMixin
from skidl import Net


class IMU(Module, _ParametricMixin):
    """Parametric Inertial Measurement Unit.

    Args:
        mpn: Exact manufacturer part number (e.g. "ICM-42688-P").
        axes: Number of axes (e.g. 6 for 6-DOF).
        package: Package code (optional).
    """

    def __init__(self, mpn: str = None, axes: int = None,
                 package: str = None, **kwargs):
        name = f"IMU_{mpn or 'Generic'}"
        super().__init__(name)

        from openhac.database.db_manager import DatabaseManager
        db = DatabaseManager()

        desc = f"IMU(" + \
               (f"mpn={mpn}" if mpn else "") + \
               (f", axes={axes}" if axes else "") + \
               (f", package={package}" if package else "") + ")"

        comp_data = None
        was_fallback = False

        # Try direct MPN lookup first
        if mpn:
            comp_data, was_fallback = db.parametric_search(
                "accelerometers",
                mpn=mpn,
                package=package,
            )

        if comp_data is None:
            # Try by axes count
            comp_data, was_fallback = db.parametric_search(
                "accelerometers",
                package=package,
            )

        if comp_data is None:
            # Live lookup fallback
            lookup_term = mpn or "IMU_6DOF"
            comp_data = Component._live_lookup(lookup_term)
            if comp_data:
                was_fallback = True

        if comp_data is None:
            self._raise_not_found(desc)

        if was_fallback:
            self._warn_soft_fallback(desc, comp_data)

        self._comp = self.add(Component(comp_data["generic_name"], **kwargs))

        # Standard IMU interface nets
        self.vdd = Net(f"{name}_VDD")
        self.gnd = Net(f"{name}_GND")

        self._comp["VDD"] += self.vdd
        self._comp["GND"] += self.gnd

        self.max_current_draw_ma = 10.0

        self.power = self.declare_interface("power", self.vdd, self.gnd)
