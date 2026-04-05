"""
Parametric power component classes.

VoltageRegulator, Connector, and pre-wired power modules.
"""

from __future__ import annotations

import warnings as _warnings


def buck_input_current_ma(
    output_current_ma: float,
    v_out_v: float,
    v_in_v: float,
    efficiency: float,
) -> float:
    """Ideal DC–DC input current (mA) from output load, voltages, and efficiency (PWR-002).

    Use the result in ``Module.extra_input_draw_by_rail_ma`` on the *input* rail name
    when modeling a buck (or similar) so per-rail ERC includes converter losses.

    ``P_in ≈ V_out × I_out / (V_in × η)``  →  ``I_in_mA = I_out_mA × V_out / V_in / η``.
    """
    if v_in_v <= 0:
        raise ValueError("buck_input_current_ma: v_in_v must be > 0")
    if efficiency <= 0:
        raise ValueError("buck_input_current_ma: efficiency must be > 0")
    return float(output_current_ma) * (float(v_out_v) / float(v_in_v)) / float(efficiency)

from openhac.core.base import Component, Module
from openhac.stdlib.passives import _ParametricMixin
from skidl import Net


class VoltageRegulator(Module, _ParametricMixin):
    """Parametric voltage regulator.

    Args:
        v_out: Output voltage in volts (e.g. 3.3, 5.0).
        package: Package code (e.g. "SOT-223", "TO-252").
        min_current: Minimum output current in amps.
    """

    def __init__(self, v_out: float, package: str = None,
                 min_current: float = None, **kwargs):
        v_str = str(int(v_out)) if v_out == int(v_out) else str(round(v_out, 1))
        name = f"LDO_{v_str}V"
        if package:
            name += f"_{package}"
        super().__init__(name)

        from openhac.database.db_manager import DatabaseManager
        db = DatabaseManager()

        desc = f"VoltageRegulator(v_out={v_out}" + \
               (f", package={package}" if package else "") + \
               (f", min_current={min_current}A" if min_current else "") + ")"

        comp_data, was_fallback = db.parametric_search(
            "voltage_regulators",
            v_out=v_out,
            package=package,
        )

        if comp_data is None:
            # Try generic name fallback
            generic_name = f"LDO_{v_str}V"
            if package:
                generic_name += f"_{package}"
            comp_data = db.get_component(generic_name)
            if comp_data is None:
                # Try broader: "LDO_5V" style
                comp_data = db.get_component(f"LDO_{v_str}V")
            if comp_data is None:
                comp_data = Component._live_lookup(generic_name)
            if comp_data is None:
                self._raise_not_found(desc)
            was_fallback = True

        if was_fallback:
            self._warn_soft_fallback(desc, comp_data)

        self._comp = self.add(Component(comp_data["generic_name"], comp_data=comp_data, **kwargs))

        # Wire standard regulator pins
        self.vin = Net(f"{name}_VIN")
        self.vout = Net(f"{name}_VOUT")
        self.gnd = Net(f"{name}_GND")

        self._comp["1"] += self.gnd
        self._comp["2"] += self.vout
        self._comp["3"] += self.vin

        self.source_current_max_ma = (min_current or 1.0) * 1000

        self.v_in = self.declare_interface("v_in", self.vin, self.gnd)
        self.v_out_iface = self.declare_interface("v_out", self.vout, self.gnd)


class Connector(Module, _ParametricMixin):
    """Parametric connector.

    Args:
        type: Connector family, e.g. "XT60", "USB_C", "JST_PH".
        pin_count: Number of pins.
        gender: "Male" or "Female" (optional).
    """

    def __init__(self, type: str, pin_count: int = 2, gender: str = None, **kwargs):
        name = f"Conn_{type}_{pin_count}P"
        if gender:
            name += f"_{gender}"
        super().__init__(name)

        from openhac.database.db_manager import DatabaseManager
        db = DatabaseManager()

        desc = f"Connector(type={type}, pin_count={pin_count}" + \
               (f", gender={gender}" if gender else "") + ")"

        comp_data, was_fallback = db.parametric_search(
            "connectors",
            connector_type=type,
            pin_count=pin_count,
        )

        if comp_data is None:
            # Try known generic names
            for try_name in [f"{type}_Vertical", f"{type}_{gender}", type]:
                comp_data = db.get_component(try_name)
                if comp_data:
                    was_fallback = True
                    break

        if comp_data is None:
            comp_data = Component._live_lookup(type)
            if comp_data:
                was_fallback = True

        if comp_data is None:
            # Final fallback: Synthetic component
            _warnings.warn(f"Warning: Component for {desc} not found. Using synthetic fallback.")
            comp_data = {
                "generic_name": f"Conn_Synthetic_{pin_count}P",
                "kicad_symbol": "Connector:Conn_01x02_Pin", # placeholder
                "kicad_footprint": "Connector_JST:JST_PH_S2B-PH-K_1x02_P2.00mm_Vertical",
                "manufacturer": "N/A",
                "mpn": "N/A",
                "supplier_sku": "N/A",
            }
            was_fallback = True

        if was_fallback:
            self._warn_soft_fallback(desc, comp_data)

        self._comp = self.add(Component(comp_data["generic_name"], comp_data=comp_data, **kwargs))

        # Wire pins as generic signals
        self._pins = []
        for i in range(1, pin_count + 1):
            n = Net(f"{name}_P{i}")
            self._comp[str(i)] += n
            self._pins.append(n)

        # Expose all pins as interface
        self.pins_iface = self.declare_interface("pins", *self._pins)


# -----------------------------------------------------------------------
# Pre-wired convenience modules (backward compatible)
# -----------------------------------------------------------------------


class XT60_Input(Module):
    """Pre-wired XT60 power input module."""

    def __init__(self):
        super().__init__()
        self.connector = self.add(Component("XT60_Vertical"))
        self.vcc = Net("VIN")
        self.gnd = Net("GND")

        self.connector["1"] += self.vcc
        self.connector["2"] += self.gnd

        self.v_out = self.declare_interface("v_out", self.vcc, self.gnd)


class LDO_5V(Module):
    """Pre-wired 5V LDO module (backward compatible)."""

    def __init__(self):
        super().__init__()
        self.ldo = self.add(Component("LDO_5V"))
        self.c_in = self.add(Component("C_100nF_0603"))
        self.c_out = self.add(Component("C_100nF_0603"))

        self.vin = Net("LDO_VIN")
        self.vout = Net("5V")
        self.gnd = Net("GND")

        self.ldo["1"] += self.gnd, self.c_in["2"], self.c_out["2"]
        self.ldo["3"] += self.vin, self.c_in["1"]
        self.ldo["2"] += self.vout, self.c_out["1"]
        self.ldo["4"] += self.vout

        self.v_in = self.declare_interface("v_in", self.vin, self.gnd)
        self.v_out = self.declare_interface("v_out", self.vout, self.gnd)
