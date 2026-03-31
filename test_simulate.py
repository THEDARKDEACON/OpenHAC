from skidl import Net
from openhac.core.board import Board
from openhac.core.base import Module, Component

board = Board(size_mm=(50, 50))

class RC_Filter(Module):
    def __init__(self):
        super().__init__("RC_LowPass")
        
        # Utilize the generic database injected components.
        self.r = self.add(Component("R_1k_0603"))
        self.c = self.add(Component("C_10uF_0805"))
        
        self.v_in = Net('VIN')
        self.gnd = Net('0') # SPICE defines ground exactly as '0'
        self.v_out = Net('VOUT')
        
        # Logical Wiring for a standard Low Pass Filter
        # Vin -> R1 -> Vout -> C1 -> GND
        self.r['1'] += self.v_in
        self.r['2'] += self.v_out, self.c['1']
        self.c['2'] += self.gnd
        
        # Inject SPICE parameters strictly for the computational engine
        self.r.part.ref = 'R1'
        self.r.part.value = '1k'
        self.c.part.ref = 'C1'
        self.c.part.value = '10uF'

rc = RC_Filter()
board.add_module(rc)

# Target the computational analog validation step instead of the layout generation
board.simulate("analog_filter")
