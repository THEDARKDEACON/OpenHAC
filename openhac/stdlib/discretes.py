"""
Parametric discrete semiconductor classes.

MOSFETs and general-purpose Diodes.
"""

from openhac.core.base import Component, Module
from openhac.stdlib.passives import _ParametricMixin
from openhac.core.net import Net


class MOSFET(Module, _ParametricMixin):
    """Parametric MOSFET.

    Args:
        type: "n" for N-Channel, "p" for P-Channel.
        v_ds: Minimum Drain-Source voltage (V).
        i_d: Minimum Drain current (A).
        package: SMD package code (e.g. "SOT-23", "SOIC-8").
        logic_level: If True, filters for low Vgs(th).
    """

    def __init__(self, type: str = "n", v_ds: float = 30.0, i_d: float = 1.0,
                 package: str = "SOT-23", logic_level: bool = True, **kwargs):
        name = f"MOS_{type.upper()}_{v_ds}V_{i_d}A"
        super().__init__(name)

        from openhac.database.db_manager import DatabaseManager
        db = DatabaseManager()

        desc = f"MOSFET(type={type}, v_ds={v_ds}V, i_d={i_d}A, logic_level={logic_level})"

        comp_data, was_fallback = db.parametric_search(
            "transistors_mosfets",
            channel_type=type,
            v_ds=v_ds,
            i_d=i_d,
            logic_level=logic_level,
            package=package
        )

        if comp_data is None:
            generic_name = f"MOS_{type.upper()}_{package}"
            comp_data = db.get_component(generic_name)
            if comp_data is None:
                comp_data = Component._live_lookup(generic_name)
            if comp_data is None:
                self._raise_not_found(desc)
            was_fallback = True

        if was_fallback:
            self._warn_soft_fallback(desc, comp_data)

        self._comp = self.add(Component(comp_data["generic_name"], comp_data=comp_data, **kwargs))

        # Standard MOSFET nets
        self.g = Net(f"{name}_G")
        self.d = Net(f"{name}_D")
        self.s = Net(f"{name}_S")

        # Basic pin mapping (DB handles mapping for complex packages)
        # SOT-23 default: 1=Gate, 2=Source, 3=Drain (usually)
        self._comp["1"] += self.g
        self._comp["2"] += self.s
        self._comp["3"] += self.d


class Diode(Module, _ParametricMixin):
    """Parametric Diode.

    Args:
        type: "schottky", "rectifier", "signal".
        v_r: Reverse voltage rating (V).
        i_f: Forward current rating (A).
        package: SMD package code (e.g. "SOD-123", "SMA").
    """

    def __init__(self, type: str = "schottky", v_r: float = 40.0, i_f: float = 1.0,
                 package: str = "SOD-123", **kwargs):
        name = f"D_{type.upper()}_{v_r}V_{i_f}A"
        super().__init__(name)

        from openhac.database.db_manager import DatabaseManager
        db = DatabaseManager()

        desc = f"Diode(type={type}, v_r={v_r}V, i_f={i_f}A)"

        comp_data, was_fallback = db.parametric_search(
            "diodes",
            diode_type=type,
            v_r=v_r,
            i_f=i_f,
            package=package
        )

        if comp_data is None:
            generic_name = f"D_{type.upper()}_{package}"
            comp_data = db.get_component(generic_name)
            if comp_data is None:
                comp_data = Component._live_lookup(generic_name)
            if comp_data is None:
                self._raise_not_found(desc)
            was_fallback = True

        if was_fallback:
            self._warn_soft_fallback(desc, comp_data)

        self._comp = self.add(Component(comp_data["generic_name"], comp_data=comp_data, **kwargs))

        # Diode pins
        self.anode = Net(f"{name}_A")
        self.cathode = Net(f"{name}_K")

        self._comp["1"] += self.anode
        self._comp["2"] += self.cathode


