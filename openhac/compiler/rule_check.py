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
    nm = str(getattr(net, "name", "") or "")
    if nm == "__NOCONNECT":
        return False
    net_name_lower = nm.lower()
    return any(net_name_lower.startswith(prefix) for prefix in _power_prefixes_for_board(board))


def ensure_power_flags(board) -> None:
    """Attach graph PWR_FLAG anchors on power/GND nets (SCH-004).

    Compile does this in ``phase_fixup_power_flags``. Simulate must do the same
    before :func:`run_erc` — schematic emission can place ``power:PWR_FLAG``
    without a graph part, but native ERC still requires the pin on the net.
    """
    from openhac.circuit import get_default_circuit

    circuit = get_default_circuit()
    for net in list(getattr(circuit, "nets", []) or []):
        net_name = str(getattr(net, "name", "") or "")
        if net_name in ("__NOCONNECT", "NC") or net_name.upper().startswith("NC"):
            continue
        ntype = getattr(net, "_openhac_net_type", None)
        if ntype not in ("power", "gnd") and not _net_requires_power_flag(board, net):
            continue
        try:
            pins = list(net.get_pins()) if hasattr(net, "get_pins") else list(getattr(net, "pins", []) or [])
        except Exception:
            pins = []
        if not pins:
            continue
        has_pwr_flag = any(
            str(getattr(p.part, "name", "") or "").upper() == "PWR_FLAG"
            or str(getattr(p.part, "ref_prefix", "") or "") == "PWR"
            for p in pins
            if getattr(p, "part", None) is not None
        )
        if has_pwr_flag:
            continue
        try:
            flag = Component("PWR_FLAG", pins={"1": ("pwr", "power_out")})
            if getattr(flag, "part", None) is not None:
                flag.part.fields["kicad_symbol"] = "power:PWR_FLAG"
                flag.part.value = "PWR_FLAG"
            flag["1"] += net
            logger.info("Injected PWR_FLAG on net %s", net_name)
        except Exception as e:
            logger.warning("Failed to inject PWR_FLAG on net %s: %s", net_name, e)


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
    seen_ids: set[int] = set()

    def _count_part(part):
        if id(part) in seen_ids:
            return
        seen_ids.add(id(part))
        raw = part.fields.get("JLC_Class", "") if hasattr(part, "fields") else ""
        key = str(raw or "").strip().lower() or "unset"
        counts[key] += 1

    # Scan SKiDL global circuit
    for part in getattr(circuit, "parts", []) or []:
        _count_part(part)

    # Scan native OpenHaC core circuit (holds Component-based parts)
    try:
        from openhac.core.circuit import default_circuit as _nc
        for part in getattr(_nc, "parts", []) or []:
            _count_part(part)
    except Exception:
        pass

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
        raw = part.pins
        pins = list(raw.values()) if isinstance(raw, dict) else list(raw)
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
        raw_pins = getattr(part, "pins", []) or []
        pin_iter = list(raw_pins.values()) if isinstance(raw_pins, dict) else list(raw_pins)
        for pin in pin_iter:
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
        raw_pins2 = getattr(part, "pins", []) or []
        for pin in (list(raw_pins2.values()) if isinstance(raw_pins2, dict) else list(raw_pins2)):
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
        if getattr(board, "declared_supply_voltages_v", {}):
            logger.info("ERC Status: Power Budget Check Passed (no supply limits defined, assumed infinite).")
        else:
            logger.info("ERC Status: No power sources defined. Skipping budget checks.")


def _net_is_anonymous(name: str) -> bool:
    """True for auto-named nets (``_1``, ``N$…``, ``Net-…``) that the unconnected-pin check covers."""
    nn = str(name or "").strip()
    if not nn:
        return True
    if nn.startswith("_") and nn[1:].isdigit():
        return True
    if nn.startswith("N$") or nn.startswith("Net-") or nn.startswith("Net$"):
        return True
    return False


def _net_is_no_connect_rail(net, circuit) -> bool:
    """True for SKiDL's reserved ``circuit.NC`` (``__NOCONNECT``) or any ``NCNet``."""
    try:
        from openhac.core.net import NC as native_nc

        if net is native_nc:
            return True
    except Exception:
        pass
    try:
        nc = getattr(circuit, "NC", None)
        if nc is not None and net is nc:
            return True
    except Exception:
        pass
    try:
        from skidl.net import NCNet

        if isinstance(net, NCNet):
            return True
    except Exception:
        pass
    return str(getattr(net, "name", "") or "") == "__NOCONNECT"


