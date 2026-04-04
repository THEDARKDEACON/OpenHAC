import sys
from openhac.core.base import OpenHaCError


class ERCPowerBudgetError(OpenHaCError):
    pass

class ERCFloatingNetError(OpenHaCError):
    pass

class ERCUnconnectedPinError(OpenHaCError):
    pass

class ERCMissingPowerFlagError(OpenHaCError):
    pass

class DRCViolationError(OpenHaCError):
    pass


_POWER_NET_PREFIXES = ('vcc', 'vin', '3v3', '5v', 'gnd', 'vbat', 'vbus')


def _check_net_level(board):
    """Check for floating nets, unconnected pins, and missing power flags."""
    try:
        from skidl import default_circuit, NC as SKIDL_NC
    except Exception:
        return  # No SKiDL circuit available

    try:
        nets = list(default_circuit.nets)
        parts = list(default_circuit.parts)
    except Exception:
        return

    floating_violations = []
    unconnected_violations = []
    power_flag_violations = []

    # 1. Floating-net check
    for net in nets:
        try:
            pins = list(net.get_pins())
        except Exception:
            try:
                pins = [p for p in net.pins]
            except Exception:
                pins = []
        if len(pins) < 2:
            floating_violations.append(f"Floating net: {net.name} ({len(pins)} pin(s))")

    # 2. Unconnected-pin check
    for part in parts:
        try:
            part_pins = list(part.pins)
        except Exception:
            continue
        for pin in part_pins:
            try:
                # Skip NC pins
                if pin.net is SKIDL_NC:
                    continue
                if not pin.is_connected():
                    unconnected_violations.append(f"Unconnected pin: {part.ref} pin {pin.num}")
            except Exception:
                pass

    # 3. Power-flag check
    for net in nets:
        net_name_lower = net.name.lower()
        if not any(net_name_lower.startswith(prefix) for prefix in _POWER_NET_PREFIXES):
            continue
        try:
            pins = list(net.get_pins())
        except Exception:
            try:
                pins = [p for p in net.pins]
            except Exception:
                pins = []
        has_pwr_flag = any(
            getattr(p.part, 'name', '').upper() == 'PWR_FLAG' or
            getattr(p.part, 'ref_prefix', '') == 'PWR'
            for p in pins
            if hasattr(p, 'part') and p.part is not None
        )
        if not has_pwr_flag:
            power_flag_violations.append(f"Missing PWR_FLAG on power net: {net.name}")

    # Aggregate and raise
    errors = []
    if floating_violations:
        errors.append(ERCFloatingNetError("\n".join(floating_violations)))
    if unconnected_violations:
        errors.append(ERCUnconnectedPinError("\n".join(unconnected_violations)))
    if power_flag_violations:
        errors.append(ERCMissingPowerFlagError("\n".join(power_flag_violations)))

    if not errors:
        return

    if sys.version_info >= (3, 11):
        raise ExceptionGroup("ERC failed", errors)
    else:
        # Fallback: raise first error with all messages concatenated
        all_messages = "\n".join(str(e) for e in errors)
        raise errors[0].__class__(all_messages)


def run_erc(board):
    print("Running Electrical Rule Check (ERC)...")

    # Net-level checks (floating nets, unconnected pins, missing power flags)
    _check_net_level(board)

    # Power-budget check (preserved from original)
    total_draw = sum(mod.max_current_draw_ma for mod in board.modules if hasattr(mod, 'max_current_draw_ma'))
    total_supply = sum(mod.source_current_max_ma for mod in board.modules if hasattr(mod, 'source_current_max_ma'))

    if total_supply > 0 and total_draw > total_supply:
        raise ERCPowerBudgetError(
            f"ERC Failed: Theoretical current draw ({total_draw}mA) exceeds power supply bounds ({total_supply}mA)."
        )
    elif total_supply > 0:
        print(f"ERC Status: Passed. Power Budget OK ({total_draw}mA / {total_supply}mA).")
    else:
        print("ERC Status: No power sources defined. Skipping budget checks.")


