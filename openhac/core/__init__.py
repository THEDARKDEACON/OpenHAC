# OpenHaC Core - Hardware as Code
# Native implementation without SKiDL dependency

from .board import Board
from .base import Component, Module, Interface
from .part import Part, Pin
from .net import Net, Bus
from .circuit import (
    Circuit,
    DesignContext,
    default_circuit,
    get_active_circuit,
    get_active_design_context,
    reset_default_circuit,
)

from .domains import (
    AnalogDomain,
    DifferentialPair,
    DigitalDomain,
    DomainKind,
    ElectricalDomain,
    PowerDomain,
    RFDomain,
)
from .constraints import (
    ClearanceConstraint,
    Constraint,
    DifferentialPairConstraint,
    KeepoutConstraint,
    LengthMatchConstraint,
    TraceWidthConstraint,
    constraint,
    evaluate_constraints,
)
from .exceptions import (
    ERCDomainMismatchError,
    ERCDriverContentionError,
    ERCFloatingInputError,
    ERCMissingTerminationError,
    ProtocolCompatibilityError,
)
from .protocol import (
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

__all__ = [
    "Board",
    "Component",
    "Module",
    "Interface",
    "Part",
    "Pin",
    "Net",
    "Bus",
    "Circuit",
    "DesignContext",
    "default_circuit",
    "get_active_circuit",
    "get_active_design_context",
    "reset_default_circuit",
    # Protocols & Signals (Phase 2)
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
    # Domains (Phase 2)
    "ElectricalDomain",
    "DomainKind",
    "PowerDomain",
    "DigitalDomain",
    "AnalogDomain",
    "DifferentialPair",
    "RFDomain",
    # ERC Errors
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
    "evaluate_constraints",
]