def _pin_is_no_connect(pin) -> bool:
    """SKiDL versions differ: legacy ``NC`` singleton vs ``NCNet`` instances."""
    try:
        from openhac.core.net import NC as _NC

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
    """Check for floating nets, unconnected pins, and missing power flags using the native circuit."""
    try:
        from openhac.core.circuit import default_circuit as circuit

        nets = list(circuit.nets)
        parts = list(circuit.parts)
    except Exception as e:
        logger.warning("ERC net-level checks skipped: circuit not initialized (%s)", e)
        return

    floating_violations = []
    unconnected_violations = []
    power_flag_violations = []

    # 1. Floating-net check
    for net in nets:
        if getattr(net, "merged_into", None) is not None:
            continue
        if _net_is_no_connect_rail(net, circuit):
            continue
        try:
            # Handle both Native (.pins) and SKiDL (.get_pins()) APIs
            if hasattr(net, "get_pins"):
                pins = list(net.get_pins())
            else:
                pins = list(getattr(net, "pins", []))
            # Optional SKiDL dual-scan only when OPENHAC_LEGACY_SKIDL=1.
            seen = {id(p) for p in pins}
            try:
                from openhac.circuit import _legacy_skidl_enabled, get_default_circuit as _legacy_circuit

                if _legacy_skidl_enabled():
                    legacy = _legacy_circuit()
                    if legacy is not circuit:
                        for part in getattr(legacy, "parts", []):
                            raw = getattr(part, "pins", None)
                            pin_iter = (
                                list(raw.values())
                                if isinstance(raw, dict)
                                else list(raw or [])
                            )
                            for p in pin_iter:
                                if id(p) not in seen and getattr(p, "net", None) is net:
                                    pins.append(p)
                                    seen.add(id(p))
            except Exception:
                pass
        except Exception:
            pins = []

        if len(pins) < 2:
            if not pins:
                continue
            nn = str(getattr(net, "name", "") or "")
            if _net_is_anonymous(nn):
                continue
            floating_violations.append(
                f"Floating net {nn!r}: {len(pins)} pin(s) (need ≥2)"
            )
            continue

    # 2. Unconnected-pin check
    for part in parts:
        part_label = str(getattr(part, "value", "") or getattr(part, "name", "") or "").upper()
        if part_label == "PWR_FLAG":
            continue
        try:
            if hasattr(part, "get_pins"):
                part_pins = part.get_pins()
            else:
                part_pins = list(getattr(part, "pins", []))
        except Exception:
            continue
        for pin in part_pins:
            try:
                if _pin_is_no_connect(pin):
                    continue
                if str(getattr(pin, "pin_type", "") or "").lower() in ("no_connect", "nc"):
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
            
        logger.debug(f"ERC: Net {net.name} requires PWR_FLAG. Checking pins...")
        try:
            pins = list(net.get_pins())
        except Exception:
            try:
                pins = [p for p in net.pins]
            except Exception:
                pins = []
                
        if not pins:
            continue

        for p in pins:
            logger.debug(f"  Pin {getattr(p, 'number', '?')} on part {getattr(getattr(p, 'part', object()), 'ref', 'unknown')} name={getattr(getattr(p, 'part', object()), 'name', 'unknown')}")
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

    # Pin compatibility checks (Shorts, contention, domain mismatch)
    _check_pin_type_compatibility(board)
    _check_voltage_safety(board)

    _run_erc_plugin_hooks(board)

    _run_power_budget(board)


