import json
import os

def generate_project_file(output_path: str):
    print(f"Synthesizing KiCad Project Directory Matrix -> {output_path}")
    
    # The modern .kicad_pro file is a strict JSON wrapper stitching the ecosystem together
    project_payload = {
        "meta": {
            "filename": os.path.basename(output_path),
            "version": 3
        },
        "board": {
            "design_settings": {},
            "layer_presets": []
        },
        "cvpcb": {
            "equivalence_files": []
        },
        "general": {},
        "netlist": {},
        "pcbnew": {},
        "schematic": {}
    }
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(project_payload, f, indent=2)
        
    print("Project Directory configuration locked.")
