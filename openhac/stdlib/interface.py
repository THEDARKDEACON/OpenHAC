"""
Parametric communication interface classes.

Transceivers for RS485, CAN, etc.
"""

from openhac.core.base import Component, Module
from openhac.stdlib.passives import _ParametricMixin, Capacitor
from openhac.core.net import Net


class RS485_Transceiver(Module, _ParametricMixin):
    """Parametric RS485 transceiver.

    Args:
        v_cc: Operating voltage (V), e.g. 3.3 or 5.0.
        package: SMD package code (e.g. "SOIC-8").
    """

    def __init__(self, v_cc: float = 3.3, package: str = "SOIC-8", **kwargs):
        super().__init__(f"RS485_{v_cc}V")

        db = Component.db

        desc = f"RS485_Transceiver(v_cc={v_cc}V)"

        comp_data, was_fallback = db.parametric_search(
            "transceivers",
            protocol="RS485",
            v_cc=v_cc,
            package=package
        )

        if comp_data is None:
            # Common parts: MAX3485 (3.3V), MAX485 (5V)
            generic_name = "MAX3485" if v_cc < 4.0 else "MAX485"
            comp_data = db.get_component(generic_name)
            if comp_data is None:
                comp_data = Component._live_lookup(generic_name)
            if comp_data is None:
                self._raise_not_found(desc)
            was_fallback = True

        if was_fallback:
            self._warn_soft_fallback(desc, comp_data)

        self.ic = self.add(Component(comp_data["generic_name"], comp_data=comp_data, **kwargs))

        # Standard bypass cap
        self.c_bypass = self.add(Capacitor(value="100nF", package="0603"))

        # Nets
        self.vcc = Net("VCC")
        self.gnd = Net("GND")
        self.a = Net("A")
        self.b = Net("B")
        self.tx = Net("TX")
        self.rx = Net("RX")

        # Basic wiring (DB handles mapping)
        self.ic["VCC"] += self.vcc, self.c_bypass.p1
        self.ic["GND"] += self.gnd, self.c_bypass.p2
        self.ic["A"] += self.a
        self.ic["B"] += self.b
        self.ic["DI"] += self.tx
        self.ic["RO"] += self.rx

        self.power = self.declare_interface("power", self.vcc, self.gnd)
        self.bus = self.declare_interface("bus", self.a, self.b)
        self.uart = self.declare_interface("uart", self.tx, self.rx)


class CAN_Transceiver(Module, _ParametricMixin):
    """Parametric CAN transceiver.

    Args:
        v_cc: Operating voltage (V).
        package: SMD package code (e.g. "SOIC-8").
    """

    def __init__(self, v_cc: float = 3.3, package: str = "SOIC-8", **kwargs):
        super().__init__(f"CAN_{v_cc}V")

        db = Component.db

        desc = f"CAN_Transceiver(v_cc={v_cc}V)"

        comp_data, was_fallback = db.parametric_search(
            "transceivers",
            protocol="CAN",
            v_cc=v_cc,
            package=package
        )

        if comp_data is None:
            # Common parts: TJA1050, SN65HVD230
            generic_name = "SN65HVD230" if v_cc < 4.0 else "TJA1050"
            comp_data = db.get_component(generic_name)
            if comp_data is None:
                comp_data = Component._live_lookup(generic_name)
            if comp_data is None:
                self._raise_not_found(desc)
            was_fallback = True

        if was_fallback:
            self._warn_soft_fallback(desc, comp_data)

        self.ic = self.add(Component(comp_data["generic_name"], comp_data=comp_data, **kwargs))
        self.c_bypass = self.add(Capacitor(value="100nF", package="0603"))

        self.vcc = Net("VCC")
        self.gnd = Net("GND")
        self.canh = Net("CANH")
        self.canl = Net("CANL")
        self.tx = Net("TX")
        self.rx = Net("RX")

        self.ic["VCC"] += self.vcc, self.c_bypass.p1
        self.ic["GND"] += self.gnd, self.c_bypass.p2
        self.ic["CANH"] += self.canh
        self.ic["CANL"] += self.canl
        self.ic["TXD"] += self.tx
        self.ic["RXD"] += self.rx

        self.power = self.declare_interface("power", self.vcc, self.gnd)
        self.bus = self.declare_interface("bus", self.canh, self.canl)
        self.controller = self.declare_interface("controller", self.tx, self.rx)