def _check_pin_type_compatibility(board) -> None:
    """Advanced ERC: Verify that connected pins have compatible types (SIG-007, PWR-003)."""
    try:
        from openhac.circuit import get_default_circuit
        circuit = get_default_circuit()
    except Exception:
        return

    violations = []
    for net in circuit.nets:
        if _net_is_no_connect_rail(net, circuit):
            continue
        
        pins = list(net.get_pins()) if hasattr(net, "get_pins") else []
        if not pins:
            continue

        drivers = []
        power_sources = []
        grounds = []
        loads = []

        for p in pins:
            part = getattr(p, "part", None)
            if part is not None and str(getattr(part, "name", "")).upper() == "PWR_FLAG":
                continue
            ptype = str(getattr(p, "pin_type", "passive")).lower()
            pname = str(getattr(p, "name", "")).upper()
            
            # Semantic refinement of 'power' type
            if ptype == "power":
                if any(x in pname for x in ["GND", "VSS", "GROUND", "VREFN", "COM"]):
                    ptype = "ground"
                elif any(x in pname for x in ["OUT", "VCC", "VDD", "3V3", "5V", "12V", "VIN", "VBUS", "BATT"]):
                    # If it has 'OUT', it is definitely a source. 
                    # If it's a known rail name on a module/IC, we treat it as power_in by default
                    # unless it's a known source (LDO/Buck).
                    if "OUT" in pname:
                        ptype = "power_out"
                    else:
                        ptype = "power_in"
            
            if ptype in ("output", "power_out"):
                drivers.append(p)
            if ptype == "power_out":
                power_sources.append(p)
            if ptype == "ground":
                grounds.append(p)
            if ptype in ("input", "power_in"):
                loads.append(p)

        # Rule: Conflict (Multiple drivers)
        if len(drivers) > 1:
            # Allow multiple power sources only if user explicitly allowed it
            if len(power_sources) > 1:
                logger.warning(f"Multiple power sources detected on net '{net.name}': {drivers}")
            else:
                violations.append(f"Driver contention on net '{net.name}': Multiple output pins detected {drivers}")

        # Rule: Critical Short (Power vs Ground)
        if power_sources and grounds:
            violations.append(f"CRITICAL SHORT on net '{net.name}': Power source {power_sources} connected to Ground {grounds}!")

    if violations:
        raise OpenHaCError("ERC Pin Compatibility Violations:\n" + "\n".join(violations))


def _check_voltage_safety(board) -> None:
    """Verify that pin voltage ratings are compatible with the net's nominal voltage (PWR-004)."""
    try:
        from openhac.circuit import get_default_circuit
        circuit = get_default_circuit()
    except Exception:
        return

    # 1. Map net names to nominal voltages (from Board or inference)
    raw_v = getattr(board, "declared_supply_voltages_v", {})
    if raw_v is None:
        raw_v = {}
    net_voltages = {str(k).lower(): float(v) for k, v in raw_v.items()}
    
    # 2. Iterate nets and perform checks
    violations = []
    for net in circuit.nets:
        net_name = net.name.lower()
        nom_v = net_voltages.get(net_name)
        
        # Inferred voltage from power prefix (e.g. '3V3' -> 3.3V)
        if nom_v is None:
            import re
            m = re.search(r"(\d+)[Vv](\d+)?", net_name)
            if m:
                v_str = m.group(1) + ("." + m.group(2) if m.group(2) else "")
                try: nom_v = float(v_str)
                except: pass

        if nom_v is None:
            continue

        # Check every component on this net
        for p in net.get_pins():
            comp = getattr(p, "part", None)
            if not comp: continue
            
            # Use database rating if available
            # Note: We access the component's internal data store
            comp_data = getattr(comp, "_comp_data", {}) if hasattr(comp, "_comp_data") else {}
            v_rating = comp_data.get("voltage_rating")
            
            if v_rating is not None:
                try:
                    v_max = float(v_rating)
                    if nom_v > v_max:
                        violations.append(
                            f"VOLTAGE MISMATCH on net '{net.name}': Net voltage {nom_v}V exceeds "
                            f"component {comp.refdes} ({comp.value}) rating of {v_max}V!"
                        )
                except (ValueError, TypeError):
                    pass
    
    if violations:
        # For now, we warn instead of failing until DB coverage is 100%
        for v in violations:
            logger.warning(f"ERC Warning: {v}")
    elif net_voltages:
        logger.info("ERC Status: Voltage Safety Check Passed.")


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


