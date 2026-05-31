"""
pcb_physics.py

IPC-2152 physics-based net-class application to pcbnew boards.

Reads per-net current ratings (set via Net.set_current() / phase_propagate_currents)
and assigns KiCad net-classes with appropriately sized trace widths so the router
and DRC tools honour them.

This module is intentionally import-safe when pcbnew is not present — all pcbnew
access happens inside the functions that receive pcbnew as an argument.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("openhac.pcb_physics")

# IPC-2152 trace-width calculation (mirrors core/physics.py for zero-import overhead here).
def _ipc2152_width_mm(
    current_a: float,
    temp_rise_c: float = 10.0,
    thickness_oz: float = 1.0,
    min_width_mm: float = 0.25,
) -> float:
    """Return IPC-2152 minimum trace width in mm for *current_a* Amperes."""
    if current_a <= 0:
        return min_width_mm
    k, b, c = 0.048, 0.44, 0.725
    area_mils2 = (current_a / (k * (temp_rise_c**b))) ** (1.0 / c)
    thickness_mils = thickness_oz * 1.37
    width_mm = (area_mils2 / thickness_mils) * 0.0254
    return max(width_mm, min_width_mm)


# Net-class name thresholds (Amperes → class name).  These match the naming used
# in the schematic SI stackup reminder and the autoroute policy generator.
_NETCLASS_THRESHOLDS: list[tuple[float, str]] = [
    (30.0, "HighCurrent_30A"),
    (15.0, "HighCurrent_15A"),
    (10.0, "HighCurrent_10A"),
    (5.0,  "HighCurrent_5A"),
    (2.0,  "Power_2A"),
    (1.0,  "Power_1A"),
    (0.5,  "Signal_500mA"),
    (0.0,  "Signal"),
]


def _netclass_for_current(current_a: float) -> str:
    for threshold, name in _NETCLASS_THRESHOLDS:
        if current_a >= threshold:
            return name
    return "Signal"


def _ensure_netclass(pcb, pcbnew_mod, class_name: str, width_mm: float, clearance_mm: float = 0.2) -> bool:
    """Create *class_name* on *pcb* if it does not already exist.  Returns True on success."""
    try:
        ncs = pcb.GetNetClasses()
    except Exception:
        return False

    # KiCad stores net-classes in a container; check by name.
    try:
        if hasattr(ncs, "has_key") and ncs.has_key(class_name):
            return True
    except Exception:
        pass
    try:
        if hasattr(ncs, "values") and class_name in [nc.GetName() for nc in ncs.values()]:
            return True
    except Exception:
        pass

    try:
        nc_cls = getattr(pcbnew_mod, "NETCLASS", None)
        if nc_cls is None:
            return False
        nc = nc_cls(class_name)
        nc.SetTraceWidth(int(pcbnew_mod.FromMM(width_mm)))
        nc.SetClearance(int(pcbnew_mod.FromMM(clearance_mm)))
        # Via sizes default to the net-class trace width.
        nc.SetViaDiameter(int(pcbnew_mod.FromMM(max(width_mm * 2.0, 0.8))))
        nc.SetViaDrill(int(pcbnew_mod.FromMM(max(width_mm * 0.8, 0.4))))
        
        if hasattr(ncs, "Add"):
            ncs.Add(nc)
        else:
            ncs[class_name] = nc
        return True
    except Exception as e:
        logger.debug("Failed to create net-class %r: %s", class_name, e)
        return False


def _assign_netclass_to_net(pcb, net_name: str, class_name: str) -> bool:
    """Assign *class_name* to the net named *net_name* on *pcb*."""
    try:
        nets = pcb.GetNetsByName()
        ni = nets.get(net_name) or nets.get(str(net_name))
        if ni is None:
            return False
        ni.SetNetClassName(class_name)
        return True
    except Exception as e:
        logger.debug("Failed to assign net-class %r to net %r: %s", class_name, net_name, e)
        return False


def apply_physics_net_classes(pcb, board, pcbnew_mod) -> int:
    """Apply IPC-2152-derived net-classes to *pcb* for all nets with a current rating.

    Reads ``Net.current_a`` annotations (set by ``Board.set_net_current()`` or
    propagated by ``phase_propagate_currents``) and creates / assigns KiCad
    net-classes whose trace widths satisfy IPC-2152 at a 10 °C temperature rise.

    Args:
        pcb:        pcbnew board object (``pcbnew.LoadBoard(...)``).
        board:      OpenHaC ``Board`` instance (source of module/net metadata).
        pcbnew_mod: The ``pcbnew`` module (passed in so this file stays importable
                    without KiCad being installed).

    Returns:
        Number of nets that received a non-default net-class assignment.
    """
    # Collect net → current_a mapping from the OpenHaC circuit.
    net_currents: dict[str, float] = {}

    # Primary source: board._high_current_nets (set via declare_high_current_net / set_net_current)
    for net_name, info in (getattr(board, "_high_current_nets", None) or {}).items():
        if isinstance(info, dict):
            amps = float(info.get("current_a", 0.0) or 0.0)
        else:
            amps = float(info or 0.0)
        if amps > 0:
            net_currents[str(net_name)] = amps

    # Secondary source: live Net objects with current_a set by phase_propagate_currents.
    try:
        from openhac.circuit import get_default_circuit
        circuit = get_default_circuit()
        for net in getattr(circuit, "nets", []):
            name = str(getattr(net, "name", None) or "").strip()
            if not name:
                continue
            amps = float(getattr(net, "current_a", 0.0) or 0.0)
            if amps > 0 and name not in net_currents:
                net_currents[name] = amps
    except Exception:
        pass

    # Fallback: walk board modules to find net current annotations.
    if not net_currents:
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
                    name = str(getattr(net, "name", None) or "").strip()
                    amps = float(getattr(net, "current_a", 0.0) or 0.0)
                    if name and amps > 0:
                        net_currents[name] = max(net_currents.get(name, 0.0), amps)

    if not net_currents:
        logger.debug("apply_physics_net_classes: no nets with current annotations found; skipping.")
        return 0

    # Board copper thickness (oz) — read from board stackup if available.
    copper_oz = 1.0
    try:
        stackup = pcb.GetDesignSettings().GetStackupDescriptor()
        for i in range(stackup.GetCount()):
            layer = stackup.GetStackupLayer(i)
            if "Cu" in str(layer.GetName() or ""):
                copper_oz = float(layer.GetThickness()) / 35000.0  # nm → oz (approx)
                copper_oz = max(0.5, min(copper_oz, 4.0))
                break
    except Exception:
        copper_oz = 1.0

    # Pre-create all needed net-classes.
    created: set[str] = set()
    for amps in net_currents.values():
        class_name = _netclass_for_current(amps)
        if class_name not in created:
            width_mm = _ipc2152_width_mm(amps, temp_rise_c=10.0, thickness_oz=copper_oz)
            # Clearance scales with trace width for high-current nets.
            clearance_mm = max(0.2, width_mm * 0.5)
            if _ensure_netclass(pcb, pcbnew_mod, class_name, width_mm, clearance_mm):
                created.add(class_name)
                logger.info(
                    "NetClass %r: %.3f A → %.3f mm trace (IPC-2152, %s oz Cu)",
                    class_name,
                    amps,
                    width_mm,
                    copper_oz,
                )

    # Assign net-classes to PCB nets.
    assigned = 0
    for net_name, amps in net_currents.items():
        class_name = _netclass_for_current(amps)
        if class_name in created and _assign_netclass_to_net(pcb, net_name, class_name):
            assigned += 1
            logger.debug("Net %r → net-class %r (%.2f A)", net_name, class_name, amps)

    if assigned:
        logger.info(
            "apply_physics_net_classes: assigned IPC-2152 net-classes to %d net(s) across %d class(es).",
            assigned,
            len(created),
        )
    return assigned
