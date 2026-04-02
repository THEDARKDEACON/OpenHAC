from openhac.core.base import Module, Component
from skidl import Net

class XT60_Input(Module):
    def __init__(self):
        super().__init__()
        self.connector = self.add(Component("XT60_Vertical"))
        self.vcc = Net('VIN')
        self.gnd = Net('GND')
        
        self.connector['1'] += self.vcc
        self.connector['2'] += self.gnd
        
        self.v_out = self.declare_interface("v_out", self.vcc, self.gnd)

class LDO_5V(Module):
    def __init__(self):
        super().__init__()
        self.ldo = self.add(Component("LDO_5V"))
        self.c_in = self.add(Component("C_100nF_0603"))
        self.c_out = self.add(Component("C_100nF_0603"))
        
        self.vin = Net('LDO_VIN')
        self.vout = Net('5V')
        self.gnd = Net('GND')
        
        self.ldo['1'] += self.gnd, self.c_in['2'], self.c_out['2']
        self.ldo['3'] += self.vin, self.c_in['1']
        self.ldo['2'] += self.vout, self.c_out['1']
        self.ldo['4'] += self.vout
        
        self.v_in = self.declare_interface("v_in", self.vin, self.gnd)
        self.v_out = self.declare_interface("v_out", self.vout, self.gnd)