def _check_power_net_current_annotations(board) -> list[str]:
    """PCB-006 / IPC standards: power-like nets should carry current_a for width calc."""
    gates = dict(getattr(board, "quality_gates", None) or {})
    env_req = (os.environ.get("OPENHAC_REQUIRE_POWER_CURRENTS") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
        "force",
    )
    require = bool(gates.get("require_power_net_currents", False)) or env_req
    warn_only = not require
    # Always evaluate under fabrication; warn by default, fail when required.
    try:
        goal = str(getattr(board, "compile_goal", "") or getattr(board, "effective_compile_goal", lambda: "")() or "")
    except Exception:
        goal = str(getattr(board, "compile_goal", "") or "")
    if goal != "fabrication" and not require:
        return []

    from openhac.compiler.pcb_physics import collect_net_currents_a

    currents = collect_net_currents_a(board)
    prefixes = tuple(getattr(board, "power_net_prefixes", None) or ()) or (
        "vcc",
        "vdd",
        "3v3",
        "3.3v",
        "5v",
        "12v",
        "vbus",
        "vbatt",
        "vin",
        "gnd",
        "pgnd",
        "agnd",
    )
    # Collect power-like net names from modules
    power_nets: set[str] = set()
    try:
        mods = board._get_all_modules()
    except Exception:
        mods = getattr(board, "modules", []) or []
    for mod in mods:
        for comp in getattr(mod, "components", []) or []:
            for pin in getattr(getattr(comp, "part", None), "get_pins", lambda: [])():
                net = getattr(pin, "net", None)
                if net is None:
                    continue
                name = str(getattr(net, "name", "") or "").strip()
                if not name:
                    continue
                low = name.lower()
                ptype = str(getattr(pin, "pin_type", "") or "").lower()
                if ptype in ("power_in", "power_out", "power") or any(low.startswith(p) or p in low for p in prefixes):
                    if low not in ("nc",):
                        power_nets.add(name)

    missing = sorted(n for n in power_nets if float(currents.get(n, 0.0) or 0.0) <= 0.0)
    # GND often uses pours — still want a rating for pour/track planning, but allow skip via gate
    if gates.get("allow_gnd_without_current", True):
        missing = [n for n in missing if not str(n).upper().startswith("GND") and str(n).upper() != "AGND"]

    if not missing:
        return []
    msg = (
        "IPC-2152 standards: power net(s) lack current annotations "
        f"(use Board.set_net_current / Net.set_current): {', '.join(missing[:12])}"
        + ("…" if len(missing) > 12 else "")
    )
    if warn_only:
        logger.warning("%s", msg)
        return []
    return [msg]


def _check_mcu_decoupling(board) -> list[str]:
    """Check that MCU modules have adequate decoupling capacitors.
    
    Per ST/ARM guidelines: each power pin should have 100nF, plus bulk 4.7uF+.
    """
    v: list[str] = []
    for mod in board._get_all_modules():
        if "mcu" in mod.name.lower() or "stm32" in mod.name.lower():
            caps_100nf = 0
            caps_bulk = 0
            for comp in mod.components:
                name = str(getattr(comp, 'generic_name', '') or '').lower()
                if '100nf' in name or '100n' in name:
                    caps_100nf += 1
                if '4u7' in name or '10u' in name:
                    caps_bulk += 1
            if caps_100nf < 2:
                v.append(f"Module '{mod.name}' may have insufficient decoupling: {caps_100nf}x 100nF found, recommend 4+ per MCU guidelines.")
            if caps_bulk < 1:
                v.append(f"Module '{mod.name}' missing bulk decoupling capacitor (recommend 4.7uF+ for MCU VDD).")
    return v


def _check_crystal_loading(board) -> list[str]:
    """Check that crystal oscillators have loading capacitors.
    
    HSE (8MHz): typically 18pF loading
    LSE (32.768kHz): typically 12pF loading
    """
    v: list[str] = []
    for mod in board._get_all_modules():
        xtal_caps = 0
        has_8mhz = False
        has_32k = False
        for comp in mod.components:
            name = str(getattr(comp, 'generic_name', '') or '').lower()
            fp = str(getattr(getattr(comp, 'part', None), 'footprint', '') or '').lower()
            if 'xtal' in name or 'crystal' in fp:
                if '8m' in name or '8mhz' in name:
                    has_8mhz = True
                if '32' in name and ('k' in name or 'hz' in name):
                    has_32k = True
            if 'pf' in name or '18pf' in name or '12pf' in name or '20pf' in name:
                xtal_caps += 1
        if has_8mhz and xtal_caps < 2:
            v.append(f"Module '{mod.name}' has 8MHz crystal but only {xtal_caps} loading capacitors (need 2).")
        if has_32k and xtal_caps < 2:
            v.append(f"Module '{mod.name}' has 32.768kHz crystal but insufficient loading capacitors.")
    return v


def _check_power_sequencing(board) -> list[str]:
    """Check power sequencing: analog rails should come up before or with digital.
    
    Also check that 3.3V rail is ready before sensitive analog sensors powered.
    """
    v: list[str] = []
    has_ldo = False
    has_buck = False
    has_analog_sensor = False
    
    for mod in board._get_all_modules():
        for comp in mod.components:
            name = str(getattr(comp, 'generic_name', '') or '').lower()
            if 'ldo' in name:
                has_ldo = True
            if 'buck' in name:
                has_buck = True
        # Check for analog sensors (IMU, baro, mag)
        if any(x in mod.name.lower() for x in ['imu', 'baro', 'mag', 'sensor']):
            has_analog_sensor = True
    
    # If we have both buck and LDO, the LDO should feed analog sensors
    if has_buck and has_ldo and has_analog_sensor:
        logger.info("Power architecture check: Buck -> LDO -> Analog sensors detected (good for noise isolation).")
    elif has_analog_sensor and not has_ldo:
        v.append("Analog sensors present without LDO for noise isolation. Consider adding dedicated analog 3.3V rail.")
    
    return v


