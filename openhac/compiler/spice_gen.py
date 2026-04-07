import logging
import warnings

from openhac.util.sort_keys import natural_key

logger = logging.getLogger("openhac.spice")


def _resolve_spice_id(part) -> str:
    """Resolve the SPICE reference designator for a part using Part.ref_prefix."""
    prefix = part.ref_prefix or "X"
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


def generate_spice(
    output_cir_path: str,
    *,
    analysis_lines: list[str] | None = None,
):
    """Write a SPICE deck to *output_cir_path* (SIM-001 / SIM-002).

    ``analysis_lines`` defaults to a single transient analysis. Parts may list
    ``Spice_Include`` fields (from the component DB) to emit ``.include`` lines.
    When ``Spice_Subckt`` is set (from DB ``spice_subckt``), the instance line uses
    that subcircuit/model name instead of value-based R/C-style lines (SIM-001).
    """
    if analysis_lines is None:
        analysis_lines = [".tran 1m 100m"]

    logger.info("Bypassing Physical Geometry.")
    logger.info("Generating Computational SPICE Simulation Netlist → %s", output_cir_path)

    try:
        from openhac.circuit import get_default_circuit

        circuit = get_default_circuit()

        parts = sorted(list(getattr(circuit, "parts", []) or []), key=lambda p: natural_key(str(getattr(p, "ref", ""))))
        emitted_refs = set()

        with open(output_cir_path, "w", encoding="utf-8") as f:
            f.write("* OpenHaC SPICE export\n")
            if analysis_lines:
                f.write("* SIM-002 analysis directives:\n")
                for line in analysis_lines:
                    f.write(f"*   {line}\n")

            includes_ordered: list[str] = []
            seen_inc: set[str] = set()
            for part in parts:
                raw = (part.fields.get("Spice_Include") or "").strip()
                if raw and raw not in seen_inc:
                    seen_inc.add(raw)
                    includes_ordered.append(raw)
            for inc in includes_ordered:
                f.write(f".include {inc}\n")

            for line in analysis_lines:
                f.write(f"{line}\n")

            for part in parts:
                spice_id = _resolve_spice_id(part)

                if spice_id in emitted_refs:
                    continue

                nodes_with_num: list[tuple[str, str]] = []
                for p in part.pins:
                    if p.net is not None:
                        net_name = _sanitize_net_name(str(p.net.name))
                        nodes_with_num.append((str(getattr(p, "num", "") or ""), net_name))
                nodes_with_num.sort(key=lambda t: natural_key(t[0]))
                nodes_list = [n for _, n in nodes_with_num]
                nodes = " ".join(nodes_list)

                val = part.value if part.value else part.name
                subckt = (part.fields.get("Spice_Subckt") or "").strip()

                if subckt and nodes_list:
                    sid = spice_id if spice_id.upper().startswith("X") else f"X{spice_id}"
                    f.write(f"{sid} {nodes} {subckt}\n")
                    emitted_refs.add(spice_id)
                elif len(nodes_list) >= 2:
                    f.write(f"{spice_id} {nodes} {val}\n")
                    emitted_refs.add(spice_id)

            f.write(".end\n")
        logger.info("Computational SPICE Engine (OpenHaC Native) completed successfully.")
    except Exception as e:
        logger.error("Native SPICE generation failed: %s", e)
        raise e
