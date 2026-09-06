"""
Parametric protection component classes.

Fuse and ESD protection logic.
"""

from openhac.core.base import Component, Module
from openhac.stdlib.passives import _ParametricMixin
from openhac.core.net import Net


class Fuse(Module, _ParametricMixin):
    """Parametric fuse or PTC.

    Args:
        hold_current: Current in amps the fuse can hold without tripping.
        voltage: Maximum operating voltage (V).
        package: SMD package code (e.g. "0805", "1206").
        type: "Fuse" or "PTC" (resettable).
    """

    def __init__(self, hold_current: float, voltage: float = 30.0,
                 package: str = "1206", type: str = "PTC", **kwargs):
        name = f"{type}_{hold_current}A"
        super().__init__(name)

        db = Component.db

        desc = f"Fuse(hold_current={hold_current}A, voltage={voltage}V, type={type})"

        comp_data, was_fallback = db.parametric_search(
            "fuses",
            hold_current=hold_current,
            voltage=voltage,
            type=type,
            package=package
        )

        if comp_data is None:
            # Try generic name lookup
            generic_name = f"{type}_{hold_current}A_{package}"
            comp_data = db.get_component(generic_name)
            if comp_data is None:
                comp_data = Component._live_lookup(generic_name)
            if comp_data is None:
                self._raise_not_found(desc)
            was_fallback = True

        if was_fallback:
            self._warn_soft_fallback(desc, comp_data)

        self._comp = self.add(Component(comp_data["generic_name"], comp_data=comp_data, **kwargs))

        # Fuses are 2-pin series devices
        self.p1 = Net(f"{name}_1")
        self.p2 = Net(f"{name}_2")
        self._comp["1"] += self.p1
        self._comp["2"] += self.p2


class ESDSafeSignal(Module, _ParametricMixin):
    """Parametric ESD/TVS protection diode for a signal or rail.

    Args:
        voltage: Working voltage of the line to protect (V).
        package: Package code (e.g. "SOD-323", "SOT-23").
        bidirectional: Whether the signal is bipolar/bidirectional.
    """

    def __init__(self, voltage: float, package: str = "SOD-323",
                 bidirectional: bool = False, **kwargs):
        name = f"TVS_{voltage}V"
        super().__init__(name)

        db = Component.db

        desc = f"ESDSafeSignal(voltage={voltage}V, bidirectional={bidirectional})"

        comp_data, was_fallback = db.parametric_search(
            "tvs_diodes",
            v_working=voltage,
            bidirectional=bidirectional,
            package=package
        )

        if comp_data is None:
            generic_name = f"TVS_{voltage}V_{'BI' if bidirectional else 'UNI'}"
            comp_data = db.get_component(generic_name)
            if comp_data is None:
                comp_data = Component._live_lookup(generic_name)
            if comp_data is None:
                self._raise_not_found(desc)
            was_fallback = True

        if was_fallback:
            self._warn_soft_fallback(desc, comp_data)

        self._comp = self.add(Component(comp_data["generic_name"], comp_data=comp_data, **kwargs))

        # TVS diodes connect between Signal and GND
        self.signal = Net(f"{name}_SIG")
        self.gnd = Net(f"{name}_GND")
        
        # Standard pinout: 1=Signal, 2=GND (varies by package but JIT/DB handles mapping)
        self._comp["1"] += self.signal
        self._comp["2"] += self.gnd


class IdealDiodeController(Module, _ParametricMixin):
    """Parametric Ideal Diode Controller with external MOSFET.

    Args:
        voltage: Operating voltage (V).
        current: Maximum load current (A).
        package: IC package code.
    """

    def __init__(self, voltage: float = 12.0, current: float = 5.0,
                 package: str = "SOT-23-6", **kwargs):
        super().__init__(f"IdealDiode_{current}A")

        from openhac.stdlib.discretes import MOSFET
        db = Component.db

        desc = f"IdealDiodeController(voltage={voltage}V, current={current}A)"

        comp_data, was_fallback = db.parametric_search(
            "ideal_diode_controllers",
            v_max=voltage,
            package=package
        )

        if comp_data is None:
            generic_name = "LM74700" # common example
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

        # Add the external MOSFET (P-Channel for high-side)
        self.mos = self.add(MOSFET(type="p", v_ds=voltage*1.5, i_d=current*1.2))

        self.vin = Net("VIN")
        self.vout = Net("VOUT")
        self.gnd = Net("GND")

        # Wiring: [VIN] -> [MOS Source] | [MOS Drain] -> [VOUT]
        self.mos.s += self.vin
        self.mos.d += self.vout
        self.mos.g += self.ic["GATE"]
        
        self.ic["VIN"] += self.vin
        self.ic["VOUT"] += self.vout
        self.ic["GND"] += self.gnd

        self.power = self.declare_interface("power", self.vin, self.vout, self.gnd)