def _check_highspeed_signals(board) -> list[str]:
    """Check for potential high-speed signal issues.
    
    - SPI > 10MHz should have series termination
    - USB needs impedance control
    """
    v: list[str] = []
    # Check for SPI interfaces without apparent series resistors
    for mod in board._get_all_modules():
        has_spi = False
        has_series_r = False
        for comp in mod.components:
            name = str(getattr(comp, 'generic_name', '') or '').lower()
            if 'spi' in name:
                has_spi = True
            if any(x in name for x in ['27r', '33r', '22r', 'series']):
                has_series_r = True
        if has_spi and not has_series_r:
            logger.warning(f"Module '{mod.name}' has SPI interface. Consider 22-33Ω series resistors for signal integrity at high speeds.")
    return v


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

    # EE-Grade Design Rule Checks
    violations.extend(_check_mcu_decoupling(board))
    violations.extend(_check_crystal_loading(board))
    violations.extend(_check_power_sequencing(board))
    violations.extend(_check_highspeed_signals(board))
    violations.extend(_check_power_net_current_annotations(board))

    # ABC-026…050 advanced board policy (fabrication)
    try:
        goal = ""
        try:
            goal = str(board.effective_compile_goal()).strip().lower()
        except Exception:
            goal = str(getattr(board, "compile_goal", "") or "").strip().lower()
        if goal == "fabrication":
            from openhac.compiler.advanced_board_policy import (
                check_bga_fab_gate,
                check_highspeed_fab_gate,
                check_rf_fab_gate,
            )

            violations.extend(check_bga_fab_gate(board))
            violations.extend(check_highspeed_fab_gate(board))
            violations.extend(check_rf_fab_gate(board))
    except Exception as e:
        logger.debug("ABC policy checks skipped: %s", e)

    ms_issue = _mixed_signal_ground_merge_issue(board)
    if ms_issue:
        if getattr(board, "strict", False):
            violations.append(ms_issue)
        else:
            logger.warning(ms_issue)

    # LIB-003 / FAB-011: production / fabrication gate for unverified JIT and synthetic parts.
    _req_verified = os.environ.get("OPENHAC_REQUIRE_VERIFIED_PARTS", "").lower() in ("1", "true", "yes")
    try:
        _fab_goal = str(getattr(board, "effective_compile_goal", lambda: "")()).strip().lower() == "fabrication"
    except Exception:
        _fab_goal = (os.environ.get("OPENHAC_COMPILE_GOAL") or "").strip().lower() in ("fabrication", "fab")
    if _fab_goal:
        _req_verified = True
    if _req_verified:
        from openhac.circuit import get_default_circuit

        circuit = get_default_circuit()
        offenders: list[str] = []
        seen_part_ids: set[int] = set()

        def _check_part_jit(part):
            if id(part) in seen_part_ids:
                return
            seen_part_ids.add(id(part))
            fields = getattr(part, "fields", None)
            if not isinstance(fields, dict):
                return
            conf = str(fields.get("OpenHaC_JIT_Confidence", "") or "").strip().lower()
            if conf in ("medium", "low"):
                offenders.append(f"{getattr(part, 'ref', '?')}:jit:{conf}")
            wm = str(fields.get("OpenHaC_WATERMARK", "") or "").strip().upper()
            if wm.startswith("SYNTHETIC"):
                offenders.append(f"{getattr(part, 'ref', '?')}:watermark:{wm}")

        for part in getattr(circuit, "parts", []) or []:
            _check_part_jit(part)
        # Also scan native OpenHaC core circuit
        try:
            from openhac.core.circuit import default_circuit as _nc
            for part in getattr(_nc, "parts", []) or []:
                _check_part_jit(part)
        except Exception:
            pass

        if offenders:
            offenders = sorted(offenders)
            violations.append(
                "FAB-011/LIB-003: verified-parts gate failed (OPENHAC_REQUIRE_VERIFIED_PARTS); "
                f"circuit contains unverified/JIT/synthetic parts ({offenders}). "
                "Pre-populate the database or use handoff mode."
            )

    if violations:
        raise DRCViolationError(
            "DRC Failed:\n" + "\n".join(f"  • {v}" for v in violations)
        )

    logger.info(f"DRC Status: Passed. Board {w}x{h}mm, {board.layers} layers.")
