"""Shared schematic helpers (SSO) — no part-type graphics."""

from __future__ import annotations

import math
import os
import re
import uuid

_PIN_NAT_SPLIT = re.compile(r"(\d+|\D+)")


def truthy_env(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in ("1", "true", "yes", "on")


def kicad_string_escape(text: str | None) -> str:
    return str(text or "").replace("\\", "\\\\").replace('"', '\\"')


def power_symbol_short_name(net_name: str) -> str:
    """KiCad unit-child base: `{short}_0_1` must match the lib_id name after the colon."""
    raw = str(net_name or "").strip() or "PWR"
    cleaned = re.sub(r"[^A-Za-z0-9_+.-]+", "_", raw).strip("_")
    return cleaned or "PWR"


def kicad_sch_unescape_label(text: str) -> str:
    return text.replace(r"\"", '"').replace(r"\\", "\\")


def det_uuid(key: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_OID, f"openhac:{key}"))


def fmt_mm(x: float) -> str:
    s = f"{float(x):.4f}".rstrip("0").rstrip(".")
    return s if s else "0"


def snap(val: float, grid: float = 1.27) -> float:
    """Nearest connection-grid point, quantized to 0.1 µm so emit matches IR."""
    if grid <= 0:
        return float(val)
    return round(round(float(val) / grid) * grid, 4)


def rotate_offset(dx: float, dy: float, rot_deg: float) -> tuple[float, float]:
    """Rotate symbol-local (dx, dy) by instance rotation (degrees CCW). SSO-002."""
    r = float(rot_deg or 0.0) % 360.0
    if abs(r) < 0.01:
        return dx, dy
    if abs(r - 90.0) < 0.01:
        return -dy, dx
    if abs(r - 180.0) < 0.01:
        return -dx, -dy
    if abs(r - 270.0) < 0.01:
        return dy, -dx
    a = math.radians(r)
    c, s = math.cos(a), math.sin(a)
    return dx * c - dy * s, dx * s + dy * c


def iter_pins(part) -> list:
    if hasattr(part, "get_pins"):
        try:
            pins = list(part.get_pins())
            if pins:
                return pins
        except Exception:
            pass
    raw = getattr(part, "pins", None)
    if isinstance(raw, dict):
        seen: set[int] = set()
        out = []
        for p in raw.values():
            if id(p) not in seen:
                seen.add(id(p))
                out.append(p)
        return out
    return list(raw or [])


def pin_num(pin) -> str:
    return str(getattr(pin, "num", None) or getattr(pin, "number", "") or "").strip()


def pin_name(pin) -> str:
    return str(getattr(pin, "name", "") or pin_num(pin)).strip()


def pin_type(pin) -> str:
    raw = getattr(pin, "pin_type", None) or getattr(pin, "func", None) or "unspecified"
    text = str(raw).lower().replace(" ", "_").replace("-", "_")
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    return text


def pin_is_power_out(pin) -> bool:
    return pin_type(pin) in ("power_out", "pwrout", "pwr_out")


def pin_unit(pin) -> int:
    try:
        return max(1, int(getattr(pin, "unit", 1) or 1))
    except (TypeError, ValueError):
        return 1


def part_datasheet(part) -> str:
    fields = part_fields(part)
    for k in ("Datasheet", "datasheet", "datasheet_url", "url"):
        v = fields.get(k) or getattr(part, k, None)
        if v:
            return str(v).strip()
    return ""


def part_mpn(part) -> str:
    fields = part_fields(part)
    for k in ("MPN", "mpn", "Mpn", "lcsc", "LCSC", "manufacturer_part_number"):
        v = fields.get(k)
        if v:
            return str(v).strip()
    return str(getattr(part, "mpn", "") or "").strip()


def part_manufacturer(part) -> str:
    fields = part_fields(part)
    for k in ("Manufacturer", "manufacturer", "Mfr"):
        v = fields.get(k)
        if v:
            return str(v).strip()
    return str(getattr(part, "manufacturer", "") or "").strip()


def part_ref(part) -> str:
    rd = getattr(part, "refdes", None) or getattr(part, "ref", None) or ""
    s = str(rd).strip()
    if s and s != "?":
        return s
    return str(getattr(part, "name", "") or "U?").strip() or "U?"


def part_value(part) -> str:
    v = getattr(part, "value", None) or getattr(part, "name", None) or ""
    return str(v).strip()


def part_footprint(part) -> str:
    fp = str(getattr(part, "footprint", None) or "").strip()
    if fp:
        return fp
    fields = part_fields(part)
    for k in ("Footprint", "footprint", "kicad_footprint"):
        v = str(fields.get(k) or "").strip()
        if v:
            return v
    return ""


def part_fields(part) -> dict:
    f = getattr(part, "fields", None)
    return f if isinstance(f, dict) else {}


def part_kicad_symbol(part) -> str:
    v = getattr(part, "kicad_symbol", "") or ""
    if str(v).strip():
        return str(v).strip()
    fields = part_fields(part)
    for k in ("kicad_symbol", "kiCad_symbol", "Kicad_symbol"):
        if fields.get(k):
            return str(fields[k]).strip()
    return ""


def module_field(part) -> str:
    v = part_fields(part).get("OpenHaC_Module")
    return str(v).strip() if v else ""


def sheet_field(part) -> str:
    v = part_fields(part).get("OpenHaC_SchSheet")
    if v and str(v).strip():
        return str(v).strip()
    return module_field(part)


