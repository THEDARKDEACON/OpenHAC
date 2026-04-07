import json
import logging
import os
import sys
from collections import defaultdict
from openhac.core.base import Component, Module, OpenHaCError

logger = logging.getLogger("openhac.rules")


class ERCPowerBudgetError(OpenHaCError):
    pass

class ERCFloatingNetError(OpenHaCError):
    pass

class ERCUnconnectedPinError(OpenHaCError):
    pass

class ERCMissingPowerFlagError(OpenHaCError):
    pass


class ERCPluginError(OpenHaCError):
    """Raised when a user-registered ERC hook reports violations (SCH-005)."""


class DRCViolationError(OpenHaCError):
    pass


_POWER_NET_PREFIXES = ('vcc', 'vin', '3v3', '5v', 'gnd', 'vbat', 'vbus')


def _power_prefixes_for_board(board) -> tuple[str, ...]:
    """Declared rails (SCH-004) + defaults + optional :attr:`Board.power_net_prefixes`."""
    extra = tuple(getattr(board, "power_net_prefixes", ()) or ())
    return tuple(dict.fromkeys((*_POWER_NET_PREFIXES, *extra)))


def _net_requires_power_flag(board, net) -> bool:
    """True if this net should carry a KiCad PWR_FLAG for OpenHaC ERC."""
    if id(net) in getattr(board, "_explicit_power_net_ids", set()):
        return True
    net_name_lower = net.name.lower()
    return any(net_name_lower.startswith(prefix) for prefix in _power_prefixes_for_board(board))


def _ma_aggregate(val, mod_name: str, field_name: str) -> float:
    """Normalize current to a single float (mA) for **DRC** aggregate IPC width checks.

    Dict values are summed (conservative) with a warning. ERC power budgeting uses per-rail
    matching when ``source_current_max_ma`` is a dict (PWR-001).
    """
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, dict):
        total = 0.0
        for k, v in val.items():
            if isinstance(v, (int, float)):
                total += float(v)
            else:
                logger.warning(
                    "Module '%s': ignoring non-numeric %s rail %r -> %r",
                    mod_name,
                    field_name,
                    k,
                    v,
                )
        if total > 0:
            logger.warning(
                "Module '%s': %s is a dict — using sum(%s)=%s mA for DRC IPC aggregate only.",
                mod_name,
                field_name,
                field_name,
                total,
            )
        return total
    return 0.0


def _mixed_signal_ground_merge_issue(board) -> str | None:
    """SIG-006: warn/fail when AGND/DGND-style nets are declared but no merge hint is recorded.

    This does not try to infer pcbnew constraints; it just nudges users to document a star-point / ferrite / net-tie.
    """
    roles = getattr(board, "_net_roles", None) or []
    merges = getattr(board, "_net_merge_hints", None) or []
    if not roles:
        return None
    agnds: set[str] = set()
    dgnds: set[str] = set()
    for r in roles:
        if not isinstance(r, dict):
            continue
        role = str(r.get("role", "") or "").strip().lower()
        net = str(r.get("net", "") or "").strip()
        if not net:
            continue
        if role == "analog_ground":
            agnds.add(net)
        elif role == "digital_ground":
            dgnds.add(net)
    if not agnds or not dgnds:
        return None
    # If any merge hint bridges an AGND↔DGND pair (either direction), consider it documented.
    merge_pairs: set[frozenset[str]] = set()
    for m in merges:
        if not isinstance(m, dict):
            continue
        a = str(m.get("net_a", "") or "").strip()
        b = str(m.get("net_b", "") or "").strip()
        if a and b:
            merge_pairs.add(frozenset((a, b)))
    for a in agnds:
        for b in dgnds:
            if frozenset((a, b)) in merge_pairs:
                return None
    return (
        "SIG-006: board declares both analog_ground and digital_ground nets "
        f"(AGND={sorted(agnds)}, DGND={sorted(dgnds)}) but no Board.declare_net_merge_hint(...) "
        "bridges any AGND↔DGND pair. Document a star-point / ferrite bead / net-tie intent."
    )


