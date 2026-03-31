import os
from skidl import Net, Bus
from .base import Module

class Board:
    def __init__(self, size_mm: tuple, layers: int = 2):
        self.size_mm = size_mm
        self.layers = layers
        self.modules = []
        self.constraints = []

    def connect(self, intf1, intf2):
        if hasattr(intf1, 'connect') and hasattr(intf2, 'connect'):
            intf1.connect(intf2)
        else:
            intf1 += intf2

    def add_module(self, module):
        self.modules.append(module)

    def constrain_distance_min(self, mod_a, mod_b, min_mm):
        self.constraints.append({'type': 'distance_min', 'args': (mod_a, mod_b, min_mm)})

    def constrain_distance_max(self, mod_a, mod_b, max_mm):
        self.constraints.append({'type': 'distance_max', 'args': (mod_a, mod_b, max_mm)})

    def constrain_edge(self, mod, edge):
        self.constraints.append({'type': 'edge', 'args': (mod, edge)})

    def compile(self, project_name: str = "board", generate_bom: bool = True, auto_route: bool = True):
        try:
            from openhac.compiler.netlist_gen import generate_logic_and_bom
            generate_logic_and_bom(project_name, generate_bom)
        except ImportError as e:
            print(f"Could not import netlist_gen. {e}")

        print(f"Applying geometric layout constraints. Target: {self.size_mm[0]}x{self.size_mm[1]}mm, {self.layers} Layers")
        try:
            from openhac.compiler.layout_gen import generate_layout
            generate_layout(f"{project_name}.net", f"{project_name}.kicad_pcb", self)
        except ImportError as e:
            print(f"Could not import layout_gen. {e}")
        
        if auto_route:
            try:
                from openhac.compiler.autoroute_cli import run_freerouting
                print("Running auto-router...")
                run_freerouting(f"{project_name}.kicad_pcb")
            except ImportError:
                print("Auto-router module missing.")
