"""
Parametric E-Series Synthesis Solvers for OpenHaC v2.

Provides mathematically grounded synthesis algorithms to automatically
select optimal standard passive components (IEC 60063 E6/E12/E24/E96/E192)
for voltage dividers, RC/LC filters, and power converter loops.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Union

from openhac.core.base import Component, Module
from openhac.core.part import Part, Pin
from openhac.core.net import Net

# -------------------------------------------------------------------------
# IEC 60063 Standard Decade Base Values
# -------------------------------------------------------------------------

E6_BASE: Tuple[float, ...] = (
    1.0, 1.5, 2.2, 3.3, 4.7, 6.8,
)

E12_BASE: Tuple[float, ...] = (
    1.0, 1.2, 1.5, 1.8, 2.2, 2.7, 3.3, 3.9, 4.7, 5.6, 6.8, 8.2,
)

E24_BASE: Tuple[float, ...] = (
    1.0, 1.1, 1.2, 1.3, 1.5, 1.6, 1.8, 2.0, 2.2, 2.4, 2.7, 3.0,
    3.3, 3.6, 3.9, 4.3, 4.7, 5.1, 5.6, 6.2, 6.8, 7.5, 8.2, 9.1,
)

E96_BASE: Tuple[float, ...] = (
    1.00, 1.02, 1.05, 1.07, 1.10, 1.13, 1.15, 1.18, 1.21, 1.24,
    1.27, 1.30, 1.33, 1.37, 1.40, 1.43, 1.47, 1.50, 1.54, 1.58,
    1.62, 1.65, 1.69, 1.74, 1.78, 1.82, 1.87, 1.91, 1.96, 2.00,
    2.05, 2.10, 2.15, 2.21, 2.26, 2.32, 2.37, 2.43, 2.49, 2.55,
    2.61, 2.67, 2.74, 2.80, 2.87, 2.94, 3.01, 3.09, 3.16, 3.24,
    3.32, 3.40, 3.48, 3.57, 3.65, 3.74, 3.83, 3.92, 4.02, 4.12,
    4.22, 4.32, 4.42, 4.53, 4.64, 4.75, 4.87, 4.99, 5.11, 5.23,
    5.36, 5.49, 5.62, 5.76, 5.90, 6.04, 6.19, 6.34, 6.49, 6.65,
    6.81, 6.98, 7.15, 7.32, 7.50, 7.68, 7.87, 8.06, 8.25, 8.45,
    8.66, 8.87, 9.09, 9.31, 9.53, 9.76,
)

E_SERIES_MAP: Dict[str, Tuple[float, ...]] = {
    "E6": E6_BASE,
    "E12": E12_BASE,
    "E24": E24_BASE,
    "E96": E96_BASE,
}


def get_e_series(
    series: str = "E24",
    min_val: float = 1.0,
    max_val: float = 1e7,
) -> List[float]:
    """Generate sorted decade values for the specified IEC E-series within [min_val, max_val]."""
    series_key = series.upper().strip()
    if series_key not in E_SERIES_MAP:
        raise ValueError(
            f"Unsupported E-series {series!r}. Supported series: {list(E_SERIES_MAP.keys())}"
        )
    base_values = E_SERIES_MAP[series_key]

    # Calculate decade limits
    dec_start = int(math.floor(math.log10(min_val))) - 1
    dec_end = int(math.ceil(math.log10(max_val))) + 1

    values: List[float] = []
    seen = set()
    for dec in range(dec_start, dec_end + 1):
        mult = 10.0 ** dec
        for base in base_values:
            raw_val = base * mult
            # Clean floating point representation
            cleaned_val = float(f"{raw_val:.6g}")
            if min_val <= cleaned_val <= max_val and cleaned_val not in seen:
                seen.add(cleaned_val)
                values.append(cleaned_val)

    return sorted(values)


def find_closest_e_series(
    target: float,
    series: str = "E24",
    min_val: float = 1e-12,
    max_val: float = 1e8,
) -> Tuple[float, float]:
    """Find the closest standard E-series value to a target.
    
    Returns:
        (closest_standard_value, absolute_error_percentage)
    """
    if target <= 0:
        raise ValueError(f"Target value must be positive, got {target}")
    
    candidates = get_e_series(series=series, min_val=min_val, max_val=max_val)
    if not candidates:
        raise ValueError(f"No candidate values found in series {series} within [{min_val}, {max_val}]")
    
    best_val = min(candidates, key=lambda v: abs(v - target))
    err_pct = abs(best_val - target) / target * 100.0
    return best_val, err_pct


# -------------------------------------------------------------------------
# Engineering Unit String Formatting
# -------------------------------------------------------------------------

def format_resistance(val: float) -> str:
    """Format resistance value in standard engineering notation (e.g. 4.7k, 100R, 1M)."""
    if val >= 1e6:
        v = val / 1e6
        return f"{int(v)}M" if v.is_integer() else f"{v:.2f}".rstrip("0").rstrip(".") + "M"
    elif val >= 1e3:
        v = val / 1e3
        return f"{int(v)}k" if v.is_integer() else f"{v:.2f}".rstrip("0").rstrip(".") + "k"
    else:
        return f"{int(val)}R" if float(val).is_integer() else f"{val:.2f}".rstrip("0").rstrip(".") + "R"


def _format_unit(v: float, unit: str) -> str:
    cleaned = round(v, 4)
    if cleaned.is_integer():
        return f"{int(cleaned)}{unit}"
    else:
        s = f"{cleaned:.4f}".rstrip("0").rstrip(".")
        return f"{s}{unit}"


def format_capacitance(val: float) -> str:
    """Format capacitance value in engineering notation (e.g. 100nF, 10uF, 22pF)."""
    if val >= 1e-3:
        return _format_unit(val * 1e3, "mF")
    elif val >= 1e-6:
        return _format_unit(val * 1e6, "uF")
    elif val >= 1e-9:
        return _format_unit(val * 1e9, "nF")
    else:
        return _format_unit(val * 1e12, "pF")


def format_inductance(val: float) -> str:
    """Format inductance value in engineering notation (e.g. 10uH, 4.7nH, 1mH)."""
    if val >= 1.0:
        return _format_unit(val, "H")
    elif val >= 1e-3:
        return _format_unit(val * 1e3, "mH")
    elif val >= 1e-6:
        return _format_unit(val * 1e6, "uH")
    else:
        return _format_unit(val * 1e9, "nH")


# -------------------------------------------------------------------------
# 1. Voltage Divider Solver
# -------------------------------------------------------------------------

@dataclass(frozen=True)
class DividerSolution:
    r1: float
    r2: float
    vin: float
    vout_target: float
    vout_actual: float
    error_pct: float
    quiescent_current_a: float
    series: str

    @property
    def r1_formatted(self) -> str:
        return format_resistance(self.r1)

    @property
    def r2_formatted(self) -> str:
        return format_resistance(self.r2)


def solve_e_series_divider(
    vin: float,
    vout: float,
    i_max: float = 1e-3,
    min_resistance: float = 100.0,
    max_resistance: float = 1e6,
    series: str = "E96",
    target_tolerance_pct: Optional[float] = None,
) -> DividerSolution:
    """Solve for optimal standard decade resistor values in a voltage divider.
    
    Divider topology:
        Vin --- [ R1 ] --- Vout --- [ R2 ] --- GND
        
    Formula:
        Vout = Vin * (R2 / (R1 + R2))
        I_q  = Vin / (R1 + R2) <= i_max
        
    Args:
        vin: Input voltage (V).
        vout: Target output voltage (V).
        i_max: Maximum quiescent current draw allowed (A). Default 1mA.
        min_resistance: Minimum allowed resistor value (Ohms).
        max_resistance: Maximum allowed resistor value (Ohms).
        series: IEC series ("E12", "E24", "E96").
        target_tolerance_pct: If provided, raises ValueError if best error exceeds this threshold.
        
    Returns:
        DividerSolution dataclass.
    """
    if vout <= 0 or vout >= vin:
        raise ValueError(
            f"Vout ({vout}V) must be strictly between 0 and Vin ({vin}V)"
        )
    if vin <= 0:
        raise ValueError(f"Vin ({vin}V) must be positive")

    target_ratio = vout / vin  # R2 / (R1 + R2)
    min_total_r = vin / i_max if i_max > 0 else min_resistance * 2

    candidates = get_e_series(series=series, min_val=min_resistance, max_val=max_resistance)

    best_r1: Optional[float] = None
    best_r2: Optional[float] = None
    best_error = float("inf")
    best_vout = 0.0
    best_iq = 0.0

    # Search for optimal R1, R2
    for r1 in candidates:
        # Ideal R2: target_ratio = R2 / (R1 + R2) => R2 = R1 * target_ratio / (1 - target_ratio)
        ideal_r2 = r1 * target_ratio / (1.0 - target_ratio)
        if ideal_r2 < min_resistance or ideal_r2 > max_resistance:
            continue

        # Find closest candidate in series
        r2, _ = find_closest_e_series(ideal_r2, series=series, min_val=min_resistance, max_val=max_resistance)
        total_r = r1 + r2
        iq = vin / total_r

        # Quiescent current preference:
        current_penalty = 1.0 if total_r >= min_total_r else 5.0

        v_calc = vin * (r2 / total_r)
        err = (abs(v_calc - vout) / vout * 100.0) * current_penalty

        if err < best_error:
            best_error = err
            best_r1 = r1
            best_r2 = r2
            best_vout = v_calc
            best_iq = iq

    if best_r1 is None or best_r2 is None:
        raise ValueError(
            f"Unable to synthesize divider for Vin={vin}V, Vout={vout}V with series {series} "
            f"and resistance range [{min_resistance}, {max_resistance}]."
        )

    actual_err_pct = abs(best_vout - vout) / vout * 100.0
    if target_tolerance_pct is not None and actual_err_pct > target_tolerance_pct:
        raise ValueError(
            f"Synthesized divider error {actual_err_pct:.2f}% exceeds tolerance threshold {target_tolerance_pct}%"
        )

    return DividerSolution(
        r1=best_r1,
        r2=best_r2,
        vin=vin,
        vout_target=vout,
        vout_actual=best_vout,
        error_pct=actual_err_pct,
        quiescent_current_a=best_iq,
        series=series.upper(),
    )


# -------------------------------------------------------------------------
# 2. Passive RC Filter Solvers
# -------------------------------------------------------------------------

@dataclass(frozen=True)
class FilterSolution:
    fc_target: float
    fc_actual: float
    error_pct: float
    r_val: float
    c_val: float
    filter_type: str
    series_r: str
    series_c: str

    @property
    def r_formatted(self) -> str:
        return format_resistance(self.r_val)

    @property
    def c_formatted(self) -> str:
        return format_capacitance(self.c_val)


def solve_rc_filter(
    fc: float,
    filter_type: str = "lowpass",
    c_preferred: Optional[float] = None,
    series_r: str = "E24",
    series_c: str = "E12",
    min_r: float = 100.0,
    max_r: float = 1e6,
    min_c: float = 1e-12,
    max_c: float = 1e-4,
) -> FilterSolution:
    """Solve for standard R and C values for an RC filter at cutoff frequency fc.
    
    Formula:
        fc = 1 / (2 * pi * R * C)  =>  R * C = 1 / (2 * pi * fc)
    """
    if fc <= 0:
        raise ValueError(f"Cutoff frequency fc must be positive, got {fc} Hz")

    target_rc = 1.0 / (2.0 * math.pi * fc)

    if c_preferred is not None:
        ideal_r = target_rc / c_preferred
        r_val, _ = find_closest_e_series(ideal_r, series=series_r, min_val=min_r, max_val=max_r)
        c_val = c_preferred
        fc_actual = 1.0 / (2.0 * math.pi * r_val * c_val)
        err_pct = abs(fc_actual - fc) / fc * 100.0
        return FilterSolution(
            fc_target=fc,
            fc_actual=fc_actual,
            error_pct=err_pct,
            r_val=r_val,
            c_val=c_val,
            filter_type=filter_type,
            series_r=series_r.upper(),
            series_c=series_c.upper(),
        )

    # Search through standard capacitor values
    c_candidates = get_e_series(series=series_c, min_val=min_c, max_val=max_c)
    best_r = None
    best_c = None
    best_err = float("inf")
    best_fc = 0.0

    for c in c_candidates:
        ideal_r = target_rc / c
        if ideal_r < min_r or ideal_r > max_r:
            continue
        r, _ = find_closest_e_series(ideal_r, series=series_r, min_val=min_r, max_val=max_r)
        actual_fc = 1.0 / (2.0 * math.pi * r * c)
        err = abs(actual_fc - fc) / fc * 100.0
        if err < best_err:
            best_err = err
            best_r = r
            best_c = c
            best_fc = actual_fc

    if best_r is None or best_c is None:
        raise ValueError(
            f"Unable to find valid RC filter for fc={fc} Hz in specified range."
        )

    return FilterSolution(
        fc_target=fc,
        fc_actual=best_fc,
        error_pct=best_err,
        r_val=best_r,
        c_val=best_c,
        filter_type=filter_type,
        series_r=series_r.upper(),
        series_c=series_c.upper(),
    )


def solve_rc_lowpass(
    fc: float,
    c_preferred: Optional[float] = None,
    series_r: str = "E24",
    series_c: str = "E12",
) -> FilterSolution:
    """Solve for passive RC lowpass filter component values."""
    return solve_rc_filter(
        fc=fc,
        filter_type="lowpass",
        c_preferred=c_preferred,
        series_r=series_r,
        series_c=series_c,
    )


def solve_rc_highpass(
    fc: float,
    c_preferred: Optional[float] = None,
    series_r: str = "E24",
    series_c: str = "E12",
) -> FilterSolution:
    """Solve for passive RC highpass filter component values."""
    return solve_rc_filter(
        fc=fc,
        filter_type="highpass",
        c_preferred=c_preferred,
        series_r=series_r,
        series_c=series_c,
    )


# -------------------------------------------------------------------------
# 3. LC Resonance & Filter Solvers
# -------------------------------------------------------------------------

@dataclass(frozen=True)
class LCSolution:
    f0_target: float
    f0_actual: float
    error_pct: float
    l_val: float
    c_val: float
    characteristic_impedance_z0: float
    series_l: str
    series_c: str

    @property
    def l_formatted(self) -> str:
        return format_inductance(self.l_val)

    @property
    def c_formatted(self) -> str:
        return format_capacitance(self.c_val)


def solve_lc_resonance(
    f0: float,
    l_preferred: Optional[float] = None,
    series_l: str = "E12",
    series_c: str = "E12",
    min_l: float = 1e-9,
    max_l: float = 1.0,
    min_c: float = 1e-12,
    max_c: float = 1e-4,
) -> LCSolution:
    """Solve for standard L and C values for resonance/cutoff frequency f0.
    
    Formula:
        f0 = 1 / (2 * pi * sqrt(L * C))  =>  L * C = 1 / ((2 * pi * f0)^2)
        Z0 = sqrt(L / C)
    """
    if f0 <= 0:
        raise ValueError(f"Resonant frequency f0 must be positive, got {f0}")

    target_lc = 1.0 / ((2.0 * math.pi * f0) ** 2)

    if l_preferred is not None:
        ideal_c = target_lc / l_preferred
        c_val, _ = find_closest_e_series(ideal_c, series=series_c, min_val=min_c, max_val=max_c)
        l_val = l_preferred
        f0_actual = 1.0 / (2.0 * math.pi * math.sqrt(l_val * c_val))
        err_pct = abs(f0_actual - f0) / f0 * 100.0
        z0 = math.sqrt(l_val / c_val)
        return LCSolution(
            f0_target=f0,
            f0_actual=f0_actual,
            error_pct=err_pct,
            l_val=l_val,
            c_val=c_val,
            characteristic_impedance_z0=z0,
            series_l=series_l.upper(),
            series_c=series_c.upper(),
        )

    l_candidates = get_e_series(series=series_l, min_val=min_l, max_val=max_l)
    best_l = None
    best_c = None
    best_err = float("inf")
    best_f0 = 0.0

    for l in l_candidates:
        ideal_c = target_lc / l
        if ideal_c < min_c or ideal_c > max_c:
            continue
        c, _ = find_closest_e_series(ideal_c, series=series_c, min_val=min_c, max_val=max_c)
        actual_f0 = 1.0 / (2.0 * math.pi * math.sqrt(l * c))
        err = abs(actual_f0 - f0) / f0 * 100.0
        if err < best_err:
            best_err = err
            best_l = l
            best_c = c
            best_f0 = actual_f0

    if best_l is None or best_c is None:
        raise ValueError(f"Unable to find valid LC solution for f0={f0} Hz")

    z0 = math.sqrt(best_l / best_c)
    return LCSolution(
        f0_target=f0,
        f0_actual=best_f0,
        error_pct=best_err,
        l_val=best_l,
        c_val=best_c,
        characteristic_impedance_z0=z0,
        series_l=series_l.upper(),
        series_c=series_c.upper(),
    )


# -------------------------------------------------------------------------
# 4. Buck Converter Passive Sizing Solver
# -------------------------------------------------------------------------

@dataclass(frozen=True)
class BuckSolution:
    vin_min: float
    vin_max: float
    vout: float
    iout_max: float
    fsw_hz: float
    l_min_henry: float
    l_recommended_henry: float
    c_out_min_farad: float
    c_out_recommended_farad: float
    i_peak_a: float
    i_sat_min_a: float
    duty_cycle_nom: float

    @property
    def l_formatted(self) -> str:
        return format_inductance(self.l_recommended_henry)

    @property
    def c_out_formatted(self) -> str:
        return format_capacitance(self.c_out_recommended_farad)


def solve_buck_converter(
    vin_min: float,
    vin_max: float,
    vout: float,
    iout_max: float,
    fsw_hz: float,
    ripple_ratio: float = 0.3,
    vout_ripple_max_v: float = 0.03,
    series_l: str = "E12",
    series_c: str = "E12",
) -> BuckSolution:
    """Size inductor and output capacitor for a synchronous/asynchronous buck converter.
    
    Formulas:
        delta_I_L = ripple_ratio * I_out_max
        L_min = (Vout * (Vin_max - Vout)) / (delta_I_L * fsw * Vin_max)
        I_peak = I_out_max + (delta_I_L / 2)
        I_sat_min >= 1.3 * I_peak
        C_out_min = delta_I_L / (8 * fsw * vout_ripple_max_v)
    """
    if not (0 < vout < vin_min <= vin_max):
        raise ValueError(
            f"Invalid voltage specification: 0 < Vout ({vout}) < Vin_min ({vin_min}) <= Vin_max ({vin_max})"
        )
    if iout_max <= 0 or fsw_hz <= 0:
        raise ValueError("iout_max and fsw_hz must be positive")

    delta_il = ripple_ratio * iout_max
    l_min = (vout * (vin_max - vout)) / (delta_il * fsw_hz * vin_max)

    # Pick standard inductor >= l_min
    l_candidates = [v for v in get_e_series(series=series_l, min_val=1e-7, max_val=1.0) if v >= l_min]
    l_rec = min(l_candidates) if l_candidates else l_min

    i_peak = iout_max + (delta_il / 2.0)
    i_sat_min = 1.3 * i_peak

    c_out_min = delta_il / (8.0 * fsw_hz * vout_ripple_max_v)
    c_candidates = [v for v in get_e_series(series=series_c, min_val=1e-7, max_val=1e-2) if v >= c_out_min]
    c_rec = min(c_candidates) if c_candidates else c_out_min

    v_nom = (vin_min + vin_max) / 2.0
    duty_nom = vout / v_nom

    return BuckSolution(
        vin_min=vin_min,
        vin_max=vin_max,
        vout=vout,
        iout_max=iout_max,
        fsw_hz=fsw_hz,
        l_min_henry=l_min,
        l_recommended_henry=l_rec,
        c_out_min_farad=c_out_min,
        c_out_recommended_farad=c_rec,
        i_peak_a=i_peak,
        i_sat_min_a=i_sat_min,
        duty_cycle_nom=duty_nom,
    )


# -------------------------------------------------------------------------
# 5. Declarative Synthesized Hardware Modules
# -------------------------------------------------------------------------

class VoltageDividerModule(Module):
    """Parametric synthesized voltage divider module with fail-safe standard passives."""

    def __init__(
        self,
        vin: float,
        vout: float,
        i_max: float = 1e-3,
        series: str = "E96",
        footprint: str = "Resistor_SMD:R_0603_1608Metric",
        name: str = "VoltageDivider",
    ):
        super().__init__(name)
        self.solution = solve_e_series_divider(
            vin=vin, vout=vout, i_max=i_max, series=series
        )

        r1_name = f"{name}_R1"
        r2_name = f"{name}_R2"

        # Explicit pins for hermetic creation without requiring external DB
        self.r1 = Component(
            r1_name,
            pins={"1": ("1", "passive"), "2": ("2", "passive")},
            parent_module=self,
        )
        self.r1.refdes = "R1"
        self.r1.value = self.solution.r1_formatted
        self.r1.footprint = footprint

        self.r2 = Component(
            r2_name,
            pins={"1": ("1", "passive"), "2": ("2", "passive")},
            parent_module=self,
        )
        self.r2.refdes = "R2"
        self.r2.value = self.solution.r2_formatted
        self.r2.footprint = footprint

        self.add(self.r1)
        self.add(self.r2)

        # Connect internal divider node
        self.vin_net = Net(f"{name}_VIN")
        self.vout_net = Net(f"{name}_VOUT")
        self.gnd_net = Net("GND")

        self.r1["1"] += self.vin_net
        self.r1["2"] += self.vout_net
        self.r2["1"] += self.vout_net
        self.r2["2"] += self.gnd_net


class RCLowPassFilterModule(Module):
    """Parametric synthesized RC lowpass filter module."""

    def __init__(
        self,
        fc: float,
        series_r: str = "E24",
        series_c: str = "E12",
        r_footprint: str = "Resistor_SMD:R_0603_1608Metric",
        c_footprint: str = "Capacitor_SMD:C_0603_1608Metric",
        name: str = "RCLowPass",
    ):
        super().__init__(name)
        self.solution = solve_rc_lowpass(
            fc=fc, series_r=series_r, series_c=series_c
        )

        self.r = Component(
            f"{name}_R",
            pins={"1": ("1", "passive"), "2": ("2", "passive")},
            parent_module=self,
        )
        self.r.refdes = "R1"
        self.r.value = self.solution.r_formatted
        self.r.footprint = r_footprint

        self.c = Component(
            f"{name}_C",
            pins={"1": ("1", "passive"), "2": ("2", "passive")},
            parent_module=self,
        )
        self.c.refdes = "C1"
        self.c.value = self.solution.c_formatted
        self.c.footprint = c_footprint

        self.add(self.r)
        self.add(self.c)

        self.in_net = Net(f"{name}_IN")
        self.out_net = Net(f"{name}_OUT")
        self.gnd_net = Net("GND")

        self.r["1"] += self.in_net
        self.r["2"] += self.out_net
        self.c["1"] += self.out_net
        self.c["2"] += self.gnd_net
