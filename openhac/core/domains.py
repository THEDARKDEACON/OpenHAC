"""Electrical domain definitions and domain compatibility checking (Phase 2).

Defines strongly-typed electrical domains (power, digital logic, analog, differential, RF)
with voltage ranges, tolerances, current limits, and impedance constraints.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple


class DomainKind(Enum):
    """Broad categories of electrical domains."""
    DIGITAL_LOGIC = "digital_logic"
    POWER = "power"
    ANALOG = "analog"
    DIFFERENTIAL = "differential"
    RF = "rf"


@dataclass(frozen=True)
class ElectricalDomain:
    """Strongly typed electrical specification for a signal, pin, net, or rail.

    Attributes:
        kind: Classification (DIGITAL_LOGIC, POWER, ANALOG, DIFFERENTIAL, RF).
        nominal_voltage: Typical operating voltage in Volts (e.g., 3.3, 5.0, 1.8).
        voltage_tolerance_pct: Allowable voltage deviation percentage (+/- %).
        min_voltage: Absolute minimum allowable voltage (Volts).
        max_voltage: Absolute maximum allowable voltage (Volts).
        max_current_a: Maximum continuous current in Amperes.
        impedance_target_ohms: Characteristic or differential target impedance.
        logic_standard: Specific logic standard name (e.g., 'LVCMOS_3V3', 'LVDS', 'USB_FS').
        name: Optional descriptive label (e.g., 'VCC_3V3', 'SPI_DOMAIN').
    """
    kind: DomainKind
    nominal_voltage: Optional[float] = None
    voltage_tolerance_pct: float = 5.0
    min_voltage: Optional[float] = None
    max_voltage: Optional[float] = None
    max_current_a: Optional[float] = None
    impedance_target_ohms: Optional[float] = None
    logic_standard: Optional[str] = None
    name: str = ""

    def effective_voltage_range(self) -> Tuple[Optional[float], Optional[float]]:
        """Return (min_voltage, max_voltage) taking nominal voltage and tolerance into account."""
        v_min = self.min_voltage
        v_max = self.max_voltage

        if self.nominal_voltage is not None:
            tol_factor = self.voltage_tolerance_pct / 100.0
            calc_min = self.nominal_voltage * (1.0 - tol_factor)
            calc_max = self.nominal_voltage * (1.0 + tol_factor)
            if v_min is None:
                v_min = calc_min
            if v_max is None:
                v_max = calc_max

        return (v_min, v_max)

    def is_compatible_with(self, other: ElectricalDomain) -> Tuple[bool, Optional[str]]:
        """Verify whether this domain is electrically compatible with another domain.

        Returns:
            (is_compatible, reason_if_incompatible)
        """
        # 1. Kind compatibility
        if self.kind == DomainKind.POWER and other.kind == DomainKind.POWER:
            if self.nominal_voltage is not None and other.nominal_voltage is not None:
                if abs(self.nominal_voltage - other.nominal_voltage) > 0.05 * max(self.nominal_voltage, other.nominal_voltage):
                    return False, (
                        f"Power rail voltage mismatch: {self.nominal_voltage}V vs {other.nominal_voltage}V "
                        f"(shorting different power rails)"
                    )
            return True, None

        if self.kind == DomainKind.DIGITAL_LOGIC and other.kind == DomainKind.DIGITAL_LOGIC:
            if self.nominal_voltage is not None and other.nominal_voltage is not None:
                # Driver vs receiver logic level check
                _, self_max = self.effective_voltage_range()
                other_min, other_max = other.effective_voltage_range()

                # If self exceeds other max by more than 0.3V (standard CMOS margin)
                if other_max is not None and self.nominal_voltage > (other_max + 0.3):
                    return False, (
                        f"Digital logic level mismatch: {self.nominal_voltage}V driver exceeds receiver "
                        f"maximum safe rating of {other_max:.2f}V"
                    )

                # If driver is too low to guarantee high logic level for receiver (e.g. 1.8V driving 5V input)
                if self.nominal_voltage < 0.65 * other.nominal_voltage:
                    return False, (
                        f"Digital logic level mismatch: {self.nominal_voltage}V driver is insufficient to "
                        f"guarantee high logic level for {other.nominal_voltage}V receiver"
                    )
            return True, None

        if self.kind == DomainKind.DIFFERENTIAL and other.kind == DomainKind.DIFFERENTIAL:
            if self.impedance_target_ohms is not None and other.impedance_target_ohms is not None:
                diff_pct = abs(self.impedance_target_ohms - other.impedance_target_ohms) / self.impedance_target_ohms
                if diff_pct > 0.15:
                    return False, (
                        f"Differential impedance mismatch: {self.impedance_target_ohms}Ω vs "
                        f"{other.impedance_target_ohms}Ω (>15% deviation)"
                    )
            return True, None

        # Cross-kind checks: Power connecting to Digital Logic (e.g. VCC pullup or power pin)
        if (self.kind == DomainKind.POWER and other.kind == DomainKind.DIGITAL_LOGIC) or (
            self.kind == DomainKind.DIGITAL_LOGIC and other.kind == DomainKind.POWER
        ):
            pwr = self if self.kind == DomainKind.POWER else other
            logic = other if self.kind == DomainKind.POWER else self
            if pwr.nominal_voltage is not None and logic.nominal_voltage is not None:
                _, logic_max = logic.effective_voltage_range()
                if logic_max is not None and pwr.nominal_voltage > (logic_max + 0.3):
                    return False, (
                        f"Power voltage {pwr.nominal_voltage}V exceeds digital logic safe voltage {logic_max:.2f}V"
                    )
            return True, None

        # Allow analog and passive connections unless explicit voltage clash
        if self.nominal_voltage is not None and other.max_voltage is not None:
            if self.nominal_voltage > other.max_voltage:
                return False, f"Nominal voltage {self.nominal_voltage}V exceeds maximum safe voltage {other.max_voltage}V"

        return True, None


def PowerDomain(
    voltage: float,
    *,
    max_current_a: Optional[float] = None,
    tolerance_pct: float = 5.0,
    name: str = "",
) -> ElectricalDomain:
    """Create a power domain specification (e.g. 3.3V, 5.0V, 12.0V)."""
    return ElectricalDomain(
        kind=DomainKind.POWER,
        nominal_voltage=float(voltage),
        voltage_tolerance_pct=float(tolerance_pct),
        max_current_a=float(max_current_a) if max_current_a is not None else None,
        name=name or f"{voltage}V_Power",
    )


def DigitalDomain(
    voltage: float = 3.3,
    *,
    standard: Optional[str] = None,
    tolerance_pct: float = 10.0,
    max_voltage: Optional[float] = None,
    min_voltage: Optional[float] = None,
    name: str = "",
) -> ElectricalDomain:
    """Create a digital logic domain specification (e.g. LVCMOS 3.3V, 1.8V)."""
    std = standard or f"LVCMOS_{str(voltage).replace('.', 'V')}"
    return ElectricalDomain(
        kind=DomainKind.DIGITAL_LOGIC,
        nominal_voltage=float(voltage),
        voltage_tolerance_pct=float(tolerance_pct),
        max_voltage=float(max_voltage) if max_voltage is not None else float(voltage) * 1.15,
        min_voltage=float(min_voltage) if min_voltage is not None else -0.3,
        logic_standard=std,
        name=name or std,
    )


def AnalogDomain(
    min_voltage: float = 0.0,
    max_voltage: float = 3.3,
    *,
    nominal_voltage: Optional[float] = None,
    impedance_target_ohms: Optional[float] = None,
    name: str = "",
) -> ElectricalDomain:
    """Create an analog signal domain specification."""
    return ElectricalDomain(
        kind=DomainKind.ANALOG,
        nominal_voltage=float(nominal_voltage) if nominal_voltage is not None else None,
        min_voltage=float(min_voltage),
        max_voltage=float(max_voltage),
        impedance_target_ohms=float(impedance_target_ohms) if impedance_target_ohms is not None else None,
        name=name or "Analog",
    )


def DifferentialPair(
    impedance_ohms: float = 100.0,
    *,
    standard: Optional[str] = None,
    nominal_voltage: Optional[float] = None,
    name: str = "",
) -> ElectricalDomain:
    """Create a differential pair specification (e.g. 100Ω Ethernet/LVDS or 90Ω USB)."""
    return ElectricalDomain(
        kind=DomainKind.DIFFERENTIAL,
        nominal_voltage=float(nominal_voltage) if nominal_voltage is not None else None,
        impedance_target_ohms=float(impedance_ohms),
        logic_standard=standard,
        name=name or (standard or f"Diff_{impedance_ohms}ohm"),
    )


def RFDomain(
    frequency_hz: Optional[float] = None,
    *,
    impedance_ohms: float = 50.0,
    name: str = "",
) -> ElectricalDomain:
    """Create an RF trace/signal specification (typically 50Ω single-ended)."""
    return ElectricalDomain(
        kind=DomainKind.RF,
        impedance_target_ohms=float(impedance_ohms),
        name=name or "RF_50ohm",
    )
