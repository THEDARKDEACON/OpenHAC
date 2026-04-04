"""
Parametric passive component classes.

These classes accept electrical intent (value, package, tolerance, etc.)
and autonomously resolve to real components from the database using the
parametric query engine.  If an exact match isn't found, the system
over-specs safely and emits a visible warning.
"""

import warnings as _warnings

from openhac.core.base import Component, Module


class _ParametricMixin:
    """Shared logic for parametric component resolution with soft fallback."""

    @staticmethod
    def _warn_soft_fallback(requested_desc: str, matched: dict):
        sku = matched.get("supplier_sku", "?")
        name = matched.get("generic_name", "?")
        msg = (
            f"\033[93m[WARNING]\033[0m Exact match not found for {requested_desc}. "
            f"Auto-substituting {name} (LCSC: {sku}) to maintain safety margins."
        )
        print(msg)
        _warnings.warn(msg, UserWarning, stacklevel=4)

    @staticmethod
    def _raise_not_found(requested_desc: str):
        raise ValueError(
            f"Component not found: {requested_desc}. "
            f"Run sync_catalog() to refresh the component database, or check parameters."
        )


class Resistor(Module, _ParametricMixin):
    """Parametric resistor.

    Args:
        value: Resistance string, e.g. "10k", "4k7", "100R".
        package: SMD package code, e.g. "0805", "0603".
        tolerance: e.g. "1%", "5%".
        power_watts: Minimum power rating in watts.
    """

    def __init__(self, value: str = "10k", package: str = "0805",
                 tolerance: str = None, power_watts: float = None, **kwargs):
        super().__init__(f"R_{value}_{package}")

        from openhac.database.db_manager import DatabaseManager
        db = DatabaseManager()

        desc = f"Resistor({value}, {package}" + \
               (f", {tolerance}" if tolerance else "") + \
               (f", {power_watts}W" if power_watts else "") + ")"

        comp_data, was_fallback = db.parametric_search(
            "resistors",
            value=value,
            package=package,
            tolerance=tolerance,
            power_watts=power_watts,
        )

        if comp_data is None:
            # Fall back to generic_name lookup via the original Component path
            generic_name = f"R_{value}_{package}"
            comp_data = db.get_component(generic_name)
            if comp_data is None:
                comp_data = Component._live_lookup(generic_name)
            if comp_data is None:
                self._raise_not_found(desc)
            was_fallback = True

        if was_fallback:
            self._warn_soft_fallback(desc, comp_data)

        self._comp = self.add(Component(comp_data["generic_name"], **kwargs))
        self.max_current_draw_ma = 0.0


class Capacitor(Module, _ParametricMixin):
    """Parametric capacitor.

    Args:
        value: Capacitance string, e.g. "100nF", "10uF", "470uF".
        package: SMD package code, e.g. "0805", "0603".
        voltage_rating: Minimum voltage rating (V). Over-specs if exact not available.
    """

    def __init__(self, value: str = "100nF", package: str = "0603",
                 voltage_rating: float = None, **kwargs):
        super().__init__(f"C_{value}_{package}")

        from openhac.database.db_manager import DatabaseManager
        db = DatabaseManager()

        desc = f"Capacitor({value}" + \
               (f", {package}" if package else "") + \
               (f", {voltage_rating}V" if voltage_rating else "") + ")"

        comp_data, was_fallback = db.parametric_search(
            "capacitors",
            value=value,
            package=package,
            voltage_rating=voltage_rating,
        )

        if comp_data is None:
            generic_name = f"C_{value}_{package}"
            comp_data = db.get_component(generic_name)
            if comp_data is None:
                comp_data = Component._live_lookup(generic_name)
            if comp_data is None:
                self._raise_not_found(desc)
            was_fallback = True

        if was_fallback:
            self._warn_soft_fallback(desc, comp_data)

        self._comp = self.add(Component(comp_data["generic_name"], **kwargs))
        self.max_current_draw_ma = 0.0
