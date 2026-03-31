def generate_spice(project_name: str):
    output_cir_path = f"{project_name}.cir"
    print(f"Bypassing Physical Geometry.")
    print(f"Generating Computational SPICE Simulation Netlist -> {output_cir_path}")
    
    try:
        import builtins
        circuit = builtins.default_circuit
        
        with open(output_cir_path, 'w') as f:
            f.write(f"* SPICE Simulation Graph: {project_name}\n")
            
            # Add SPICE simulation models directive standard
            f.write(".tran 1m 100m\n")
            
            # Generate node definitions based on part logic map
            for part in circuit.parts:
                # Assign a valid SPICE reference designator (R for Resistor, C for Capacitor, V for Source)
                refs = part.ref
                if not refs.upper().startswith('R') and ("Resistor" in str(part.description) or "R" in str(part.value)):
                    refs = "R" + refs
                elif not refs.upper().startswith('C') and ("Capacitor" in str(part.description) or "uF" in str(part.value)):
                    refs = "C" + refs
                    
                nodes_list = []
                for p in part.pins:
                    if p.net is not None:
                        # Sanitize net names for SPICE compatibility
                        net_name = str(p.net.name).replace(" ", "_").replace("-", "_")
                        nodes_list.append(net_name)
                nodes = " ".join(nodes_list)
                
                val = part.value if part.value else part.name
                
                # Ensure only components with valid connections are exported
                if len(nodes_list) >= 2:
                    f.write(f"{refs} {nodes} {val}\n")
            
            f.write(".end\n")
        print("Computational SPICE Engine (OpenHaC Native) completed successfully.")
    except Exception as e:
        print(f"Native SPICE generation failed: {e}")
        raise e
