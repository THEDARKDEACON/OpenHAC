"""Interface — named signal groups for module-to-module wiring.

Extracted from ``base.py`` to keep each abstraction in its own file.
"""

from __future__ import annotations


class Interface:
    """A named group of nets that form a logical interface (e.g. SPI, I2C).

    Interfaces are declared on :class:`~openhac.core.module.Module` instances
    and connected at the :class:`~openhac.core.board.Board` level.
    """

    def __init__(
        self,
        name: str,
        *signals,
        logic_level: float | None = None,
        voltage_rating: float | None = None,
        **named_signals,
    ):
        self.name = name
        self.signals = list(signals)
        self.named_signals = named_signals
        self.logic_level = logic_level
        self.voltage_rating = voltage_rating
        # Also store named signals as attributes for easy access
        for n, s in named_signals.items():
            setattr(self, n, s)

    def set_semantics(
        self,
        logic_level: float | None = None,
        voltage_rating: float | None = None,
    ) -> Interface:
        """Apply semantic properties to all pins/nets in this interface."""
        if logic_level is not None:
            self.logic_level = logic_level
        if voltage_rating is not None:
            self.voltage_rating = voltage_rating

        # Propagate to underlying signals if they support it
        for sig in self.signals + list(self.named_signals.values()):
            if hasattr(sig, "set_semantics"):
                sig.set_semantics(logic_level=logic_level, voltage_rating=voltage_rating)
        return self

    def connect(self, other_interface: Interface) -> None:
        """Merge each signal pair between *self* and *other_interface*."""
        # Connect positional signals
        for sig1, sig2 in zip(self.signals, other_interface.signals):
            sig1 += sig2
        
        # Connect named signals
        for name, sig1 in self.named_signals.items():
            if hasattr(other_interface, name):
                sig2 = getattr(other_interface, name)
                sig1 += sig2

    def __getitem__(self, key):
        if isinstance(key, int):
            return self.signals[key]
        return self.named_signals[key]
