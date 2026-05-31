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
from openhac.core.net import Net


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


    def __init__(self):
        super().__init__("XT60_Input")
        self.connector = self.add(Component("XT60_Vertical"))
        self.vcc = Net("VIN")
        self.gnd = Net("GND")

        self.connector["1"] += self.vcc
        self.connector["2"] += self.gnd

        self.v_out = self.declare_interface("v_out", self.vcc, self.gnd)


class USB_C_Input(Module):
    """USB-C Power Input with 5.1k CC pull-downs for 5V negotiation."""
    def __init__(self):
        super().__init__("USB_C_Input")
        self.conn = self.add(Connector(type="USB_C", pin_count=16)) # Standard 16-pin variant
        self.vbus = Net("VBUS")
        self.gnd = Net("GND")
        
        # Pull-downs for 5V @ 3A negotiation (standard USB-C)
        from openhac.stdlib.passives import Resistor
        self.r1 = self.add(Resistor(value="5.1k", package="0603"))
        self.r2 = self.add(Resistor(value="5.1k", package="0603"))

        # Connect VBUS and GND
        for p in ["A4", "A9", "B4", "B9", "VBUS"]:
            try: self.conn[p] += self.vbus
            except: pass
        for p in ["A1", "A12", "B1", "B12", "GND"]:
            try: self.conn[p] += self.gnd
            except: pass

        # Attach CC resistors
        try: self.conn["A5"] += self.r1[1]; self.r1[2] += self.gnd # CC1
        except: pass
        try: self.conn["B5"] += self.r2[1]; self.r2[2] += self.gnd # CC2
        except: pass

        self.v_out = self.declare_interface("v_out", self.vbus, self.gnd)


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


class VoltageReference(Module, _ParametricMixin):
    """Parametric precision voltage reference.

    Args:
        v_out: Target output voltage (V).
        accuracy: Maximum initial accuracy (%) - e.g. 0.1 for 0.1%.
        package: SMD package code (e.g. "SOT-23", "SOIC-8").
    """

    def __init__(self, v_out: float, accuracy: float = 0.5,
                 package: str = "SOT-23", **kwargs):
        super().__init__(f"VREF_{v_out}V")

        from openhac.database.db_manager import DatabaseManager
        db = DatabaseManager()

        desc = f"VoltageReference(v_out={v_out}V, accuracy={accuracy}%)"

        comp_data, was_fallback = db.parametric_search(
            "voltage_references",
            v_out=v_out,
            accuracy=accuracy,
            package=package
        )

        if comp_data is None:
            # Common part: TL431 (shunt), REF30xx (series)
            generic_name = f"VREF_{v_out}V"
            comp_data = db.get_component(generic_name)
            if comp_data is None:
                comp_data = Component._live_lookup(generic_name)
            if comp_data is None:
                self._raise_not_found(desc)
            was_fallback = True

        if was_fallback:
            self._warn_soft_fallback(desc, comp_data)

        self.ic = self.add(Component(comp_data["generic_name"], comp_data=comp_data, **kwargs))
        self.ic.lib = "Reference_Voltage"

        self.vout = Net("VOUT")
        self.gnd = Net("GND")
        
        self.ic["VOUT"] += self.vout
        self.ic["GND"] += self.gnd

        self.output = self.declare_interface("output", self.vout, self.gnd)


class PMIC(Module, _ParametricMixin):
    """Parametric Power Management IC (PMIC).

    Args:
        mcu_family: Target MCU family (e.g. "STM32", "i.MX").
        rails: Number of buck/LDO rails required.
    """

    def __init__(self, mcu_family: str = None, rails: int = 3, **kwargs):
        super().__init__(f"PMIC_{mcu_family or 'Generic'}")

        from openhac.database.db_manager import DatabaseManager
        db = DatabaseManager()

        desc = f"PMIC(mcu_family={mcu_family}, rails={rails})"

        comp_data, was_fallback = db.parametric_search(
            "pmics",
            mcu_family=mcu_family,
            rails=rails
        )

        if comp_data is None:
            generic_name = "TPS65217" # common example
            comp_data = db.get_component(generic_name)
            if comp_data is None:
                comp_data = Component._live_lookup(generic_name)
            if comp_data is None:
                self._raise_not_found(desc)
            was_fallback = True

        if was_fallback:
            self._warn_soft_fallback(desc, comp_data)

        self.ic = self.add(Component(comp_data["generic_name"], comp_data=comp_data, **kwargs))
        self.ic.lib = "Power_Management"

        self.v_in = self.declare_interface("v_in", self.ic["VIN"], self.ic["GND"])


