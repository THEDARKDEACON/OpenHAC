"""Strongly-typed Hardware Protocol and Signal primitives (Phase 2).

Provides first-class interfaces for hardware protocols (I2C, SPI, UART, etc.)
with directional type annotations, automatic master/slave inversion, and static
driver contention checking (ERC-001) and domain mismatch checking (ERC-003).
"""

from __future__ import annotations

import copy
import logging
from enum import Enum
from typing import Any, Dict, Generic, Iterator, Optional, Tuple, Type, TypeVar, Union, get_args, get_origin

from openhac.core.domains import DigitalDomain, ElectricalDomain
from openhac.core.exceptions import (
    ERCDriverContentionError,
    ERCDomainMismatchError,
    ProtocolCompatibilityError,
)
from openhac.core.net import Net
from openhac.core.part import Pin

logger = logging.getLogger("openhac.protocol")


class SignalDirection(Enum):
    """Signal port flow directions."""
    INPUT = "input"
    OUTPUT = "output"
    INOUT = "inout"
    PASSIVE = "passive"
    POWER_IN = "power_in"
    POWER_OUT = "power_out"
    TRISTATE = "tristate"
    OPEN_DRAIN = "open_drain"

    def flipped(self) -> SignalDirection:
        """Return the complementary direction for role inversion (master <-> slave)."""
        if self == SignalDirection.INPUT:
            return SignalDirection.OUTPUT
        elif self == SignalDirection.OUTPUT:
            return SignalDirection.INPUT
        elif self == SignalDirection.POWER_IN:
            return SignalDirection.POWER_OUT
        elif self == SignalDirection.POWER_OUT:
            return SignalDirection.POWER_IN
        # INOUT, PASSIVE, TRISTATE, OPEN_DRAIN are bidirectional or self-inverting
        return self

    def is_driver(self) -> bool:
        """True if this endpoint actively drives the line."""
        return self in (SignalDirection.OUTPUT, SignalDirection.POWER_OUT)

    def is_load(self) -> bool:
        """True if this endpoint consumes or observes a signal without driving."""
        return self in (SignalDirection.INPUT, SignalDirection.POWER_IN)


# Directional Type Markers for Signal[Direction] generics
class Input:
    direction = SignalDirection.INPUT


class Output:
    direction = SignalDirection.OUTPUT


class InOut:
    direction = SignalDirection.INOUT


class Passive:
    direction = SignalDirection.PASSIVE


class PowerIn:
    direction = SignalDirection.POWER_IN


class PowerOut:
    direction = SignalDirection.POWER_OUT


class Tristate:
    direction = SignalDirection.TRISTATE


class OpenDrain:
    direction = SignalDirection.OPEN_DRAIN


_DIR_TYPE_MAP: Dict[Any, SignalDirection] = {
    Input: SignalDirection.INPUT,
    Output: SignalDirection.OUTPUT,
    InOut: SignalDirection.INOUT,
    Passive: SignalDirection.PASSIVE,
    PowerIn: SignalDirection.POWER_IN,
    PowerOut: SignalDirection.POWER_OUT,
    Tristate: SignalDirection.TRISTATE,
    OpenDrain: SignalDirection.OPEN_DRAIN,
    "input": SignalDirection.INPUT,
    "output": SignalDirection.OUTPUT,
    "inout": SignalDirection.INOUT,
    "bidirectional": SignalDirection.INOUT,
    "passive": SignalDirection.PASSIVE,
    "power_in": SignalDirection.POWER_IN,
    "power_out": SignalDirection.POWER_OUT,
    "tristate": SignalDirection.TRISTATE,
    "open_drain": SignalDirection.OPEN_DRAIN,
}

D = TypeVar("D")