def jlc_class_line_counts_from_circuit() -> dict[str, int]:
    """Count BOM line items by normalized ``JLC_Class`` (LIB-005).

    Empty or whitespace ``JLC_Class`` is counted under ``\"unset\"``.
    """
    try:
        from openhac.circuit import get_default_circuit
    except Exception:
        return {}
    try:
        circuit = get_default_circuit()
    except Exception:
        return {}
    counts: defaultdict[str, int] = defaultdict(int)
    for part in getattr(circuit, "parts", []) or []:
        raw = part.fields.get("JLC_Class", "") if hasattr(part, "fields") else ""
        key = str(raw or "").strip().lower() or "unset"
        counts[key] += 1
    return dict(sorted(counts.items()))


def _effective_jlc_class_limits(board) -> dict[str, int]:
    """Merge scalar caps and :attr:`~openhac.core.board.Board.jlc_class_line_limits` (dict overrides)."""
    lims: dict[str, int] = {}
    mjb = getattr(board, "max_jlc_basic_parts", None)
    if mjb is not None:
        lims["basic"] = int(mjb)
    mje = getattr(board, "max_jlc_extended_parts", None)
    if mje is not None:
        lims["extended"] = int(mje)
    extra = getattr(board, "jlc_class_line_limits", None)
    if extra:
        for k, v in extra.items():
            lims[str(k).strip().lower() or "unset"] = int(v)
    return lims


def _count_jlc_extended_line_items() -> int:
    """Count SKiDL parts whose ``JLC_Class`` field is Extended (LIB-005)."""
    return jlc_class_line_counts_from_circuit().get("extended", 0)


def _count_jlc_basic_line_items() -> int:
    """Count SKiDL parts whose ``JLC_Class`` field is Basic (LIB-005)."""
    return jlc_class_line_counts_from_circuit().get("basic", 0)


def _board_all_modules(board):
    all_mods = getattr(board, "all_modules", None)
    if not all_mods:
        all_mods = board.modules
    return all_mods


def _collect_board_components(board):
    """All :class:`Component` instances under any module (including nested modules)."""

    found: list = []

    def walk(node):
        if isinstance(node, Component):
            found.append(node)
        elif isinstance(node, Module):
            for c in node:
                walk(c)

    for mod in _board_all_modules(board):
        for c in mod:
            walk(c)
    return found


def _cap_voltage_temp_margin_factor(board) -> float:
    """Scale required capacitor voltage when ambient exceeds catalog rating reference (REL-001).

    Enabled only when both :attr:`~openhac.core.board.Board.ambient_operating_temp_c` and
    :attr:`~openhac.core.board.Board.cap_voltage_temp_derating_percent_per_c` are set.
    Factor = ``1 + (pct/100) * max(0, Ta - Tref)``.
    """
    ta = getattr(board, "ambient_operating_temp_c", None)
    pct = getattr(board, "cap_voltage_temp_derating_percent_per_c", None)
    if ta is None or pct is None:
        return 1.0
    try:
        pct_f = float(pct)
    except (TypeError, ValueError):
        return 1.0
    if pct_f <= 0:
        return 1.0
    try:
        tref = float(getattr(board, "cap_voltage_rating_reference_temp_c", 85.0))
    except (TypeError, ValueError):
        tref = 85.0
    try:
        ta_f = float(ta)
    except (TypeError, ValueError):
        return 1.0
    delta = max(0.0, ta_f - tref)
    return 1.0 + (pct_f / 100.0) * delta


def _cap_nominal_rail_voltage_v(comp: Component, declared: dict) -> float | None:
    """Largest declared nominal voltage among the capacitor's pins (excludes common ground net names)."""
    if not declared:
        return None
    decl = {str(k).lower(): float(v) for k, v in declared.items()}
    skip = {"gnd", "agnd", "dgnd", "vss", "vee", "earth", "pgnd", "egnd"}
    part = getattr(comp, "part", None)
    if part is None:
        return None
    try:
        pins = list(part.pins)
    except Exception:
        return None
    vals: list[float] = []
    for pin in pins:
        net = getattr(pin, "net", None)
        if net is None:
            continue
        nm = str(getattr(net, "name", "") or "").strip().lower()
        if nm in skip:
            continue
        if nm in decl:
            vals.append(decl[nm])
    if not vals:
        return None
    return max(vals)