class BatteryGauge(Module, _ParametricMixin):
    """Parametric Battery Fuel Gauge.

    Args:
        chemistry: "LiPo", "LiFePO4", etc.
        interface: "I2C" or "SPI".
    """

    def __init__(self, chemistry: str = "LiPo", interface: str = "I2C", **kwargs):
        super().__init__(f"Gauge_{chemistry}")

        from openhac.database.db_manager import DatabaseManager
        db = DatabaseManager()

        desc = f"BatteryGauge(chemistry={chemistry}, interface={interface})"

        comp_data, was_fallback = db.parametric_search(
            "battery_gauges",
            chemistry=chemistry,
            interface=interface
        )

        if comp_data is None:
            # Common part: MAX17048
            generic_name = "MAX17048"
            comp_data = db.get_component(generic_name)
            if comp_data is None:
                comp_data = Component._live_lookup(generic_name)
            if comp_data is None:
                self._raise_not_found(desc)
            was_fallback = True

        if was_fallback:
            self._warn_soft_fallback(desc, comp_data)

        self.ic = self.add(Component(comp_data["generic_name"], comp_data=comp_data, **kwargs))
        self.ic.lib = "Power_Management"

        self.v_batt = Net("VBATT")
        self.gnd = Net("GND")
        
        self.ic["CELL"] += self.v_batt
        self.ic["GND"] += self.gnd

        self.sense = self.declare_interface("sense", self.v_batt, self.gnd)
        if interface == "I2C":
            self.i2c = self.declare_interface("i2c", self.ic["SCL"], self.ic["SDA"])


class BuckConverter(Module, _ParametricMixin):
    """Parametric Buck (Step-Down) Switching Regulator.
    
    Automatically calculates input current draw for ERC power budgeting (PWR-002).
    """
    def __init__(self, v_out: float, max_current_a: float, efficiency: float = 0.9, **kwargs):
        super().__init__(f"Buck_{v_out}V_{max_current_a}A")
        
        from openhac.database.db_manager import DatabaseManager
        db = DatabaseManager()
        
        comp_data, _ = db.parametric_search("buck_regulators", v_out=v_out, max_current=max_current_a)
        if not comp_data:
            comp_data = Component._live_lookup(f"Buck_{v_out}V")
        
        if not comp_data:
            self._raise_not_found(f"BuckConverter(v_out={v_out}, max_current={max_current_a})")

        self.ic = self.add(Component(comp_data["generic_name"], comp_data=comp_data, **kwargs))
        self.vin = Net("VIN")
        self.vout = Net("VOUT")
        self.gnd = Net("GND")

        # Standard 3-pin style wiring (common for modules)
        try: self.ic["IN+"] += self.vin; self.ic["IN-"] += self.gnd
        except: pass
        try: self.ic["OUT+"] += self.vout; self.ic["OUT-"] += self.gnd
        except: pass

        self.v_in = self.declare_interface("v_in", self.vin, self.gnd)
        self.v_out = self.declare_interface("v_out", self.vout, self.gnd)
        
        # Register for power budgeting
        self.declare_rail_conversion("VIN", "VOUT", efficiency=efficiency)


class TP4056_Charger(Module):
    """TP4056 LiPo Battery Charger module."""
    def __init__(self):
        super().__init__("TP4056_Charger")
        self.ic = self.add(Component("TP4056"))
        self.v_in = Net("V_USB")
        self.v_batt = Net("V_BATT")
        self.gnd = Net("GND")

        # Data-driven semantic mapping
        self.ic["VCC"] += self.v_in
        self.ic["BATT"] += self.v_batt
        self.ic["GND"] += self.gnd

        self.usb_in = self.declare_interface("usb_in", self.v_in, self.gnd)
        self.batt_out = self.declare_interface("batt_out", self.v_batt, self.gnd)


# -----------------------------------------------------------------------
# Phase 3: Dynamic Parametric Submodules
# -----------------------------------------------------------------------
from openhac.core.parametric import ParametricModule
from openhac.core.part import Part, Pin
import json

# Simplified Pin Mappers for common IC families
FAMILY_PIN_MAP = {
    "TPS54302": {"VIN": "2", "GND": "1", "SW": "3", "EN": "5", "BOOT": "6", "FB": "4"},
    "AP3211": {"VIN": "5", "GND": "2", "SW": "3", "EN": "4", "BOOT": "1", "FB": "6"},
    # Default fallback guessing
    "DEFAULT": {"VIN": "VIN", "GND": "GND", "SW": "SW", "EN": "EN", "BOOT": "BOOT", "FB": "FB"}
}

