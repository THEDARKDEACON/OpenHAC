from openhac.core.base import Module, Component
from skidl import Net

class ESP32_WROOM(Module):
    def __init__(self):
        super().__init__()
        self.mcu = self.add(Component("ESP32_WROOM"))
        
        self.vcc = Net('3V3_VCC') 
        self.gnd = Net('GND')
        
        self.mcu['2'] += self.vcc
        self.mcu['1'] += self.gnd
        self.mcu['15'] += self.gnd
        self.mcu['38'] += self.gnd
        
        self.power = self.declare_interface("power", self.vcc, self.gnd)