def part_rotation_deg(part) -> float:
    fields = part_fields(part)
    raw = fields.get("OpenHaC_Rotation_Deg")
    if raw is None:
        return 0.0
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def net_name(net) -> str:
    return str(getattr(net, "name", None) or net)


def _pin_number_natural_key(s: str) -> tuple:
    parts: list[tuple[int, int | str]] = []
    for chunk in _PIN_NAT_SPLIT.findall(str(s)):
        if chunk.isdigit():
            parts.append((0, int(chunk)))
        else:
            parts.append((1, chunk.lower()))
    return tuple(parts)


def pin_sort_key(pin) -> tuple:
    part = getattr(pin, "part", None)
    ref = getattr(part, "ref", "") or getattr(part, "refdes", "") or ""
    snum = pin_num(pin)
    try:
        nkey = (0, int(snum))
    except ValueError:
        nkey = (1, _pin_number_natural_key(snum))
    return (str(ref), nkey)


def sorted_net_pins(net) -> list:
    pins = []
    raw = net.get_pins() if hasattr(net, "get_pins") else getattr(net, "pins", [])
    if isinstance(raw, dict):
        raw = raw.values()
    for p in raw or []:
        if getattr(p, "part", None) is not None:
            pins.append(p)
    return sorted(pins, key=pin_sort_key)


def part_stable_key(p) -> str:
    ref = part_ref(p)
    if not ref or ref == "?" or ref.startswith("U?"):
        return f"Z{getattr(p, '_part_id', 0):08d}"
    return ref


def net_stable_key(net) -> str:
    return net_name(net)


_POWER_EXACT = frozenset({
    "GND", "VSS", "VCC", "VDD", "3V3", "+3V3", "3.3V", "5V", "+5V", "5.0V",
    "VBAT", "VBUS", "VIN", "VOUT", "12V", "+12V", "15V", "24V", "PWR",
})


def is_gnd_net_name(name: str) -> bool:
    u = name.upper().strip()
    return u in ("GND", "VSS", "AGND", "DGND", "PGND", "EARTH") or u.endswith("_GND")


def is_power_net_name(name: str) -> bool:
    u = name.upper().strip()
    if is_gnd_net_name(name):
        return True
    if u in _POWER_EXACT:
        return True
    if u.startswith(("VCC", "VDD", "VBUS", "VBAT", "VIN", "+")):
        return True
    return False


_BUS_MEMBER_RE = re.compile(r"^(.+)\[(\d+)\]$")


def bus_member_prefix(name: str) -> str | None:
    m = _BUS_MEMBER_RE.match(str(name or "").strip())
    return m.group(1) if m else None


def net_openhac_type(net) -> str:
    ntype = str(getattr(net, "_openhac_net_type", "") or "").lower()
    if ntype in ("power", "gnd", "bus", "signal"):
        return ntype
    nm = net_name(net)
    if is_gnd_net_name(nm):
        return "gnd"
    if is_power_net_name(nm):
        return "power"
    if bus_member_prefix(nm):
        return "bus"
    return "signal"


def is_pwr_flag_part(part) -> bool:
    name = str(getattr(part, "name", "") or getattr(part, "value", "") or "").upper()
    if name == "PWR_FLAG":
        return True
    ref = part_ref(part).upper()
    return ref.startswith("#PWR") or str(getattr(part, "ref_prefix", "")).upper() == "PWR"


def is_nc_net(net) -> bool:
    nm = net_name(net).upper().strip()
    if nm in ("NC", "__NOCONNECT", "NOCONNECT"):
        return True
    try:
        from openhac.core.net import NC as native_nc
        if net is native_nc:
            return True
    except Exception:
        pass
    return False


def want_multi_sheet(parts: list, module_names: list[str]) -> bool:
    if truthy_env("OPENHAC_SCHEMATIC_SINGLE_SHEET"):
        return False
    if truthy_env("OPENHAC_SCHEMATIC_MULTI_SHEET"):
        return True
    try:
        min_parts = int((os.environ.get("OPENHAC_SCHEMATIC_MULTI_SHEET_MIN_PARTS") or "25").strip() or 25)
    except Exception:
        min_parts = 25
    min_parts = max(1, min_parts)
    return len(parts) >= min_parts


def pinout_records(part) -> list[dict]:
    """Best-effort pin records from the live part (not a type-specific map)."""
    recs = []
    for p in iter_pins(part):
        recs.append({
            "num": pin_num(p),
            "name": pin_name(p),
            "type": pin_type(p) or "unspecified",
            "unit": pin_unit(p),
            "side": "",
        })
    fields = part_fields(part)
    raw = fields.get("pinout_json") or getattr(part, "pinout_json", None)
    parsed: list = []
    if raw:
        import json
        try:
            parsed = list(json.loads(raw) if isinstance(raw, str) else raw)
        except Exception:
            parsed = []
    if parsed and not recs:
        recs = [dict(r) for r in parsed]
    elif parsed:
        by_num = {str(r.get("num") or ""): r for r in parsed}
        for rec in recs:
            extra = by_num.get(str(rec.get("num") or ""))
            if not extra:
                continue
            if extra.get("unit") not in (None, ""):
                try:
                    rec["unit"] = max(1, int(extra.get("unit") or 1))
                except (TypeError, ValueError):
                    pass
            if extra.get("side"):
                rec["side"] = extra["side"]
            if extra.get("name") and not rec.get("name"):
                rec["name"] = extra["name"]
    return recs