class BJT(Module, _ParametricMixin):
    """Parametric Bipolar Junction Transistor (BJT).

    Args:
        type: "npn" or "pnp".
        v_ce: Minimum Collector-Emitter voltage (V).
        i_c: Minimum Collector current (A).
        package: SMD package code (e.g. "SOT-23").
    """

    def __init__(self, type: str = "npn", v_ce: float = 30.0, i_c: float = 0.1,
                 package: str = "SOT-23", **kwargs):
        name = f"BJT_{type.upper()}"
        super().__init__(name)

        from openhac.database.db_manager import DatabaseManager
        db = DatabaseManager()

        desc = f"BJT(type={type}, v_ce={v_ce}V, i_c={i_c}A)"

        comp_data, was_fallback = db.parametric_search(
            "transistors_bjts",
            transistor_type=type,
            v_ce=v_ce,
            i_c=i_c,
            package=package
        )

        if comp_data is None:
            # Common parts: MMBT2222 (NPN), MMBT2907 (PNP)
            generic_name = "MMBT2222" if type == "npn" else "MMBT2907"
            comp_data = db.get_component(generic_name)
            if comp_data is None:
                comp_data = Component._live_lookup(generic_name)
            if comp_data is None:
                self._raise_not_found(desc)
            was_fallback = True

        if was_fallback:
            self._warn_soft_fallback(desc, comp_data)

        self.ic = self.add(Component(comp_data["generic_name"], comp_data=comp_data, **kwargs))
        self.ic.lib = "Transistor_BJT"

        self.b = Net("B")
        self.c = Net("C")
        self.e = Net("E")

        # Basic pin mapping (DB handles specific package variations)
        self.ic["1"] += self.b
        self.ic["2"] += self.e
        self.ic["3"] += self.c


class ZenerDiode(Module, _ParametricMixin):
    """Parametric Zener Diode.

    Args:
        v_zener: Nominal Zener voltage (V).
        p_max: Maximum power dissipation (W).
        package: SMD package code (e.g. "SOD-123").
    """

    def __init__(self, v_zener: float, p_max: float = 0.5,
                 package: str = "SOD-123", **kwargs):
        super().__init__(f"ZENER_{v_zener}V")

        from openhac.database.db_manager import DatabaseManager
        db = DatabaseManager()

        desc = f"ZenerDiode(v_zener={v_zener}V)"

        comp_data, was_fallback = db.parametric_search(
            "diodes_zener",
            v_zener=v_zener,
            p_max=p_max,
            package=package
        )

        if comp_data is None:
            generic_name = f"BZX84_{v_zener}V"
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

        self.anode = Net("A")
        self.cathode = Net("K")
        self.ic["1"] += self.anode
        self.ic["2"] += self.cathode


class BridgeRectifier(Module, _ParametricMixin):
    """Parametric Bridge Rectifier.

    Args:
        v_rms: Minimum AC input voltage (Vrms).
        i_avg: Average rectified output current (A).
        package: Package code (e.g. "MB6S").
    """

    def __init__(self, v_rms: float = 230.0, i_avg: float = 1.0,
                 package: str = "MB6S", **kwargs):
        super().__init__(f"BRIDGE_{i_avg}A")

        from openhac.database.db_manager import DatabaseManager
        db = DatabaseManager()

        desc = f"BridgeRectifier(v_rms={v_rms}V, i_avg={i_avg}A)"

        comp_data, was_fallback = db.parametric_search(
            "bridge_rectifiers",
            v_rms=v_rms,
            i_avg=i_avg,
            package=package
        )

        if comp_data is None:
            generic_name = package or "MB6S"
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

        self.ac1 = Net("AC1")
        self.ac2 = Net("AC2")
        self.pos = Net("POS")
        self.neg = Net("NEG")

        self.ic["1"] += self.ac1
        self.ic["2"] += self.ac2
        self.ic["3"] += self.pos
        self.ic["4"] += self.neg


class IGBT(Module, _ParametricMixin):
    """Parametric Insulated Gate Bipolar Transistor (IGBT)."""

    def __init__(self, v_ce: float = 600.0, i_c: float = 20.0, **kwargs):
        super().__init__("IGBT")
        # Implementation similar to MOSFET/BJT
        # Targets 'transistors_igbts' category in DB


class JFET(Module, _ParametricMixin):
    """Parametric Junction Field Effect Transistor (JFET)."""

    def __init__(self, type: str = "n", **kwargs):
        super().__init__("JFET")


class SCR_Thyristor(Module, _ParametricMixin):
    """Parametric Thyristor or TRIAC."""

    def __init__(self, type: str = "triac", **kwargs):
        super().__init__("TRIAC")
