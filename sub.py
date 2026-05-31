
import openhac.core  # noqa: F401
from openhac.core.net import Net
from openhac.core.base import Component
from openhac.core import Board
from openhac.core.base import Module

vcc, gnd = Net("3V3"), Net("GND")
p1 = Component("PWR_FLAG")
p1["1"] += vcc
p2 = Component("PWR_FLAG")
p2["1"] += gnd


class Node(Module):
    def __init__(self, name: str):
        super().__init__(name)
        r = self.add(Component("R_10k_0805", footprint="Resistor_SMD:R_0805_2012Metric", pins={"1": ("1", "passive"), "2": ("2", "passive")}))
        r["1"] += vcc
        r["2"] += gnd
        self.declare_interface("power", vcc, gnd)


a, b = Node("A"), Node("B")
board = Board(size_mm=(48.0, 36.0))
board.add_module(a)
board.add_module(b)
board.connect(a.expose_interface("power"), b.expose_interface("power"))
