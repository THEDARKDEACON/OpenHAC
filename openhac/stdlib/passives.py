from openhac.core.base import Component

class Resistor(Component):
    def __init__(self, value="10k", package="0805", **kwargs):
        generic_name = f"R_{value}_{package}"
        super().__init__(generic_name, **kwargs)

class Capacitor(Component):
    def __init__(self, value="100nF", package="0603", **kwargs):
        generic_name = f"C_{value}_{package}"
        super().__init__(generic_name, **kwargs)