class Varistor(Module, _ParametricMixin):
    """Parametric Metal Oxide Varistor (MOV).

    Args:
        v_clamping: Maximum clamping voltage (V).
        package: Package code (e.g. "0603", "10D").
    """

    def __init__(self, v_clamping: float, package: str = "0603", **kwargs):
        super().__init__(f"MOV_{v_clamping}V")

        db = Component.db

        desc = f"Varistor(v_clamping={v_clamping}V)"

        comp_data, was_fallback = db.parametric_search(
            "varistors",
            v_clamping=v_clamping,
            package=package
        )

        if comp_data is None:
            generic_name = f"MOV_{v_clamping}V"
            comp_data = db.get_component(generic_name)
            if comp_data is None:
                comp_data = Component._live_lookup(generic_name)
            if comp_data is None:
                self._raise_not_found(desc)
            was_fallback = True

        if was_fallback:
            self._warn_soft_fallback(desc, comp_data)

        self.mov = self.add(Component(comp_data["generic_name"], comp_data=comp_data, **kwargs))
        self.mov.lib = "Device"

        self.p1 = Net("P1")
        self.p2 = Net("P2")
        self.mov["1"] += self.p1
        self.mov["2"] += self.p2


class GDT(Module, _ParametricMixin):
    """Parametric Gas Discharge Tube (GDT).

    Args:
        v_sparkover: Nominal DC sparkover voltage (V).
        package: Package code (e.g. "SMD_5x5mm").
    """

    def __init__(self, v_sparkover: float, package: str = None, **kwargs):
        super().__init__(f"GDT_{v_sparkover}V")

        db = Component.db

        desc = f"GDT(v_sparkover={v_sparkover}V)"

        comp_data, was_fallback = db.parametric_search(
            "gdts",
            v_sparkover=v_sparkover,
            package=package
        )

        if comp_data is None:
            generic_name = f"GDT_{v_sparkover}V"
            comp_data = db.get_component(generic_name)
            if comp_data is None:
                comp_data = Component._live_lookup(generic_name)
            if comp_data is None:
                self._raise_not_found(desc)
            was_fallback = True

        if was_fallback:
            self._warn_soft_fallback(desc, comp_data)

        self.gdt = self.add(Component(comp_data["generic_name"], comp_data=comp_data, **kwargs))
        self.gdt.lib = "Device"

        self.p1 = Net("P1")
        self.p2 = Net("P2")
        self.gdt["1"] += self.p1
        self.gdt["2"] += self.p2


class ThermalSwitch(Module, _ParametricMixin):
    """Parametric Thermal Switch or Monitor.

    Args:
        temp_threshold: Trip temperature in Celsius.
        type: "Switch" (bimetallic) or "IC" (silicon).
    """

    def __init__(self, temp_threshold: float, type: str = "IC", **kwargs):
        super().__init__(f"Thermal_{temp_threshold}C")

        db = Component.db

        desc = f"ThermalSwitch(temp={temp_threshold}C, type={type})"

        comp_data, was_fallback = db.parametric_search(
            "thermal_switches",
            temp_threshold=temp_threshold,
            type=type
        )

        if comp_data is None:
            # Common part: TMP302
            generic_name = "TMP302"
            comp_data = db.get_component(generic_name)
            if comp_data is None:
                comp_data = Component._live_lookup(generic_name)
            if comp_data is None:
                self._raise_not_found(desc)
            was_fallback = True

        if was_fallback:
            self._warn_soft_fallback(desc, comp_data)

        self.ic = self.add(Component(comp_data["generic_name"], comp_data=comp_data, **kwargs))
        self.ic.lib = "Sensor_Temperature"

        self.vcc = Net("VCC")
        self.gnd = Net("GND")
        self.trip = Net("TRIP")
        
        self.ic["VCC"] += self.vcc
        self.ic["GND"] += self.gnd
        self.ic["OUT"] += self.trip

        self.power = self.declare_interface("power", self.vcc, self.gnd)
        self.signal = self.declare_interface("signal", self.trip)