class Signal(Generic[D]):
    """First-class typed signal endpoint on a protocol or module interface.

    Can be declared as a class attribute on a Protocol:
        sck: Signal[Output] = Signal()

    Or instantiated standalone:
        clk = Signal[Output]("CLK")
    """

    def __init__(
        self,
        name: str = "",
        direction: Optional[Union[SignalDirection, Type[Any], str]] = None,
        *,
        default_pullup: bool = False,
        default_pulldown: bool = False,
        domain: Optional[ElectricalDomain] = None,
        net: Optional[Net] = None,
    ):
        self.name = name
        self.default_pullup = default_pullup
        self.default_pulldown = default_pulldown
        self.domain = domain
        self._net = net
        self.parent_protocol: Optional["Protocol"] = None

        # Resolve direction
        resolved_dir = None
        if direction is not None:
            if isinstance(direction, SignalDirection):
                resolved_dir = direction
            elif direction in _DIR_TYPE_MAP:
                resolved_dir = _DIR_TYPE_MAP[direction]
            elif hasattr(direction, "direction"):
                resolved_dir = getattr(direction, "direction")

        if resolved_dir is None:
            bound_dir = getattr(self, "_bound_direction", None)
            if bound_dir is not None:
                resolved_dir = _DIR_TYPE_MAP.get(bound_dir, bound_dir if isinstance(bound_dir, SignalDirection) else None)

        self.direction: SignalDirection = resolved_dir or SignalDirection.PASSIVE

    def __class_getitem__(cls, item):
        dir_val = _DIR_TYPE_MAP.get(item, getattr(item, "direction", item))
        class _TypedSignal(cls):
            _bound_direction = dir_val
        _TypedSignal.__name__ = f"Signal[{getattr(item, '__name__', str(item))}]"
        _TypedSignal.__qualname__ = f"Signal[{getattr(item, '__qualname__', str(item))}]"
        return _TypedSignal

    @property
    def net(self) -> Net:
        """Get or lazily create the underlying Net for this signal."""
        if self._net is None:
            net_name = self.name or "SIG"
            if self.parent_protocol is not None and self.parent_protocol.name:
                net_name = f"{self.parent_protocol.name}_{self.name.upper()}"
            self._net = Net(net_name)
        return self._net

    @net.setter
    def net(self, value: Net) -> None:
        self._net = value

    def is_connected(self) -> bool:
        """True if this signal is connected to an underlying Net with pins or other signals."""
        if self._net is None:
            return False
        return self._net.is_connected()

    @property
    def pins(self) -> list:
        """Return pins attached to the signal's net."""
        return self.net.pins if self._net is not None else []

    def flipped(self) -> Signal[Any]:
        """Return a copy of this signal with its direction inverted."""
        new_sig = Signal(
            name=self.name,
            direction=self.direction.flipped(),
            default_pullup=self.default_pullup,
            default_pulldown=self.default_pulldown,
            domain=self.domain,
            net=self._net,
        )
        new_sig.parent_protocol = self.parent_protocol
        return new_sig

    def connect(self, target: Any) -> Signal[D]:
        """Connect this signal to a Pin, Net, or another Signal.

        Validates driver contention (ERC-001) and domain mismatch (ERC-003).
        """
        if isinstance(target, Signal):
            # 1. Driver contention check
            if self.direction.is_driver() and target.direction.is_driver():
                raise ERCDriverContentionError(
                    f"ERC-001: Driver contention between {self} ({self.direction.value}) "
                    f"and {target} ({target.direction.value}) on net {self.net.name}"
                )

            # 2. Domain compatibility check
            if self.domain is not None and target.domain is not None:
                compat, reason = self.domain.is_compatible_with(target.domain)
                if not compat:
                    raise ERCDomainMismatchError(
                        f"ERC-003: Electrical domain mismatch between {self} and {target}: {reason}"
                    )

            # Connect underlying nets
            if self.net is not target.net:
                self.net += target.net
                target._net = self.net
            return self

        elif isinstance(target, Pin):
            # 1. Pin type driver contention check
            ptype = str(getattr(target, "pin_type", "passive")).lower()
            if self.direction.is_driver() and ptype in ("output", "power_out"):
                pname = getattr(target, "name", "")
                pref = getattr(getattr(target, "part", None), "refdes", "?")
                raise ERCDriverContentionError(
                    f"ERC-001: Driver contention between signal {self.name} ({self.direction.value}) "
                    f"and pin {pref}.{pname} ({ptype}) on net {self.net.name}"
                )

            # 2. Voltage / domain check
            pin_logic = getattr(target, "logic_level", None)
            pin_vmax = getattr(target, "voltage_rating", None)
            if self.domain is not None and self.domain.nominal_voltage is not None:
                if pin_vmax is not None and self.domain.nominal_voltage > (pin_vmax + 0.3):
                    raise ERCDomainMismatchError(
                        f"ERC-003: Domain mismatch: signal {self.name} nominal voltage "
                        f"{self.domain.nominal_voltage}V exceeds pin max rating {pin_vmax}V"
                    )
                if pin_logic is not None and self.domain.nominal_voltage > (pin_logic + 0.5):
                    raise ERCDomainMismatchError(
                        f"ERC-003: Domain mismatch: signal {self.name} nominal voltage "
                        f"{self.domain.nominal_voltage}V exceeds pin logic level {pin_logic}V"
                    )

            # Connect pin to net
            self.net += target
            return self

        elif isinstance(target, Net):
            self.net += target
            return self

        else:
            raise TypeError(f"Cannot connect Signal to unsupported object of type {type(target)}")

    def __add__(self, other: Any) -> Signal[D]:
        self.connect(other)
        return self

    def __radd__(self, other: Any) -> Signal[D]:
        self.connect(other)
        return self

    def __repr__(self) -> str:
        proto_str = f"{self.parent_protocol.name}." if self.parent_protocol else ""
        return f"Signal({proto_str}{self.name or "unnamed"}, dir={self.direction.value})"