class USB_Controller(Module, _ParametricMixin):
    """Parametric USB-to-UART / Bridge Controller.

    Args:
        type: "uart", "fifo", "spi".
        channels: Number of UART channels.
    """

    def __init__(self, type: str = "uart", channels: int = 1, **kwargs):
        super().__init__(f"USB_{type.upper()}")

        db = Component.db

        desc = f"USB_Controller(type={type}, channels={channels})"

        comp_data, was_fallback = db.parametric_search(
            "usb_controllers",
            bridge_type=type,
            channels=channels
        )

        if comp_data is None:
            # Common parts: CP2102, CH340
            generic_name = "CP2102"
            comp_data = db.get_component(generic_name)
            if comp_data is None:
                comp_data = Component._live_lookup(generic_name)
            if comp_data is None:
                self._raise_not_found(desc)
            was_fallback = True

        if was_fallback:
            self._warn_soft_fallback(desc, comp_data)

        self.ic = self.add(Component(comp_data["generic_name"], comp_data=comp_data, **kwargs))
        self.ic.lib = "Interface_USB"


class BusBuffer(Module, _ParametricMixin):
    """Parametric I2C/SPI Bus Buffer / Repeater."""

    def __init__(self, protocol: str = "I2C", **kwargs):
        super().__init__(f"{protocol}_Buffer")


class Ethernet_PHY(Module, _ParametricMixin):
    """Parametric Ethernet Physical Layer (PHY).

    Args:
        speed: "10/100" or "10/100/1000".
        interface: "RMII" or "MII".
    """

    def __init__(self, speed: str = "10/100", interface: str = "RMII", **kwargs):
        super().__init__(f"ETH_PHY_{interface}")

        db = Component.db

        desc = f"Ethernet_PHY(speed={speed}, interface={interface})"

        comp_data, was_fallback = db.parametric_search(
            "ethernet_phys",
            speed=speed,
            interface_type=interface
        )

        if comp_data is None:
            # Common part: LAN8720A
            generic_name = "LAN8720A"
            comp_data = db.get_component(generic_name)
            if comp_data is None:
                comp_data = Component._live_lookup(generic_name)
            if comp_data is None:
                self._raise_not_found(desc)
            was_fallback = True

        if was_fallback:
            self._warn_soft_fallback(desc, comp_data)

        self.ic = self.add(Component(comp_data["generic_name"], comp_data=comp_data, **kwargs))
        self.ic.lib = "Interface_Ethernet"


class RF_Module(Module, _ParametricMixin):
    """Parametric RF / Wireless Module.

    Args:
        protocol: "WiFi", "Bluetooth", "LoRa", "Zigbee".
        form_factor: "Castellated", "DIP", "SMD".
    """

    def __init__(self, protocol: str = "WiFi", form_factor: str = "Castellated", **kwargs):
        super().__init__(f"RF_{protocol}")

        db = Component.db

        desc = f"RF_Module(protocol={protocol}, form_factor={form_factor})"

        comp_data, was_fallback = db.parametric_search(
            "rf_modules",
            protocol=protocol,
            form_factor=form_factor
        )

        if comp_data is None:
            self._raise_not_found(desc)

        if was_fallback:
            self._warn_soft_fallback(desc, comp_data)

        self.module = self.add(Component(comp_data["generic_name"], comp_data=comp_data, **kwargs))
        self.module.lib = "RF_Module"
