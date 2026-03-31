from skidl import generate_netlist
import csv

def generate_logic_and_bom(project_name: str, generate_bom: bool = True):
    print(f"Compiling Netlist for {project_name}...")
    try:
        generate_netlist(file_="{}.net".format(project_name))
        print(f"Generated {project_name}.net")
    except Exception as e:
        print(f"Netlist generation error: {e}")

    if generate_bom:
        bom_filename = f"{project_name}.csv"
        print(f"Exporting BOM to {bom_filename}...")
        with open(bom_filename, 'w', newline='') as csvfile:
            fieldnames = ['Reference', 'Value', 'Manufacturer', 'MPN', 'Supplier_SKU', 'Footprint']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            import builtins
            for part in builtins.default_circuit.parts:
                writer.writerow({
                    'Reference': part.ref,
                    'Value': part.value,
                    'Manufacturer': part.fields.get('Manufacturer', ''),
                    'MPN': part.fields.get('MPN', ''),
                    'Supplier_SKU': part.fields.get('Supplier_SKU', ''),
                    'Footprint': part.footprint,
                })