class Protocol:
    """Base class for structured, typed hardware interfaces (I2C, SPI, UART, etc.).

    Subclasses declare signal templates using type annotations or class attributes:
        class SPI(Protocol):
            sck: Signal[Output] = Signal()
            mosi: Signal[Output] = Signal()
            miso: Signal[Input] = Signal()
            cs_n: Signal[Output] = Signal()

    Instances manage live, bound signals attached to the active DesignContext:
        spi_master = SPI("SPI0")
        spi_slave = SPI("SENSOR_SPI").as_peripheral()
        spi_master += spi_slave  # Automatically connects sck->sck, mosi->mosi, miso->miso, cs_n->cs_n!
    """

    _signal_templates: Dict[str, Signal] = {}

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        templates: Dict[str, Signal] = {}

        # 1. Inherit templates from base classes
        for base in reversed(cls.__mro__):
            if issubclass(base, Protocol) and hasattr(base, "_signal_templates"):
                templates.update(base._signal_templates)

        # 2. Inspect class annotations
        annotations = getattr(cls, "__annotations__", {})
        for attr_name, attr_type in annotations.items():
            if attr_name.startswith("_"):
                continue
            orig = get_origin(attr_type)
            is_sig_subclass = isinstance(attr_type, type) and issubclass(attr_type, Signal)
            if orig is Signal or attr_type is Signal or is_sig_subclass:
                args = get_args(attr_type)
                dir_param = args[0] if args else getattr(attr_type, "_bound_direction", SignalDirection.PASSIVE)
                templates[attr_name] = Signal(name=attr_name, direction=dir_param)

        # 3. Inspect class attributes
        for attr_name, attr_val in list(cls.__dict__.items()):
            if isinstance(attr_val, Signal):
                attr_val.name = attr_name
                # If direction was not specified on Signal() constructor, inherit from annotation if available
                if attr_name in templates and attr_val.direction == SignalDirection.PASSIVE:
                    annotated_dir = templates[attr_name].direction
                    if annotated_dir != SignalDirection.PASSIVE:
                        attr_val.direction = annotated_dir
                templates[attr_name] = attr_val

        cls._signal_templates = templates

    def __init__(
        self,
        name: Optional[str] = None,
        *,
        prefix: Optional[str] = None,
        circuit: Optional[Any] = None,
        domain: Optional[ElectricalDomain] = None,
        **signal_bindings: Any,
    ):
        self._name = name or (f"{prefix or self.__class__.__name__}_{id(self) % 10000}")
        self.domain = domain
        self._signals: Dict[str, Signal] = {}

        # Instantiate bound signals from class templates
        for sig_name, template in self._signal_templates.items():
            sig_domain = template.domain or self.domain
            bound_sig = Signal(
                name=sig_name,
                direction=template.direction,
                default_pullup=template.default_pullup,
                default_pulldown=template.default_pulldown,
                domain=sig_domain,
            )
            bound_sig.parent_protocol = self
            self._signals[sig_name] = bound_sig
            setattr(self, sig_name, bound_sig)

        # Apply any initial explicit bindings passed to constructor
        for sig_name, binding in signal_bindings.items():
            if sig_name in self._signals:
                self._signals[sig_name].connect(binding)
            else:
                raise AttributeError(f"{self.__class__.__name__} has no signal named '{sig_name}'")

    @property
    def name(self) -> str:
        return self._name

    @property
    def signals(self) -> Dict[str, Signal]:
        """Dictionary of bound signal instances on this protocol."""
        return dict(self._signals)

    def flipped(self) -> Protocol:
        """Return a role-inverted protocol instance (e.g. Host -> Peripheral)."""
        clone = copy.copy(self)
        clone._name = f"{self._name}_inverted"
        clone._signals = {}
        for sig_name, sig in self._signals.items():
            flipped_sig = sig.flipped()
            flipped_sig.parent_protocol = clone
            clone._signals[sig_name] = flipped_sig
            setattr(clone, sig_name, flipped_sig)
        return clone

    def as_peripheral(self) -> Protocol:
        """Return role-inverted protocol instance for device / peripheral endpoints."""
        return self.flipped()

    def as_device(self) -> Protocol:
        """Synonym for as_peripheral()."""
        return self.as_peripheral()

    def as_host(self) -> Protocol:
        """Return host / controller instance."""
        return self

    def bind(self, **kwargs: Any) -> Protocol:
        """Bind pins, nets, or signals to named protocol signals.

        Example:
            spi.bind(sck=mcu["PA5"], mosi=mcu["PA7"])
        """
        for sig_name, target in kwargs.items():
            if sig_name not in self._signals:
                raise AttributeError(f"{self.__class__.__name__} has no signal named '{sig_name}'")
            self._signals[sig_name].connect(target)
        return self

    def connect(self, other: Protocol) -> None:
        """Connect all matching signals between this protocol and another protocol.

        Validates directional compatibility (ERC-001) and domains (ERC-003).
        """
        if not isinstance(other, Protocol):
            raise TypeError(f"Cannot connect {self.__class__.__name__} to non-Protocol object {other}")

        connected_count = 0
        for sig_name, sig in self._signals.items():
            if sig_name in other._signals:
                sig.connect(other._signals[sig_name])
                connected_count += 1

        if connected_count == 0:
            raise ProtocolCompatibilityError(
                f"Cannot connect {self} to {other}: no overlapping signal names. "
                f"Available signals: {list(self._signals.keys())} vs {list(other._signals.keys())}"
            )

    def __add__(self, other: Protocol) -> Protocol:
        self.connect(other)
        return self

    def __getitem__(self, name: str) -> Signal:
        if name in self._signals:
            return self._signals[name]
        raise KeyError(f"{self.__class__.__name__} has no signal named '{name}'")

    def __contains__(self, name: str) -> bool:
        return name in self._signals

    def __iter__(self) -> Iterator[Signal]:
        return iter(self._signals.values())

    def __len__(self) -> int:
        return len(self._signals)

    def __repr__(self) -> str:
        sig_repr = ", ".join(f"{k}:{v.direction.value}" for k, v in self._signals.items())
        return f"{self.__class__.__name__}({self._name!r}, signals=[{sig_repr}])"


