import warnings


def _resolve_spice_id(part) -> str:
    """Resolve the SPICE reference designator for a part using Part.ref_prefix."""
    prefix = part.ref_prefix or 'X'
    if not part.ref_prefix:
        warnings.warn(
            f"Part {part.ref} has no ref_prefix, defaulting to 'X'",
            UserWarning,
        )
    ref = part.ref
    if ref.upper().startswith(prefix.upper()):
        return ref
    return prefix + ref


def _sanitize_net_name(name: str) -> str:
    """Sanitize a net name for SPICE compatibility."""
    return name.replace(" ", "_").replace("-", "_").replace("/", "_")


def generate_spice(project_name: str):
    output_cir_path = f"{project_name}.cir"
    print(f"Bypassing Physical Geometry.")
    print(f"Generating Computational SPICE Simulation Netlist -> {output_cir_path}")

    try:
        import builtins
        circuit = builtins.default_circuit

        emitted_refs = set()

        with open(output_cir_path, 'w') as f:
            f.write(f"* SPICE Simulation Graph: {project_name}\n")

            # Add SPICE simulation models directive standard
            f.write(".tran 1m 100m\n")

            for part in circuit.parts:
                spice_id = _resolve_spice_id(part)

                # Skip duplicates
                if spice_id in emitted_refs:
                    continue

                nodes_list = []
                for p in part.pins:
                    if p.net is not None:
                        net_name = _sanitize_net_name(str(p.net.name))
                        nodes_list.append(net_name)
                nodes = " ".join(nodes_list)

                val = part.value if part.value else part.name

                # Ensure only components with valid connections are exported
                if len(nodes_list) >= 2:
                    f.write(f"{spice_id} {nodes} {val}\n")
                    emitted_refs.add(spice_id)

            f.write(".end\n")
        print("Computational SPICE Engine (OpenHaC Native) completed successfully.")
    except Exception as e:
        print(f"Native SPICE generation failed: {e}")
        raise e