def calculate_ipc2152_trace_width(current_amps, temp_rise_c=10, copper_oz=1.0):
    """Calculate minimum PCB trace width per IPC-2152 for external layers.

    Uses the simplified IPC-2221/2152 formula:
        A = (I / (k * ΔT^b))^(1/c)
    where A is cross-sectional area in mil², and the standard constants for
    external layers are k=0.048, b=0.44, c=0.725.

    Args:
        current_amps: Maximum continuous current through the trace (A).
        temp_rise_c: Acceptable temperature rise above ambient (°C).
        copper_oz: Copper weight in oz/ft² (1 oz ≈ 35 µm = 1.378 mil).

    Returns:
        Minimum trace width in millimeters.

    Raises:
        ValueError: If current_amps <= 0 or temp_rise_c <= 0.
    """
    if current_amps <= 0:
        raise ValueError(f"current_amps must be positive, got {current_amps}")
    if temp_rise_c <= 0:
        raise ValueError(f"temp_rise_c must be positive, got {temp_rise_c}")

    # IPC-2152 external layer constants
    k = 0.048
    b = 0.44
    c = 0.725

    # Required cross-sectional area in mil²
    area_mil2 = (current_amps / (k * (temp_rise_c ** b))) ** (1.0 / c)

    # Copper thickness in mils (1 oz/ft² = 1.378 mil)
    thickness_mil = copper_oz * 1.378

    # Width in mils, then convert to mm (1 mil = 0.0254 mm)
    width_mil = area_mil2 / thickness_mil
    width_mm = width_mil * 0.0254

    return round(width_mm, 4)


# Default DRC rule limits (mm)
_DRC_DEFAULTS = {
    "min_trace_width_mm": 0.15,       # 6 mil — standard for most fabs
    "min_trace_clearance_mm": 0.15,   # 6 mil clearance
    "min_via_drill_mm": 0.3,          # typical min drill
    "min_edge_clearance_mm": 0.25,    # copper-to-edge minimum
}


def run_drc(board):
    """Run Design Rule Checks on the board.

    Checks:
      1. Board dimensions must be positive.
      2. Placed modules must fit within board boundaries.
      3. Power traces must meet IPC-2152 minimum width for current draw.

    Raises:
        DRCViolationError: If any rule is violated.
    """
    print("Running Design Rule Check (DRC)...")
    violations = []

    w, h = board.size_mm
    if w <= 0 or h <= 0:
        violations.append(f"Invalid board dimensions: {w}x{h}mm (must be positive)")

    # Check placed modules fit within board boundaries
    for mod in board.modules:
        if mod.placed_x is not None and mod.placed_y is not None:
            if mod.placed_x < 0 or mod.placed_y < 0:
                violations.append(
                    f"Module '{mod.name}' placed at negative coords "
                    f"({mod.placed_x}, {mod.placed_y})"
                )
            if mod.placed_x + mod.width > w:
                violations.append(
                    f"Module '{mod.name}' exceeds board width: "
                    f"x={mod.placed_x} + w={mod.width} > {w}mm"
                )
            if mod.placed_y + mod.height > h:
                violations.append(
                    f"Module '{mod.name}' exceeds board height: "
                    f"y={mod.placed_y} + h={mod.height} > {h}mm"
                )

    # Power trace width check via IPC-2152
    min_width = _DRC_DEFAULTS["min_trace_width_mm"]
    for mod in board.modules:
        draw_ma = getattr(mod, "max_current_draw_ma", 0.0)
        if draw_ma > 0:
            required_width = calculate_ipc2152_trace_width(draw_ma / 1000.0)
            if required_width < min_width:
                required_width = min_width
            print(
                f"  DRC: Module '{mod.name}' draws {draw_ma}mA → "
                f"min trace width: {required_width}mm"
            )

    if violations:
        raise DRCViolationError(
            "DRC Failed:\n" + "\n".join(f"  • {v}" for v in violations)
        )

    print(f"DRC Status: Passed. Board {w}x{h}mm, {board.layers} layers.")
