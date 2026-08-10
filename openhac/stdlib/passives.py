"""
Parametric passive component classes.

These classes accept electrical intent (value, package, tolerance, etc.)
and autonomously resolve to real components from the database using the
parametric query engine.  If an exact match isn't found, the system
over-specs safely and emits a visible warning.
"""

import logging
import warnings as _warnings

from openhac.core.base import Component, Module

logger = logging.getLogger("openhac.stdlib")


class _ParametricMixin:
    """Shared logic for parametric component resolution with soft fallback."""

    @staticmethod
    def _warn_soft_fallback(requested_desc: str, matched: dict):
        sku = matched.get("supplier_sku", "?")
        name = matched.get("generic_name", "?")
        msg = (
            f"Exact match not found for {requested_desc}. "
            f"Auto-substituting {name} (LCSC: {sku}) to maintain safety margins."
        )
        logger.warning(msg)

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

        self._comp = self.add(Component(comp_data["generic_name"], comp_data=comp_data, **kwargs))
        self._comp.lib = "Device"
        if "kicad_symbol" not in self._comp.fields:
            self._comp.fields["kicad_symbol"] = "Device:R"
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

        self._comp = self.add(Component(comp_data["generic_name"], comp_data=comp_data, **kwargs))
        self._comp.lib = "Device"
        if "kicad_symbol" not in self._comp.fields:
            self._comp.fields["kicad_symbol"] = "Device:C"
        self.max_current_draw_ma = 0.0


class Inductor(Module, _ParametricMixin):
    """Parametric inductor."""

    def __init__(self, value: str = "10uH", package: str = "0603",
                 current_max_ma: float = None, **kwargs):
        super().__init__(f"L_{value}")
        from openhac.database.db_manager import DatabaseManager
        db = DatabaseManager()
        comp_data, _ = db.parametric_search("inductors", value=value, package=package)
        if not comp_data:
            comp_data = Component._live_lookup(f"L_{value}_{package}")
        self._comp = self.add(Component(comp_data["generic_name"], comp_data=comp_data, **kwargs))
        self._comp.lib = "Device"
        if "kicad_symbol" not in self._comp.fields:
            self._comp.fields["kicad_symbol"] = "Device:L"


class ResistorArray(Module, _ParametricMixin):
    """Parametric Resistor Array (e.g. 4x 10k).

    Args:
        value: Resistance value, e.g. "10k".
        count: Number of resistors in pack (2, 4, 8).
        package: Package code (e.g. "0603x4").
    """

    def __init__(self, value: str = "10k", count: int = 4,
                 package: str = "0603x4", **kwargs):
        super().__init__(f"RA_{count}x{value}")

        from openhac.database.db_manager import DatabaseManager
        db = DatabaseManager()

        desc = f"ResistorArray(value={value}, count={count})"

        comp_data, was_fallback = db.parametric_search(
            "resistor_arrays",
            value=value,
            count=count,
            package=package
        )

        if comp_data is None:
            generic_name = f"RA_{value}_{package}"
            comp_data = db.get_component(generic_name)
            if comp_data is None:
                comp_data = Component._live_lookup(generic_name)
            if comp_data is None:
                self._raise_not_found(desc)
            was_fallback = True

        if was_fallback:
            self._warn_soft_fallback(desc, comp_data)

        self.ic = self.add(Component(comp_data["generic_name"], comp_data=comp_data, **kwargs))
        self.ic.lib = "Device"


class FerriteBead(Module, _ParametricMixin):
    """Parametric Ferrite Bead for noise suppression.

    Args:
        impedance_at_100mhz: Impedance in ohms (e.g. 600).
        i_max: Maximum DC current (A).
        package: SMD package code (e.g. "0603").
    """

    def __init__(self, impedance_at_100mhz: float = 600, i_max: float = 0.5,
                 package: str = "0603", **kwargs):
        super().__init__(f"FB_{impedance_at_100mhz}R")

        from openhac.database.db_manager import DatabaseManager
        db = DatabaseManager()

        desc = f"FerriteBead(z={impedance_at_100mhz}R, i_max={i_max}A)"

        comp_data, was_fallback = db.parametric_search(
            "ferrite_beads",
            impedance=impedance_at_100mhz,
            i_max=i_max,
            package=package
        )

        if comp_data is None:
            generic_name = f"FB_{impedance_at_100mhz}R_{package}"
            comp_data = db.get_component(generic_name)
            if comp_data is None:
                comp_data = Component._live_lookup(generic_name)
            if comp_data is None:
                self._raise_not_found(desc)
            was_fallback = True

        if was_fallback:
            self._warn_soft_fallback(desc, comp_data)

        self.ic = self.add(Component(comp_data["generic_name"], comp_data=comp_data, **kwargs))
        self.ic.lib = "Device"

        self.p1 = Net("P1")
        self.p2 = Net("P2")
        self.ic["1"] += self.p1
        self.ic["2"] += self.p2


class Transformer(Module, _ParametricMixin):
    """Parametric Transformer."""

    def __init__(self, type: str = "signal", **kwargs):
        super().__init__(f"XFMR_{type.upper()}")
        from openhac.database.db_manager import DatabaseManager
        db = DatabaseManager()
        comp_data = db.get_component("Transformer_Signal")
        self.ic = self.add(Component(comp_data["generic_name"], comp_data=comp_data, **kwargs))
        self.ic.lib = "Device"
