"""OpenHaC — Open Hardware-as-Code compiler and HDL."""

from openhac.core.context import (
    DesignContext,
    get_active_circuit,
    get_active_design_context,
)
from openhac.core.domains import (
    AnalogDomain,
    DifferentialPair,
    DigitalDomain,
    DomainKind,
    ElectricalDomain,
    PowerDomain,
    RFDomain,
)
from openhac.core.exceptions import (
    ERCDomainMismatchError,
    ERCDriverContentionError,
    ERCFloatingInputError,
    ERCMissingTerminationError,
    ERCUnconnectedPinError,
    OpenHaCError,
    ProtocolCompatibilityError,
)
from openhac.core.protocol import (
    I2C,
    JTAG,
    SPI,
    SWD,
    UART,
    InOut,
    Input,
    OpenDrain,
    Output,
    Passive,
    PowerIn,
    PowerOut,
    Protocol,
    Signal,
    SignalDirection,
    Tristate,
)
from openhac.compiler.elaborator import elaborate
from openhac.compiler.fpga_exporter import (
    export_fpga_bundle,
    export_gowin_cst,
    export_vivado_xdc,
    parse_verilog_ports,
)
from openhac.compiler.kicad_rules import generate_kicad_dru
from openhac.compiler.parametric_solvers import (
    RCLowPassFilterModule,
    VoltageDividerModule,
    solve_buck_converter,
    solve_e_series_divider,
    solve_lc_resonance,
    solve_rc_highpass,
    solve_rc_lowpass,
)
from openhac.core.constraints import (
    ClearanceConstraint,
    Constraint,
    DifferentialPairConstraint,
    KeepoutConstraint,
    LengthMatchConstraint,
    TraceWidthConstraint,
    constraint,
)
from openhac.ir import (
    BusNode,
    CircuitIR,
    ComponentNode,
    ConstraintNode,
    ModuleNode,
    NetNode,
    PinNode,
)

__all__ = [
    "CircuitIR",
    "ModuleNode",
    "ComponentNode",
    "PinNode",
    "NetNode",
    "BusNode",
    "ConstraintNode",
    "elaborate",
    "DesignContext",
    "get_active_circuit",
    "get_active_design_context",
    # Protocols & Signals
    "Protocol",
    "Signal",
    "SignalDirection",
    "Input",
    "Output",
    "InOut",
    "Passive",
    "PowerIn",
    "PowerOut",
    "Tristate",
    "OpenDrain",
    "I2C",
    "SPI",
    "UART",
    "SWD",
    "JTAG",
    # Domains
    "ElectricalDomain",
    "DomainKind",
    "PowerDomain",
    "DigitalDomain",
    "AnalogDomain",
    "DifferentialPair",
    "RFDomain",
    # ERC
    "OpenHaCError",
    "ERCUnconnectedPinError",
    "ERCDriverContentionError",
    "ERCFloatingInputError",
    "ERCDomainMismatchError",
    "ERCMissingTerminationError",
    "ProtocolCompatibilityError",
    # Constraints (Phase 4)
    "Constraint",
    "DifferentialPairConstraint",
    "ClearanceConstraint",
    "TraceWidthConstraint",
    "LengthMatchConstraint",
    "KeepoutConstraint",
    "constraint",
    # Parametric Solvers (Phase 4)
    "solve_e_series_divider",
    "solve_rc_lowpass",
    "solve_rc_highpass",
    "solve_lc_resonance",
    "solve_buck_converter",
    "VoltageDividerModule",
    "RCLowPassFilterModule",
    # KiCad Rules (Phase 4)
    "generate_kicad_dru",
    # FPGA Co-Design (Phase 4)
    "parse_verilog_ports",
    "export_vivado_xdc",
    "export_gowin_cst",
    "export_fpga_bundle",
]