# ---------------------------------------------------------------------------
# Standard Hardware Protocol Implementations
# ---------------------------------------------------------------------------

class I2C(Protocol):
    """Inter-Integrated Circuit (I2C) two-wire bus protocol."""
    scl: Signal[InOut] = Signal(direction=SignalDirection.INOUT, default_pullup=True)
    sda: Signal[InOut] = Signal(direction=SignalDirection.INOUT, default_pullup=True)


class SPI(Protocol):
    """Serial Peripheral Interface (SPI) 4-wire synchronous serial protocol."""
    sck: Signal[Output] = Signal(direction=SignalDirection.OUTPUT)
    mosi: Signal[Output] = Signal(direction=SignalDirection.OUTPUT)
    miso: Signal[Input] = Signal(direction=SignalDirection.INPUT)
    cs_n: Signal[Output] = Signal(direction=SignalDirection.OUTPUT)

    def as_peripheral(self) -> SPI:
        """Returns a role-inverted SPI instance where MOSI/SCK/CS are inputs and MISO is output."""
        return self.flipped()  # type: ignore[return-value]


class UART(Protocol):
    """Universal Asynchronous Receiver-Transmitter (UART) serial interface."""
    tx: Signal[Output] = Signal(direction=SignalDirection.OUTPUT)
    rx: Signal[Input] = Signal(direction=SignalDirection.INPUT)
    rts: Signal[Output] = Signal(direction=SignalDirection.OUTPUT)
    cts: Signal[Input] = Signal(direction=SignalDirection.INPUT)

    def as_peripheral(self) -> UART:
        """Returns a role-inverted UART instance where TX is input and RX is output."""
        return self.flipped()  # type: ignore[return-value]


class SWD(Protocol):
    """ARM Serial Wire Debug (SWD) programming and debug interface."""
    swdio: Signal[InOut] = Signal(direction=SignalDirection.INOUT, default_pullup=True)
    swclk: Signal[Output] = Signal(direction=SignalDirection.OUTPUT)
    swo: Signal[Input] = Signal(direction=SignalDirection.INPUT)
    reset_n: Signal[Output] = Signal(direction=SignalDirection.OUTPUT)

    def as_target(self) -> SWD:
        """Return role-inverted SWD interface for the target microcontroller."""
        return self.flipped()  # type: ignore[return-value]


class JTAG(Protocol):
    """IEEE 1149.1 Joint Test Action Group (JTAG) boundary-scan interface."""
    tck: Signal[Output] = Signal(direction=SignalDirection.OUTPUT)
    tms: Signal[Output] = Signal(direction=SignalDirection.OUTPUT, default_pullup=True)
    tdi: Signal[Output] = Signal(direction=SignalDirection.OUTPUT, default_pullup=True)
    tdo: Signal[Input] = Signal(direction=SignalDirection.INPUT)
    trst_n: Signal[Output] = Signal(direction=SignalDirection.OUTPUT)

    def as_target(self) -> JTAG:
        """Return role-inverted JTAG interface for the target chip."""
        return self.flipped()  # type: ignore[return-value]