def _is_test_point_component(comp: Component) -> bool:
    """Heuristic test-point detection for REL-003 (refs, generic names, DB category, footprint)."""
    g = (comp.generic_name or "").strip()
    if g.upper().startswith("TP_"):
        return True
    row = Component.db.get_component(g)
    if row and str(row.get("category") or "").lower() == "testability":
        return True
    fp = str(getattr(comp.part, "footprint", None) or "")
    if "testpoint" in fp.lower():
        return True
    ref = str(getattr(comp.part, "ref", "") or "")
    if ref.upper().startswith("TP"):
        return True
    return False


def _count_test_points(board) -> int:
    return sum(1 for c in _collect_board_components(board) if _is_test_point_component(c))


def _test_point_touches_net_name_ci(board, name_lower: str) -> bool:
    """True if some heuristic test-point component has a pin on a net matching *name_lower* (REL-003)."""
    for comp in _collect_board_components(board):
        if not _is_test_point_component(comp):
            continue
        part = comp.part
        for pin in getattr(part, "pins", []) or []:
            net = getattr(pin, "net", None)
            if net is None:
                continue
            nm = str(getattr(net, "name", "") or "").strip().lower()
            if nm == name_lower:
                return True
    return False


def _count_test_points_on_net_ci(board, name_lower: str) -> int:
    """Count heuristic test-point components with at least one pin on *name_lower* (REL-003)."""
    n = 0
    for comp in _collect_board_components(board):
        if not _is_test_point_component(comp):
            continue
        part = comp.part
        for pin in getattr(part, "pins", []) or []:
            net = getattr(pin, "net", None)
            if net is None:
                continue
            nm = str(getattr(net, "name", "") or "").strip().lower()
            if nm == name_lower:
                n += 1
                break
    return n


def _load_fab_profile_data(name: str) -> dict:
    """Load ``{name}.json`` from the ``openhac.fab_profiles`` package (MFG-004)."""
    if not name:
        return {}
    try:
        from importlib.resources import files

        root = files("openhac.fab_profiles")
        path = root / f"{name}.json"
        if not path.is_file():
            logger.warning("Fab profile %r not found under openhac.fab_profiles.", name)
            return {}
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("Could not load fab profile %r: %s", name, e)
        return {}


def _effective_drc_defaults(board) -> dict:
    d = dict(_DRC_DEFAULTS)
    prof = getattr(board, "fab_profile", None)
    if prof:
        data = _load_fab_profile_data(str(prof))
        for k in d:
            if k in data and data[k] is not None:
                try:
                    d[k] = float(data[k])
                except (TypeError, ValueError):
                    pass
        logger.info("DRC: applied fab profile %r geometry hints (MFG-004).", prof)
    return d


def _collect_supply_by_rail_and_scalar(board):
    """Merge dict rails from any module; ignore scalar ``source_current_max_ma`` under a dict-supply subtree."""
    supply_by_rail = defaultdict(float)
    scalar_supply = 0.0

    def walk(mod, under_dict_subtree: bool) -> None:
        nonlocal scalar_supply
        s = getattr(mod, "source_current_max_ma", 0)
        if isinstance(s, dict):
            for k, v in s.items():
                if isinstance(v, (int, float)):
                    supply_by_rail[str(k)] += float(v)
                else:
                    logger.warning(
                        "Module '%s': ignoring non-numeric source_current_max_ma rail %r -> %r",
                        mod.name,
                        k,
                        v,
                    )
            child_under = True
        else:
            if isinstance(s, (int, float)) and s > 0 and not under_dict_subtree:
                scalar_supply += float(s)
            child_under = under_dict_subtree
        for c in mod:
            if isinstance(c, Module):
                walk(c, child_under)

    for top in board.modules:
        walk(top, False)
    return supply_by_rail, scalar_supply


