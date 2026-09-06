"""DNP helpers (VAR-001). DNP parts stay on the BOM and leave ERC/placement."""

from __future__ import annotations

from typing import Any


def part_is_dnp(part: Any) -> bool:
    """True when a circuit part (or Component) is marked do-not-place."""
    if part is None:
        return False
    if bool(getattr(part, "_openhac_dnp", False)):
        return True
    fields = getattr(part, "fields", None)
    if not isinstance(fields, dict):
        inner = getattr(part, "part", None)
        fields = getattr(inner, "fields", None) if inner is not None else None
        if bool(getattr(inner, "_openhac_dnp", False)):
            return True
    if isinstance(fields, dict):
        raw = str(fields.get("DNP") or "").strip().lower()
        if raw in ("yes", "true", "1", "dnp"):
            return True
    return False


def mark_part_dnp(part: Any) -> None:
    if part is None:
        return
    try:
        part._openhac_dnp = True
    except Exception:
        pass
    fields = getattr(part, "fields", None)
    if isinstance(fields, dict):
        fields["DNP"] = "Yes"


def disconnect_part_from_nets(part: Any) -> None:
    """Unbind pins so ERC/placement do not see DNP connectivity."""
    try:
        if hasattr(part, "get_pins"):
            pins = list(part.get_pins() or [])
        else:
            raw = getattr(part, "pins", None) or []
            pins = list(raw.values()) if isinstance(raw, dict) else list(raw)
    except Exception:
        return
    for pin in pins:
        net = getattr(pin, "net", None)
        if net is None:
            continue
        try:
            if hasattr(net, "remove_pin"):
                net.remove_pin(pin)
            else:
                plist = getattr(net, "pins", None)
                if isinstance(plist, list) and pin in plist:
                    plist.remove(pin)
                pin.net = None
        except Exception:
            try:
                pin.net = None
            except Exception:
                pass
