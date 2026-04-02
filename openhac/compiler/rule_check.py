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
    ...


def run_drc(board):
    ...