def _collect_draw_by_rail_and_scalar(board):
    draw_by_rail = defaultdict(float)
    scalar_draw = 0.0
    for mod in _board_all_modules(board):
        d = getattr(mod, "max_current_draw_ma", 0)
        if isinstance(d, dict):
            for k, v in d.items():
                if isinstance(v, (int, float)):
                    draw_by_rail[str(k)] += float(v)
                else:
                    logger.warning(
                        "Module '%s': ignoring non-numeric max_current_draw_ma rail %r -> %r",
                        mod.name,
                        k,
                        v,
                    )
        elif isinstance(d, (int, float)) and d > 0:
            scalar_draw += float(d)
        extra = getattr(mod, "extra_input_draw_by_rail_ma", None) or {}
        if isinstance(extra, dict):
            for k, v in extra.items():
                if isinstance(v, (int, float)):
                    draw_by_rail[str(k)] += float(v)
                else:
                    logger.warning(
                        "Module '%s': ignoring non-numeric extra_input_draw_by_rail_ma rail %r -> %r",
                        mod.name,
                        k,
                        v,
                    )
    return draw_by_rail, scalar_draw


def _run_power_budget(board) -> None:
    supply_by_rail, scalar_supply = _collect_supply_by_rail_and_scalar(board)
    draw_by_rail, scalar_draw = _collect_draw_by_rail_and_scalar(board)

    has_dict_supply = bool(supply_by_rail)
    has_dict_draw = bool(draw_by_rail)

    if has_dict_supply:
        # PWR-002 (stretch): allow declaring rail conversions so downstream rail draw can be checked
        # against upstream supply, given rail voltages and efficiency.
        convs = list(getattr(board, "_rail_conversions", None) or [])
        dsv = getattr(board, "declared_supply_voltages_v", None) or {}
        if convs and dsv:
            for c in convs:
                try:
                    inp = str(c.get("input_rail", "") or "")
                    outp = str(c.get("output_rail", "") or "")
                    eff = float(c.get("efficiency", 0.0) or 0.0)
                except Exception:
                    continue
                if not inp or not outp or eff <= 0:
                    continue
                vin = dsv.get(inp.strip().lower())
                vout = dsv.get(outp.strip().lower())
                if not isinstance(vin, (int, float)) or not isinstance(vout, (int, float)):
                    continue
                if vin <= 0 or vout <= 0:
                    continue
                avail_in = float(supply_by_rail.get(inp, 0.0))
                if avail_in > 0:
                    supply_by_rail[outp] += avail_in * float(vin) * eff / float(vout)
        if scalar_draw > 0:
            raise ERCPowerBudgetError(
                "ERC Failed: source_current_max_ma uses per-rail dicts, but at least one module "
                "still uses scalar max_current_draw_ma. Use max_current_draw_ma={rail: mA, ...} "
                "with the same rail names as the supply dict (e.g. '3V3', '5V')."
            )
        for rail, draw in draw_by_rail.items():
            avail = supply_by_rail.get(rail, 0.0)
            if draw > avail:
                raise ERCPowerBudgetError(
                    f"ERC Failed: rail '{rail}' draw {draw}mA exceeds supply {avail}mA."
                )
        logger.info(
            "ERC Status: Per-rail power OK (draw %s vs supply %s).",
            dict(draw_by_rail) if draw_by_rail else "{}",
            dict(supply_by_rail),
        )
        return

    if has_dict_draw:
        if scalar_supply <= 0:
            logger.info("ERC Status: No power sources defined. Skipping budget checks.")
            return
        raise ERCPowerBudgetError(
            "ERC Failed: max_current_draw_ma uses per-rail dicts but no source_current_max_ma dict "
            "was found. Add source_current_max_ma={rail: mA, ...} with matching rail names, or use "
            "scalar draw and scalar supply only."
        )

    total_draw = scalar_draw
    if scalar_supply > 0 and total_draw > scalar_supply:
        raise ERCPowerBudgetError(
            f"ERC Failed: Theoretical current draw ({total_draw}mA) exceeds power supply bounds "
            f"({scalar_supply}mA)."
        )
    if scalar_supply > 0:
        logger.info(
            f"ERC Status: Passed. Power Budget OK ({total_draw}mA / {scalar_supply}mA)."
        )
    else:
        logger.info("ERC Status: No power sources defined. Skipping budget checks.")


def _net_is_no_connect_rail(net, circuit) -> bool:
    """True for SKiDL's reserved ``circuit.NC`` (``__NOCONNECT``) or any ``NCNet``."""
    try:
        nc = getattr(circuit, "NC", None)
        if nc is not None and net is nc:
            return True
    except Exception:
        pass
    try:
        from skidl.net import NCNet

        return isinstance(net, NCNet)
    except Exception:
        return str(getattr(net, "name", "") or "") == "__NOCONNECT"


