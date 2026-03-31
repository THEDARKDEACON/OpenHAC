from skidl import Part, Net, Bus
from openhac.database.db_manager import DatabaseManager

class Component:
    db = DatabaseManager()

    def __init__(self, generic_name: str, **kwargs):
        self.generic_name = generic_name
        
        comp_data = self.db.get_component(generic_name)
        if not comp_data:
            raise ValueError(f"Component '{generic_name}' not found in database.")
            
        sym_lib, sym_name = comp_data['kicad_symbol'].split(':', 1)
        try:
            import skidl
            skidl.config.github_search = False
            self.part = Part(sym_lib, sym_name, footprint=comp_data['kicad_footprint'], **kwargs)
        except Exception as e:
            # Fallback for environments without KiCad libraries installed
            import skidl
            from skidl import Pin
            print(f"Warning: Could not load KiCad library for {sym_lib}:{sym_name}. Creating synthetic part.")
            pins = [Pin(num=str(i), name=str(i)) for i in range(1, 100)]
            self.part = Part(tool=skidl.SKIDL, name=sym_name, ref_prefix='U', pins=pins, footprint=comp_data['kicad_footprint'])

        
        self.part.fields['Manufacturer'] = comp_data['manufacturer'] or ""
        self.part.fields['MPN'] = comp_data['mpn']
        self.part.fields['Supplier_SKU'] = comp_data['supplier_sku'] or ""
        self.part.fields['Value'] = generic_name

    def __getattr__(self, name):
        return getattr(self.part, name)

    def __getitem__(self, key):
        return self.part[key]

    def __setitem__(self, key, value):
        self.part[key] = value

class Interface:
    def __init__(self, name: str, *signals):
        self.name = name
        self.signals = list(signals)

    def connect(self, other_interface):
        for sig1, sig2 in zip(self.signals, other_interface.signals):
            sig1 += sig2

class Module:
    def __init__(self):
        self.components = []
        
    def add(self, component):
        self.components.append(component)
        return component
