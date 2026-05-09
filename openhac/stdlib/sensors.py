"""
Parametric sensor modules.

IMU and other sensor classes that resolve to real components
from the database using parametric search.
"""

from openhac.core.base import Component, Module
from openhac.stdlib.passives import _ParametricMixin
from openhac.core.net import Net


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

        self.max_current_draw_ma = 10.0

        self.power = self.declare_interface("power", self.vdd, self.gnd)


class TempSensor(Module, _ParametricMixin):
    """Parametric Temperature Sensor.

    Args:
        interface: "I2C", "SPI", or "Analog".
        accuracy: Required accuracy in Celsius (e.g. 0.5).
        package: Package code.
    """

    def __init__(self, interface: str = "I2C", accuracy: float = 1.0,
                 package: str = None, **kwargs):
        super().__init__(f"TEMP_{interface}")

        from openhac.database.db_manager import DatabaseManager
        db = DatabaseManager()

        desc = f"TempSensor(interface={interface}, accuracy={accuracy}C)"

        comp_data, was_fallback = db.parametric_search(
            "temperature_sensors",
            interface=interface,
            accuracy=accuracy,
            package=package
        )

        if comp_data is None:
            # Common part: TMP102 (I2C) or LM35 (Analog)
            generic_name = "TMP102" if interface == "I2C" else "LM35"
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
        self.ic["VCC"] += self.vcc
        self.ic["GND"] += self.gnd

        self.power = self.declare_interface("power", self.vcc, self.gnd)
        if interface == "I2C":
            self.i2c = self.declare_interface("i2c", self.ic["SCL"], self.ic["SDA"])


class PressureSensor(Module, _ParametricMixin):
    """Parametric Pressure Sensor (Barometric)."""

    def __init__(self, interface: str = "I2C", **kwargs):
        super().__init__("PRESSURE")
        from openhac.database.db_manager import DatabaseManager
        db = DatabaseManager()
        comp_data = db.get_component("BMP280") # example
        self.ic = self.add(Component(comp_data["generic_name"], comp_data=comp_data, **kwargs))
        self.ic.lib = "Sensor_Pressure"


class HumiditySensor(Module, _ParametricMixin):
    """Parametric Humidity + Temperature Sensor."""

    def __init__(self, interface: str = "I2C", **kwargs):
        super().__init__("HUMIDITY")
        from openhac.database.db_manager import DatabaseManager
        db = DatabaseManager()
        comp_data = db.get_component("SHT30") # example
        self.ic = self.add(Component(comp_data["generic_name"], comp_data=comp_data, **kwargs))
        self.ic.lib = "Sensor_Humidity"


class HallEffectSensor(Module, _ParametricMixin):
    """Parametric Hall Effect Sensor (Magnetic)."""

    def __init__(self, type: str = "switch", **kwargs):
        super().__init__("HALL")
        # Logic to search sensors_magnetic


class CurrentSensor(Module, _ParametricMixin):
    """Parametric Current Sensor.

    Supports both Hall-effect (isolated) and Shunt-based (non-isolated) sensors.

    Args:
        type: "hall" or "shunt".
        range_a: Maximum current range (A).
        interface: "Analog", "I2C", or "SPI".
    """

    def __init__(self, type: str = "hall", range_a: float = 50.0,
                 interface: str = "Analog", **kwargs):
        super().__init__(f"CURR_{type.upper()}_{range_a}A")

        from openhac.database.db_manager import DatabaseManager
        db = DatabaseManager()

        desc = f"CurrentSensor(type={type}, range={range_a}A, interface={interface})"

        comp_data, was_fallback = db.parametric_search(
            "sensors_current",
            sensor_type=type,
            current_range=range_a,
            interface=interface
        )

        if comp_data is None:
            # Common parts: ACS758 (Hall), INA219 (Shunt I2C)
            generic_name = "ACS758LCB-100B" if type == "hall" else "INA219"
            comp_data = db.get_component(generic_name)
            if comp_data is None:
                comp_data = Component._live_lookup(generic_name)
            if comp_data is None:
                self._raise_not_found(desc)
            was_fallback = True

        if was_fallback:
            self._warn_soft_fallback(desc, comp_data)

        self.ic = self.add(Component(comp_data["generic_name"], comp_data=comp_data, **kwargs))
        self.ic.lib = "Sensor_Current"

        # Common interfaces
        self.vcc = Net("VCC")
        self.gnd = Net("GND")
        
        # Mapping for ACS758 style Hall sensors
        if "ACS758" in comp_data["generic_name"]:
            self.ic["1"] += self.vcc
            self.ic["2"] += self.gnd
            self.out = Net("VOUT")
            self.ic["3"] += self.out
            self.ip_pos = Net("IP_POS")
            self.ip_neg = Net("IP_NEG")
            self.ic["4"] += self.ip_pos
            self.ic["5"] += self.ip_neg
        else:
            # Fallback/Generic mapping
            try:
                self.ic["VCC"] += self.vcc
                self.ic["GND"] += self.gnd
            except KeyError:
                pass

        self.power = self.declare_interface("power", vcc=self.vcc, gnd=self.gnd)
        if interface == "Analog":
            out_pin = getattr(self, "out", None) or self.ic["OUT"]
            self.v_out = self.declare_interface("v_out", vout=out_pin)
        elif interface == "I2C":
            self.i2c = self.declare_interface("i2c", scl=self.ic["SCL"], sda=self.ic["SDA"])


class GasSensor(Module, _ParametricMixin):
    """Parametric Gas/VOC Sensor."""

    def __init__(self, gas_type: str = "CO2", **kwargs):
        super().__init__(f"GAS_{gas_type}")


class LightSensor(Module, _ParametricMixin):
    """Parametric Ambient Light Sensor."""

    def __init__(self, **kwargs):
        super().__init__("LIGHT")


class ProximitySensor(Module, _ParametricMixin):
    """Parametric Proximity/Distance Sensor."""

    def __init__(self, technology: str = "IR", **kwargs):
        super().__init__(f"PROX_{technology}")
