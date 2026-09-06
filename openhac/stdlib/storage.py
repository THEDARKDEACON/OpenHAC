"""
Parametric storage component classes.

Flash, EEPROM, and other non-volatile memory.
"""

from openhac.core.base import Component, Module
from openhac.stdlib.passives import _ParametricMixin, Capacitor
from openhac.core.net import Net


class FlashMemory(Module, _ParametricMixin):
    """Parametric NOR Flash memory.

    Args:
        size_mb: Memory size in Megabits (Mbit).
        interface: "SPI" or "QSPI".
        v_cc: Operating voltage (V).
        package: SMD package code (e.g. "SOIC-8", "WSON-8").
    """

    def __init__(self, size_mb: int = 64, interface: str = "SPI",
                 v_cc: float = 3.3, package: str = "SOIC-8", **kwargs):
        super().__init__(f"FLASH_{size_mb}M")

        db = Component.db

        desc = f"FlashMemory(size={size_mb}Mbit, interface={interface})"

        comp_data, was_fallback = db.parametric_search(
            "memory_flash",
            size_mb=size_mb,
            interface=interface,
            v_cc=v_cc,
            package=package
        )

        if comp_data is None:
            # Common part: W25Q64 (64-Mbit SPI)
            generic_name = f"W25Q{size_mb}"
            comp_data = db.get_component(generic_name)
            if comp_data is None:
                comp_data = Component._live_lookup(generic_name)
            if comp_data is None:
                self._raise_not_found(desc)
            was_fallback = True

        if was_fallback:
            self._warn_soft_fallback(desc, comp_data)

        self.ic = self.add(Component(comp_data["generic_name"], comp_data=comp_data, **kwargs))
        self.ic.lib = "Memory_Flash"

        self.c_vcc = self.add(Capacitor(value="100nF", package="0402"))
        
        self.vcc = Net("VCC")
        self.gnd = Net("GND")
        
        self.ic["VCC"] += self.vcc, self.c_vcc.p1
        self.ic["GND"] += self.gnd, self.c_vcc.p2

        self.power = self.declare_interface("power", self.vcc, self.gnd)


class EEPROM(Module, _ParametricMixin):
    """Parametric EEPROM memory.

    Args:
        size_kb: Memory size in Kilobits (kbit).
        interface: "I2C" or "SPI".
    """

    def __init__(self, size_kb: int = 256, interface: str = "I2C", **kwargs):
        super().__init__(f"EEPROM_{size_kb}K")

        db = Component.db

        desc = f"EEPROM(size={size_kb}kbit, interface={interface})"

        comp_data, was_fallback = db.parametric_search(
            "memory_eeprom",
            size_kb=size_kb,
            interface=interface
        )

        if comp_data is None:
            # Common part: 24LC256 (256-kbit I2C)
            generic_name = f"24LC{size_kb}"
            comp_data = db.get_component(generic_name)
            if comp_data is None:
                comp_data = Component._live_lookup(generic_name)
            if comp_data is None:
                self._raise_not_found(desc)
            was_fallback = True

        if was_fallback:
            self._warn_soft_fallback(desc, comp_data)

        self.ic = self.add(Component(comp_data["generic_name"], comp_data=comp_data, **kwargs))
        self.ic.lib = "Memory_EEPROM"

        self.vcc = Net("VCC")
        self.gnd = Net("GND")
        
        self.ic["VCC"] += self.vcc
        self.ic["GND"] += self.gnd

        self.power = self.declare_interface("power", self.vcc, self.gnd)


class RAM(Module, _ParametricMixin):
    """Parametric SRAM / SDRAM memory.

    Args:
        size_mb: Memory size in Megabits (Mbit).
        interface: "SPI", "QSPI", or "Parallel".
    """

    def __init__(self, size_mb: int = 8, interface: str = "SPI", **kwargs):
        super().__init__(f"RAM_{size_mb}M")

        db = Component.db

        desc = f"RAM(size={size_mb}Mbit, interface={interface})"

        comp_data, was_fallback = db.parametric_search(
            "memory_ram",
            size_mb=size_mb,
            interface=interface
        )

        if comp_data is None:
            # Common part: 23LC1024 (1-Mbit SPI)
            generic_name = f"RAM_{size_mb}M"
            comp_data = db.get_component(generic_name)
            if comp_data is None:
                comp_data = Component._live_lookup(generic_name)
            if comp_data is None:
                self._raise_not_found(desc)
            was_fallback = True

        if was_fallback:
            self._warn_soft_fallback(desc, comp_data)

        self.ic = self.add(Component(comp_data["generic_name"], comp_data=comp_data, **kwargs))
        self.ic.lib = "Memory_RAM"


class EEPROM_I2C(Module, _ParametricMixin):
    """Parametric I2C EEPROM.

    Args:
        size_kb: Capacity in Kilobits (Kb).
        v_min: Minimum supply voltage.
    """

    def __init__(self, size_kb: int = 256, v_min: float = 3.3, **kwargs):
        super().__init__(f"EEPROM_{size_kb}K")

        db = Component.db

        desc = f"EEPROM(size={size_kb}Kb, v_min={v_min}V)"

        comp_data, was_fallback = db.parametric_search(
            "memory_eeprom",
            size_kb=size_kb,
            v_min=v_min,
            interface="I2C"
        )

        if comp_data is None:
            # Common part: 24LC256
            generic_name = f"24LC{size_kb}" if size_kb in (32, 64, 128, 256, 512) else "24LC256"
            comp_data = db.get_component(generic_name)
            if comp_data is None:
                comp_data = Component._live_lookup(generic_name)
            if comp_data is None:
                self._raise_not_found(desc)
            was_fallback = True

        if was_fallback:
            self._warn_soft_fallback(desc, comp_data)

        self.ic = self.add(Component(comp_data["generic_name"], comp_data=comp_data, **kwargs))
        self.ic.lib = "Memory_EEPROM"

        self.vcc = Net("VCC")
        self.gnd = Net("GND")
        self.scl = Net("SCL")
        self.sda = Net("SDA")
        
        # Standard 24xx pinout
        try:
            self.ic["VCC"] += self.vcc
            self.ic["GND"] += self.gnd
            self.ic["SCL"] += self.scl
            self.ic["SDA"] += self.sda
        except KeyError:
            pass

        self.power = self.declare_interface("power", vcc=self.vcc, gnd=self.gnd)
        self.i2c = self.declare_interface("i2c", scl=self.scl, sda=self.sda)