class SwitchingRegulator(ParametricModule):
    """Dynamically selected Switching Regulator (Buck Converter)."""
    
    def __init__(self, name: str, v_in_nominal: float, v_out: float, current_min: float, **kwargs):
        super().__init__(name, category="Power Management", v_out=v_out, min_current=current_min, **kwargs)
        
        self.v_in_nominal = v_in_nominal
        self.v_out = v_out
        self.current_min = current_min
        
        # External interfaces
        self.vin_net = Net(f"{name}_VIN")
        self.vout_net = Net(f"{name}_VOUT")
        self.gnd_net = Net(f"{name}_GND")
        
        self.power_in = self.declare_interface("power_in", v_in=self.vin_net, gnd=self.gnd_net)
        self.power_out = self.declare_interface("power_out", v_out=self.vout_net, gnd=self.gnd_net)
        
    def _build_circuit(self, part_data: dict) -> None:
        """Wire up the selected IC and dynamically inject passives."""
        import logging
        logger = logging.getLogger("openhac.stdlib.power")
        gn = part_data.get("generic_name", "UNKNOWN_IC")
        
        # 1. Instantiate the IC
        pinout_json = part_data.get("pinout_json")
        pins = []
        if pinout_json:
            try:
                pin_list = json.loads(pinout_json)
                pins = [Pin(str(p["num"]), p.get("name", f"P{p['num']}")) for p in pin_list]
            except Exception as e:
                logger.warning(f"Failed to parse pinout for {gn}: {e}")
                
        # If no DB pinout, we mock it based on the family map (for testing/resiliency)
        if not pins:
            logger.warning(f"No pinout in DB for {gn}, falling back to mock pins.")
            pins = [Pin(str(i), str(i)) for i in range(1, 9)]
            
        ic = self.add(Part(
            "U_REG", 
            f"{part_data.get('category', 'IC')}:{gn}", 
            {"Manufacturer": part_data.get("manufacturer", "Unknown"), "Value": gn},
            pins
        ))
        
        # 2. Determine Pin Mapping
        # We try to match a known family string in the generic name
        mapping = FAMILY_PIN_MAP["DEFAULT"]
        for family, cmap in FAMILY_PIN_MAP.items():
            if family in gn:
                mapping = cmap
                break
                
        # 3. Dynamic Passive Calculation
        # Example: L = (Vin - Vout) * (Vout/Vin) / (f_sw * I_ripple)
        # We will use simplified hardcoded heuristics for the demonstration
        l_value = "4.7uH" if self.current_min > 2.0 else "10uH"
        c_in_val = "10uF"
        c_out_val = "22uF" if self.current_min > 2.0 else "10uF"
        
        # 4. Inject and Connect Components
        # Input Cap
        cin = self.add(Part("C_IN", "Capacitor_SMD:C_0805_2012Metric", {"Value": c_in_val}, [Pin("1", "1"), Pin("2", "2")]))
        cin["1"] += self.vin_net
        cin["2"] += self.gnd_net
        
        # Output Cap
        cout = self.add(Part("C_OUT", "Capacitor_SMD:C_0805_2012Metric", {"Value": c_out_val}, [Pin("1", "1"), Pin("2", "2")]))
        cout["1"] += self.vout_net
        cout["2"] += self.gnd_net
        
        # Inductor
        ind = self.add(Part("L1", "Inductor_SMD:L_Bourns_SRN6045TA", {"Value": l_value}, [Pin("1", "1"), Pin("2", "2")]))
        
        # Wire up IC
        try:
            # Power in
            ic[mapping["VIN"]] += self.vin_net
            ic[mapping["GND"]] += self.gnd_net
            
            # Enable pin to Vin (always on) if it exists
            if mapping["EN"] in [p.number for p in ic.pins.values()] or mapping["EN"] in ic.pins:
                ic[mapping["EN"]] += self.vin_net
                
            # Switch Node
            sw_net = Net("SW_NODE")
            ic[mapping["SW"]] += sw_net
            ind["1"] += sw_net
            
            # Inductor output
            ind["2"] += self.vout_net
            
            # Feedback (Simplified: assume fixed output version or external divider not shown for brevity)
            ic[mapping["FB"]] += self.vout_net
            
        except KeyError as e:
            logger.error(f"Pin mapping failed for {gn}. Missing pin in Part: {e}")
            raise