def _pin_is_no_connect(pin) -> bool:
    """SKiDL versions differ: legacy ``NC`` singleton vs ``NCNet`` instances."""
    try:
        from skidl import NC as _NC

        if pin.net is _NC:
            return True
    except Exception:
        pass
    try:
        from skidl.net import NCNet

        return isinstance(pin.net, NCNet)
    except Exception:
        return False


def _check_net_level(board):
    """Check for floating nets, unconnected pins, and missing power flags."""
    try:
        import skidl  # noqa: F401 — ensure package importable
    except Exception as e:
        logger.warning(
            "SKiDL not available (%s); skipping net-level ERC (floating nets, unconnected pins, PWR_FLAG).",
            e,
        )
        return

    try:
        from openhac.circuit import get_default_circuit

        circuit = get_default_circuit()
        nets = list(circuit.nets)
        parts = list(circuit.parts)
    except Exception as e:
        raise OpenHaCError(
            "ERC net-level checks require an initialized SKiDL default circuit. "
            "Run netlist/schematic generation first, or ensure skidl is imported before run_erc()."
        ) from e

    floating_violations = []
    unconnected_violations = []
    power_flag_violations = []

    # 1. Floating-net check
    for net in nets:
        if _net_is_no_connect_rail(net, circuit):
            continue
        try:
            pins = list(net.get_pins())
        except Exception:
            try:
                pins = [p for p in net.pins]
            except Exception:
                pins = []
        if len(pins) < 2:
            # Power nets often show one load pin until PWR_FLAG is added; PWR_FLAG check covers that.
            if len(pins) == 1 and _net_requires_power_flag(board, net):
                continue
            floating_violations.append(f"Floating net: {net.name} ({len(pins)} pin(s))")

    # 2. Unconnected-pin check
    for part in parts:
        try:
            part_pins = list(part.pins)
        except Exception:
            continue
        for pin in part_pins:
            try:
                if _pin_is_no_connect(pin):
                    continue
                if not pin.is_connected():
                    unconnected_violations.append(f"Unconnected pin: {part.ref} pin {pin.num}")
            except Exception as e:
                logger.warning(
                    "ERC: could not verify pin connectivity for %s pin %s: %s",
                    getattr(part, "ref", "?"),
                    getattr(pin, "num", "?"),
                    e,
                )

    # 3. Power-flag check (prefix heuristics + Board.declare_power_rail, SCH-004)
    for net in nets:
        if _net_is_no_connect_rail(net, circuit):
            continue
        if not _net_requires_power_flag(board, net):
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
        errors.append(ERCFloatingNetError("\n".join(sorted(floating_violations))))
    if unconnected_violations:
        errors.append(ERCUnconnectedPinError("\n".join(sorted(unconnected_violations))))
    if power_flag_violations:
        errors.append(ERCMissingPowerFlagError("\n".join(sorted(power_flag_violations))))

    if not errors:
        return

    if sys.version_info >= (3, 11):
        raise ExceptionGroup("ERC failed", errors)
    else:
        # Fallback: raise first error with all messages concatenated
        all_messages = "\n".join(str(e) for e in errors)
        raise errors[0].__class__(all_messages)


def _run_erc_plugin_hooks(board) -> None:
    hooks = getattr(board, "_erc_hooks", None) or []
    messages: list[str] = []
    for fn in hooks:
        try:
            out = fn(board)
        except Exception as e:
            raise OpenHaCError(f"ERC hook {getattr(fn, '__name__', repr(fn))} raised: {e}") from e
        if out:
            messages.extend(str(m) for m in out)
    if messages:
        raise ERCPluginError("ERC plugin violations:\n" + "\n".join(messages))


