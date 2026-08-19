"""Symbol resolution providers (SSO-010). No part-type graphics."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from openhac.compiler.kicad_sym_pinpos import (
    EmptySymbolPinResolver,
    SymbolPinResolver,
    find_symbol_library_file,
    parse_kicad_symbol_id,
    part_library_name,
)
from openhac.core.exceptions import SchematicGenerationError
from openhac.schematic.util import (
    iter_pins,
    part_fields,
    part_footprint,
    part_kicad_symbol,
    part_ref,
    pin_num,
    pinout_records,
    power_symbol_short_name,
    truthy_env,
)

logger = logging.getLogger("openhac.schematic.resolve")


@dataclass
class ResolvedSymbol:
    lib_id: str
    lib_file: Path | None
    source: str  # explicit | vendor | kicad | synth | stub
    pin_complete: bool


_DEVICE_PASSIVE_PREFIXES = ("R", "C", "L", "D")
_DEVICE_PASSIVE_FP = ("resistor", "capacitor", "inductor", "diode", "led_")


def schematic_symbol_lib_key(part) -> str:
    sym = part_kicad_symbol(part)
    if ":" in str(sym):
        return str(sym).split(":", 1)[1]
    name = (getattr(part, "name", None) or "").strip()
    value = (getattr(part, "value", None) or "").strip()
    ref = part_ref(part)
    if name and name not in ("?", "PWR_FLAG") and not name.startswith("R_") and len(name) > 1:
        # Prefer SKiDL symbol name (e.g. "R") over generic_name.
        if getattr(part, "lib", None) is not None:
            return name
    if ":" in str(sym):
        return str(sym).split(":", 1)[1]
    lib_nick = part_library_name(part)
    if lib_nick in ("Device", "power") and name and name != "?":
        return name
    if name and name != "?" and not str(name).startswith("R_"):
        return name
    if value and value != "?" and not (len(value) <= 4 and value[0].isdigit()):
        return value
    if ref and ref != "?":
        return ref
    return "PART"


def declared_lib_id(part) -> str | None:
    ks = part_kicad_symbol(part)
    if ks and ":" in ks:
        return ks
    lib = part_library_name(part)
    name = (getattr(part, "name", None) or "").strip()
    if lib and lib not in ("OpenHaC", "") and name and name != "?":
        return f"{lib}:{name}"
    if lib and lib not in ("OpenHaC", ""):
        key = schematic_symbol_lib_key(part)
        if key and key != "PART":
            return f"{lib}:{key}"
    return None


def _lcsc_id(part) -> str | None:
    fields = part_fields(part)
    for k in ("Supplier_SKU", "LCSC", "lcsc", "lcsc_id", "sku"):
        v = str(fields.get(k) or "").strip()
        if v.upper().startswith("C") and v[1:].isdigit():
            return v
    return None


def looks_like_device_passive(part) -> bool:
    """True when catalog/ref/footprint data says R/C/L/D — not a compiler graphics table."""
    ks = part_kicad_symbol(part).upper()
    if ks.startswith("DEVICE:R") or ks.startswith("DEVICE:C") or ks.startswith("DEVICE:L"):
        return True
    if ks.startswith("DEVICE:D") or ks.startswith("DEVICE:LED"):
        return True
    ref = part_ref(part).upper()
    prefix = "".join(c for c in ref if c.isalpha())
    if prefix in _DEVICE_PASSIVE_PREFIXES or prefix == "LED":
        return True
    fp = part_footprint(part).lower()
    return any(tok in fp for tok in _DEVICE_PASSIVE_FP)


def _lib_has_symbol(lib_id: str) -> bool:
    parsed = parse_kicad_symbol_id(lib_id)
    if not parsed:
        return False
    lib, name = parsed
    path = find_symbol_library_file(lib)
    if path is None:
        return False
    from openhac.compiler.kicad_sym_pinpos import load_symbol_pin_positions
    pmap = load_symbol_pin_positions(path, name)
    return bool(pmap)


def _graph_pin_nums(part) -> set[str]:
    return {pin_num(p) for p in iter_pins(part) if pin_num(p)}


def _library_pin_nums(lib_id: str) -> set[str]:
    parsed = parse_kicad_symbol_id(lib_id)
    if not parsed:
        return set()
    lib, name = parsed
    path = find_symbol_library_file(lib)
    if path is None:
        return set()
    from openhac.compiler.kicad_sym_pinpos import load_symbol_pin_positions
    pmap = load_symbol_pin_positions(path, name) or {}
    return set(pmap.keys())


def library_covers_graph_pins(lib_id: str, part) -> bool:
    """True when every graph pin number exists on the KiCad library symbol."""
    graph = _graph_pin_nums(part)
    if not graph:
        return _lib_has_symbol(lib_id)
    lib_pins = _library_pin_nums(lib_id)
    return bool(lib_pins) and graph <= lib_pins


def find_pin_parity_lib_id(part, declared: str | None) -> str | None:
    """Pick a library symbol whose pin numbers cover the graph (exact match preferred).

    Searches only the declared library nick — no part-type tables.
    """
    graph = _graph_pin_nums(part)
    if declared and _lib_has_symbol(declared) and library_covers_graph_pins(declared, part):
        return declared
    parsed = parse_kicad_symbol_id(declared or "")
    if not parsed:
        return None
    lib, _hint = parsed
    path = find_symbol_library_file(lib)
    if path is None:
        return None
    from openhac.compiler.kicad_sym_pinpos import iter_library_symbol_names, load_symbol_pin_positions

    hint = _hint.lower()
    best: tuple[int, int, str] | None = None  # (extra_pins, name_distance, name)
    for name in iter_library_symbol_names(path):
        pmap = load_symbol_pin_positions(path, name) or {}
        lpins = set(pmap.keys())
        if not graph or not (graph <= lpins):
            continue
        extra = len(lpins - graph)
        nl, hl = name.lower(), hint
        related = (not hl) or nl == hl or nl.startswith(hl) or hl.startswith(nl)
        if hl and not related:
            continue
        dist = 0 if hl and (nl == hl or nl.startswith(hl)) else 1
        cand = (extra, dist, name)
        if best is None or cand < best:
            best = cand
            if extra == 0 and dist == 0:
                break
    if best is None:
        return None
    return f"{lib}:{best[2]}"


def _vendor_lib_id(part) -> str | None:
    lcsc = _lcsc_id(part)
    if not lcsc:
        return None
    cand = f"jlc2kicad_generated:{lcsc}"
    if _lib_has_symbol(cand):
        return cand
    # Search extra dirs for a file named {lcsc}.kicad_sym
    from openhac.compiler.kicad_sym_pinpos import symbol_library_search_paths
    for d in symbol_library_search_paths():
        p = Path(d) / f"{lcsc}.kicad_sym"
        if p.is_file():
            return f"{lcsc}:{lcsc}"
    return None


def resolve_part_symbol(part, *, signoff: bool = False) -> ResolvedSymbol:
    """SSO-010: explicit → vendor → same-lib pin-parity → synth.

    Never instance a library id that is missing on disk or whose pin numbers
    do not cover the live graph (MCU/USB parity).
    """
    lib_id = declared_lib_id(part)
    if lib_id and _lib_has_symbol(lib_id) and library_covers_graph_pins(lib_id, part):
        parsed = parse_kicad_symbol_id(lib_id)
        path = find_symbol_library_file(parsed[0]) if parsed else None
        return ResolvedSymbol(lib_id, path, "explicit", True)

    vendor = _vendor_lib_id(part)
    if vendor and _lib_has_symbol(vendor) and library_covers_graph_pins(vendor, part):
        parsed = parse_kicad_symbol_id(vendor)
        path = find_symbol_library_file(parsed[0]) if parsed else None
        return ResolvedSymbol(vendor, path, "vendor", True)

    parity = find_pin_parity_lib_id(part, lib_id)
    if parity and _lib_has_symbol(parity):
        parsed = parse_kicad_symbol_id(parity)
        path = find_symbol_library_file(parsed[0]) if parsed else None
        logger.info(
            "SSO pin-parity: %s declared=%s → %s",
            part_ref(part),
            lib_id,
            parity,
        )
        return ResolvedSymbol(parity, path, "parity", True)

    if lib_id and not _lib_has_symbol(lib_id):
        logger.debug("Declared lib_id %s not on disk for %s; synthesizing", lib_id, part_ref(part))

    recs = pinout_records(part)
    pin_ok = bool(recs) and all(str(r.get("num") or "").strip() for r in recs)

    device_lib = find_symbol_library_file("Device")
    if signoff and looks_like_device_passive(part) and device_lib is not None:
        # Must bind a real Device (or vendor) symbol — never a fake zigzag.
        if not (lib_id and _lib_has_symbol(lib_id)):
            raise SchematicGenerationError(
                f"SSO-010: passive {part_ref(part)} has no resolvable KiCad/vendor symbol "
                f"(declared={lib_id!r}) while Device library is present at {device_lib}."
            )

    if not pin_ok and signoff:
        raise SchematicGenerationError(
            f"SSO-010: part {part_ref(part)} has no library symbol and incomplete pinout."
        )

    synth_name = schematic_symbol_lib_key(part)
    return ResolvedSymbol(f"OpenHaC:{synth_name}", None, "synth", pin_ok)


def make_pin_resolver(*, generated_sym_path: str | None = None):
    if truthy_env("OPENHAC_SCHEMATIC_STUB_ONLY"):
        return EmptySymbolPinResolver()
    resolver = SymbolPinResolver()
    if generated_sym_path:
        resolver.add_explicit_library("OpenHaC", generated_sym_path)
    return resolver


def pin_offset(resolver, part, pin, symbol_name: str | None = None) -> tuple[float, float, float]:
    off = None
    try:
        off = resolver.offset_for_pin(part, pin, symbol_name=symbol_name)
    except Exception:
        off = None
    if off is not None:
        return float(off[0]), float(off[1]), float(off[2]) if len(off) > 2 else 0.0
    # Generic dual-column fallback (index order, not name keywords).
    pins = iter_pins(part)
    idx = 0
    for i, p in enumerate(pins):
        if p is pin or pin_num(p) == pin_num(pin):
            idx = i
            break
    row = idx // 2
    is_right = (idx % 2) == 1
    dx = 15.24 if is_right else -15.24
    dy = row * 2.54
    return dx, dy, 0.0


def _power_symbol_pin_index() -> dict[str, str]:
    """Map uppercased pin/symbol name → KiCad power symbol name (e.g. '+3V3')."""
    path = find_symbol_library_file("power")
    out: dict[str, str] = {}
    if path is None:
        return out
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    import re
    for m in re.finditer(r'\(symbol\s+"([^"]+)"', text):
        name = m.group(1)
        if "_" in name and name.rsplit("_", 1)[-1].isdigit():
            continue  # unit child symbols like GND_0_1
        key = name.upper().lstrip("+")
        out.setdefault(name.upper(), name)
        out.setdefault(key, name)
    return out


def match_power_symbol(net: str) -> tuple[str, str, bool]:
    """Return (lib_id, pin_name, is_gnd). Never reuse power:VCC for another rail (SSO-003)."""
    from openhac.schematic.util import is_gnd_net_name

    raw = str(net or "").strip()
    upper = raw.upper()
    is_gnd = is_gnd_net_name(raw)
    idx = _power_symbol_pin_index()
    candidates = [upper, upper.lstrip("+"), f"+{upper.lstrip('+')}"]
    found = None
    for c in candidates:
        found = idx.get(c) or idx.get(c.lstrip("+"))
        if found:
            break
    if found:
        if found.upper() in ("VCC", "+VCC") and upper not in ("VCC", "+VCC"):
            found = None
    if found:
        return f"power:{found}", found, is_gnd
    # Do not instance power:<net> — KiCad resolves `power` from the system library
    # and will report "symbol not found" / "doesn't match copy". SSO-003: pin name = net.
    # Unit children must be `{short}_0_1` / `{short}_1_1` (KiCad 9 rejects a mismatch).
    short = power_symbol_short_name(raw)
    return f"OpenHaC:{short}", raw, is_gnd

