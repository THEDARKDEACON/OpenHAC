"""OpenHaC Compiler Pipeline, Elaboration, Synthesis Solvers, and Backend Generators."""

from .elaborator import elaborate
from .fpga_exporter import (
    PinMapping,
    VerilogPort,
    export_fpga_bundle,
    export_gowin_cst,
    export_lattice_pdc,
    export_quartus_qsf,
    export_vivado_xdc,
    parse_verilog_file,
    parse_verilog_ports,
    resolve_fpga_pin_mappings,
)
from .kicad_rules import (
    export_circuit_dru,
    extract_dsn_differential_pairs,
    generate_kicad_dru,
)
from .parametric_solvers import (
    BuckSolution,
    DividerSolution,
    FilterSolution,
    LCSolution,
    RCLowPassFilterModule,
    VoltageDividerModule,
    find_closest_e_series,
    format_capacitance,
    format_inductance,
    format_resistance,
    get_e_series,
    solve_buck_converter,
    solve_e_series_divider,
    solve_lc_resonance,
    solve_rc_highpass,
    solve_rc_lowpass,
)

__all__ = [
    "elaborate",
    # Solvers
    "get_e_series",
    "find_closest_e_series",
    "format_resistance",
    "format_capacitance",
    "format_inductance",
    "solve_e_series_divider",
    "solve_rc_lowpass",
    "solve_rc_highpass",
    "solve_lc_resonance",
    "solve_buck_converter",
    "DividerSolution",
    "FilterSolution",
    "LCSolution",
    "BuckSolution",
    "VoltageDividerModule",
    "RCLowPassFilterModule",
    # KiCad Rules
    "generate_kicad_dru",
    "export_circuit_dru",
    "extract_dsn_differential_pairs",
    # FPGA Co-Design
    "parse_verilog_ports",
    "parse_verilog_file",
    "VerilogPort",
    "PinMapping",
    "resolve_fpga_pin_mappings",
    "export_vivado_xdc",
    "export_gowin_cst",
    "export_lattice_pdc",
    "export_quartus_qsf",
    "export_fpga_bundle",
]