def run_erc(board):
    """OpenHaC ERC on the SKiDL graph (pre-check). For KiCad library ERC, use ``kicad-cli sch erc`` (see ``--kicad-erc``)."""
    logger.info("Running Electrical Rule Check (ERC)...")

    # Net-level checks (floating nets, unconnected pins, missing power flags)
    _check_net_level(board)

    _run_erc_plugin_hooks(board)

    _run_power_budget(board)


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
      4. Optional: ``Board.min_test_points`` (REL-003) requires a minimum count of
         heuristic test-point components.
      5. Optional: ``Board.test_point_min_count_by_net`` (REL-003) requires at least *N*
         heuristic test-point components per named net (case-insensitive keys).

    Raises:
        DRCViolationError: If any rule is violated.
    """
    logger.info("Running Design Rule Check (DRC)...")
    violations = []

    w, h = board.size_mm
    if w <= 0 or h <= 0:
        violations.append(f"Invalid board dimensions: {w}x{h}mm (must be positive)")

    all_mods = getattr(board, "all_modules", None)
    if not all_mods:
        all_mods = board._get_all_modules() if hasattr(board, "_get_all_modules") else board.modules

    # Check placed modules fit within board boundaries
    for mod in all_mods:
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

    # Power trace width: IPC-2152 required width vs design minimum (PCB-006 + MFG-004 fab profile)
    merged = _effective_drc_defaults(board)
    raw_board_min = getattr(board, "min_trace_width_mm", None)
    if raw_board_min is not None:
        design_min_mm = float(raw_board_min)
    else:
        design_min_mm = float(merged["min_trace_width_mm"])
    ipc_epsilon = 1e-4
    for mod in all_mods:
        draw_ma = _ma_aggregate(
            getattr(mod, "max_current_draw_ma", 0.0), mod.name, "max_current_draw_ma"
        )
        if draw_ma > 0:
            ipc_mm = calculate_ipc2152_trace_width(draw_ma / 1000.0)
            if ipc_mm > design_min_mm + ipc_epsilon:
                violations.append(
                    f"Module '{mod.name}' draw {draw_ma}mA → IPC-2152 external-layer width "
                    f"≥{ipc_mm}mm exceeds design min trace {design_min_mm}mm "
                    f"(increase design min / netclass or lower stated draw)."
                )
            logger.info(
                f"  DRC: Module '{mod.name}' draws {draw_ma}mA → IPC-2152 width {ipc_mm}mm "
                f"(vs design min trace {design_min_mm}mm)"
            )

    jlc_counts = jlc_class_line_counts_from_circuit()
    jlc_limits = _effective_jlc_class_limits(board)
    for cls, lim in jlc_limits.items():
        n = jlc_counts.get(cls, 0)
        if n > int(lim):
            label = "unset/empty" if cls == "unset" else cls
            violations.append(
                f"JLC assembly policy (LIB-005): {n} BOM line(s) with JLC_Class={label!r} exceed limit {lim}."
            )

    if getattr(board, "warn_jlc_extended_parts", False):
        ext_warn = _count_jlc_extended_line_items()
        if ext_warn > 0:
            logger.warning(
                "LIB-005: %s BOM line(s) use JLC_Class=Extended (assembly surcharge risk); "
                "set max_jlc_extended_parts to enforce a hard limit.",
                ext_warn,
            )

    if getattr(board, "require_passive_voltage_ratings", False):
        for comp in _collect_board_components(board):
            row = Component.db.get_component(comp.generic_name)
            if not row:
                continue
            cat = (row.get("category") or "").lower()
            g = comp.generic_name.lower()
            is_cap = "cap" in cat or g.startswith("c_")
            if not is_cap:
                continue
            vr = row.get("voltage_rating")
            try:
                ok = vr is not None and float(vr) > 0
            except (TypeError, ValueError):
                ok = False
            if not ok:
                violations.append(
                    f"Capacitor part {comp.generic_name!r} has no positive voltage_rating in DB (REL-001)."
                )

    if getattr(board, "require_passive_power_ratings", False):
        for comp in _collect_board_components(board):
            row = Component.db.get_component(comp.generic_name)
            if not row:
                continue
            cat = (row.get("category") or "").lower()
            g = comp.generic_name.lower()
            is_res = "res" in cat or g.startswith("r_")
            if not is_res:
                continue
            pw = row.get("power_watts")
            try:
                ok = pw is not None and float(pw) > 0
            except (TypeError, ValueError):
                ok = False
            if not ok:
                violations.append(
                    f"Resistor part {comp.generic_name!r} has no positive power_watts in DB (REL-001)."
                )

    if getattr(board, "require_inductor_voltage_ratings", False):
        for comp in _collect_board_components(board):
            row = Component.db.get_component(comp.generic_name)
            if not row:
                continue
            cat = (row.get("category") or "").lower()
            g = comp.generic_name.lower()
            is_ind = "ind" in cat or g.startswith("l_")
            if not is_ind:
                continue
            vr = row.get("voltage_rating")
            try:
                ok = vr is not None and float(vr) > 0
            except (TypeError, ValueError):
                ok = False
            if not ok:
                violations.append(
                    f"Inductor part {comp.generic_name!r} has no positive voltage_rating in DB (REL-001)."
                )

    if getattr(board, "require_resistor_voltage_ratings", False):
        for comp in _collect_board_components(board):
            row = Component.db.get_component(comp.generic_name)
            if not row:
                continue
            cat = (row.get("category") or "").lower()
            g = comp.generic_name.lower()
            is_res = "res" in cat or g.startswith("r_")
            if not is_res:
                continue
            vr = row.get("voltage_rating")
            try:
                ok = vr is not None and float(vr) > 0
            except (TypeError, ValueError):
                ok = False
            if not ok:
                violations.append(
                    f"Resistor part {comp.generic_name!r} has no positive voltage_rating in DB (REL-001)."
                )

    ratio = getattr(board, "require_cap_voltage_derating_ratio", None)
    declared_v = getattr(board, "declared_supply_voltages_v", None) or {}
    if ratio is not None:
        try:
            rf = float(ratio)
        except (TypeError, ValueError):
            rf = 0.0
        if rf <= 0:
            violations.append("REL-001: require_cap_voltage_derating_ratio must be > 0.")
        elif not declared_v:
            violations.append(
                "REL-001: require_cap_voltage_derating_ratio is set but declared_supply_voltages_v is empty "
                "(map net name → nominal DC volts, keys matched case-insensitively)."
            )
        else:
            for comp in _collect_board_components(board):
                row = Component.db.get_component(comp.generic_name)
                if not row:
                    continue
                cat = (row.get("category") or "").lower()
                g = comp.generic_name.lower()
                is_cap = "cap" in cat or g.startswith("c_")
                if not is_cap:
                    continue
                vnom = _cap_nominal_rail_voltage_v(comp, declared_v)
                if vnom is None:
                    continue
                tf = _cap_voltage_temp_margin_factor(board)
                need = rf * vnom * tf
                vr = row.get("voltage_rating")
                try:
                    ok = vr is not None and float(vr) + 1e-9 >= need
                except (TypeError, ValueError):
                    ok = False
                if not ok:
                    if tf > 1.0 + 1e-9:
                        tail = (
                            f"{rf}×{vnom:g}V nominal × {tf:g} temp margin "
                            f"(ambient {getattr(board, 'ambient_operating_temp_c', '?')}°C vs ref "
                            f"{getattr(board, 'cap_voltage_rating_reference_temp_c', 85)}°C; "
                            f"{getattr(board, 'cap_voltage_temp_derating_percent_per_c', '?')}%/°C)"
                        )
                    else:
                        tail = f"{rf}× nominal rail {vnom:g}V per declared_supply_voltages_v"
                    violations.append(
                        f"Capacitor {comp.generic_name!r}: voltage_rating must be ≥ {need:g}V ({tail}) (REL-001)."
                    )

    if getattr(board, "strict_passive_catalog_fields", False):
        for comp in _collect_board_components(board):
            row = Component.db.get_component(comp.generic_name)
            if not row:
                continue
            cat = (row.get("category") or "").lower()
            g = comp.generic_name.lower()
            is_r = "res" in cat or g.startswith("r_")
            is_c = "cap" in cat or g.startswith("c_")
            is_l = "ind" in cat or g.startswith("l_")
            if is_r and not str(row.get("tolerance") or "").strip():
                violations.append(
                    f"Resistor part {comp.generic_name!r} has empty tolerance in DB (LIB-006 strict_passive_catalog_fields)."
                )
            if is_c and not str(row.get("tolerance") or "").strip():
                violations.append(
                    f"Capacitor part {comp.generic_name!r} has empty tolerance in DB (LIB-006 strict_passive_catalog_fields)."
                )
            if is_l and not str(row.get("tolerance") or "").strip():
                violations.append(
                    f"Inductor part {comp.generic_name!r} has empty tolerance in DB (LIB-006 strict_passive_catalog_fields)."
                )

    if getattr(board, "strict_passive_attributes_json", False):
        for comp in _collect_board_components(board):
            row = Component.db.get_component(comp.generic_name)
            if not row:
                continue
            cat = (row.get("category") or "").lower()
            g = comp.generic_name.lower()
            is_r = "res" in cat or g.startswith("r_")
            is_c = "cap" in cat or g.startswith("c_")
            is_l = "ind" in cat or g.startswith("l_")
            if not (is_r or is_c or is_l):
                continue
            raw = row.get("attributes_json")
            if raw is None or not str(raw).strip():
                violations.append(
                    f"Part {comp.generic_name!r} has empty attributes_json in DB (LIB-006 strict_passive_attributes_json)."
                )
                continue
            try:
                parsed = json.loads(str(raw))
            except json.JSONDecodeError:
                violations.append(
                    f"Part {comp.generic_name!r}: attributes_json is not valid JSON (LIB-006 strict_passive_attributes_json)."
                )
                continue
            if not isinstance(parsed, dict):
                violations.append(
                    f"Part {comp.generic_name!r}: attributes_json must be a JSON object (LIB-006 strict_passive_attributes_json)."
                )

    min_tp = getattr(board, "min_test_points", None)
    if min_tp is not None:
        need = int(min_tp)
        if need < 0:
            violations.append("min_test_points must be >= 0 (REL-003).")
        else:
            got = _count_test_points(board)
            if got < need:
                violations.append(
                    f"Testability (REL-003): board requires at least {need} test point(s), found {got}."
                )

    for nm in getattr(board, "require_test_point_on_nets", ()) or ():
        if not _test_point_touches_net_name_ci(board, str(nm).strip().lower()):
            violations.append(
                "Testability (REL-003): require_test_point_on_nets includes "
                f"{nm!r} but no heuristic test point touches that net."
            )

    tpm = getattr(board, "test_point_min_count_by_net", None) or {}
    for net_key, need in tpm.items():
        need_i = int(need)
        if need_i < 0:
            violations.append(
                f"Testability (REL-003): test_point_min_count_by_net[{net_key!r}] must be >= 0."
            )
            continue
        if need_i == 0:
            continue
        nk = str(net_key).strip().lower()
        got = _count_test_points_on_net_ci(board, nk)
        if got < need_i:
            violations.append(
                f"Testability (REL-003): net {nk!r} requires at least {need_i} test point(s), found {got}."
            )

    if any(c.get("type") == "diff_pair" for c in getattr(board, "constraints", ())):
        logger.warning(
            "Board defines route_differential_pair() constraints; controlled impedance / pair geometry is "
            "not applied by OpenHaC placement or FreeRouting (SIG-002). "
            "diff_pair_intent is recorded in the compile manifest for KiCad handoff."
        )

    ms_issue = _mixed_signal_ground_merge_issue(board)
    if ms_issue:
        if getattr(board, "strict", False):
            violations.append(ms_issue)
        else:
            logger.warning(ms_issue)

    # LIB-003 stretch: production-mode gate for any medium/low-confidence JIT parts.
    if os.environ.get("OPENHAC_REQUIRE_VERIFIED_PARTS", "").lower() in ("1", "true", "yes"):
        from openhac.circuit import get_default_circuit

        circuit = get_default_circuit()
        offenders: list[str] = []
        for part in getattr(circuit, "parts", []) or []:
            fields = getattr(part, "fields", None)
            if not isinstance(fields, dict):
                continue
            conf = str(fields.get("OpenHaC_JIT_Confidence", "") or "").strip().lower()
            if conf in ("medium", "low"):
                offenders.append(f"{getattr(part, 'ref', '?')}:{conf}")
        if offenders:
            offenders = sorted(offenders)
            violations.append(
                "LIB-003: OPENHAC_REQUIRE_VERIFIED_PARTS is set but circuit contains unverified/JIT parts "
                f"({offenders}). Pre-populate the database or disable the production gate."
            )

    if violations:
        raise DRCViolationError(
            "DRC Failed:\n" + "\n".join(f"  • {v}" for v in violations)
        )

    logger.info(f"DRC Status: Passed. Board {w}x{h}mm, {board.layers} layers.")
