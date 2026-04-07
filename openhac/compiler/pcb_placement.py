"""
Place SKiDL parts on a KiCad board and assign pad nets (PCB-001 / PCB-002).

Loads footprints from KiCad ``*.pretty`` directories (resolved via ``KICAD*_FOOTPRINT_DIR``
or common install paths), positions them from OpenHaC module placement, then attaches
``NETINFO_ITEM`` so ratsnest / DSN export see connectivity.
"""

from __future__ import annotations

import logging
import os
import re
import sys

from openhac.circuit import get_default_circuit
from openhac.core.base import Component, LayoutGenerationError, Module

logger = logging.getLogger("openhac.pcb_placement")


def parse_footprint_id(footprint: str | None) -> tuple[str, str] | None:
    """Split ``Library:FootprintName`` into ``(library, name)``."""
    if not footprint or not str(footprint).strip():
        return None
    s = str(footprint).strip()
    if ":" not in s:
        return None
    lib, name = s.split(":", 1)
    lib, name = lib.strip(), name.strip()
    if not lib or not name:
        return None
    return lib, name


def footprint_search_roots() -> list[str]:
    """Ordered KiCad footprint root directories (contain ``*.pretty`` folders)."""
    roots: list[str] = []
    for key in ("KICAD9_FOOTPRINT_DIR", "KICAD8_FOOTPRINT_DIR", "KICAD_FOOTPRINT_DIR"):
        v = os.environ.get(key)
        if v and os.path.isdir(v):
            roots.append(os.path.normpath(v))
    if sys.platform.startswith("linux"):
        sys_paths = ("/usr/share/kicad/footprints", "/usr/local/share/kicad/footprints")
        for p in sys_paths:
            if os.path.isdir(p) and p not in roots:
                roots.append(p)
    # de-dupe preserving order
    seen: set[str] = set()
    out: list[str] = []
    for r in roots:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


def kicad_mod_pad_numbers(kicad_mod_body: str) -> set[str]:
    """Best-effort pad numbers/names from a ``.kicad_mod`` file body (PCB-002 diagnostics)."""
    names: set[str] = set()
    for m in re.finditer(r'\(pad\s+"([^"]+)"', kicad_mod_body):
        names.add(m.group(1))
    for m in re.finditer(r"\(pad\s+(\d+)\s+", kicad_mod_body):
        names.add(m.group(1))
    return names


def footprint_pad_numbers_from_library(lib_name: str, fp_name: str) -> set[str] | None:
    """Load pad set from ``{fp_name}.kicad_mod`` under ``{lib_name}.pretty``, or None if missing."""
    pretty_dir = resolve_pretty_directory(lib_name)
    if not pretty_dir:
        return None
    path = os.path.join(pretty_dir, f"{fp_name}.kicad_mod")
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8", errors="replace") as f:
        return kicad_mod_pad_numbers(f.read())


def pin_pad_coverage_warnings(circuit) -> list[str]:
    """Pre-flight: SKiDL pins on nets whose numbers are absent from the footprint's ``.kicad_mod``.

    Does not require ``pcbnew``. Use before ``place_circuit_on_board`` to catch pad-name mismatches (PCB-002).
    """
    try:
        from skidl import NC as SKIDL_NC
    except Exception:
        SKIDL_NC = None

    messages: list[str] = []
    for part in circuit.parts:
        fpid = parse_footprint_id(getattr(part, "footprint", None))
        if fpid is None:
            continue
        pads = footprint_pad_numbers_from_library(fpid[0], fpid[1])
        if pads is None:
            continue
        for pin in part.pins:
            try:
                if SKIDL_NC is not None and pin.net is SKIDL_NC:
                    continue
            except Exception:
                pass
            if pin.net is None:
                continue
            pnum = str(pin.num)
            if pnum not in pads:
                messages.append(
                    f"Part {part.ref}: footprint {part.footprint!r} has no pad {pnum!r} "
                    f"for net {getattr(pin.net, 'name', pin.net)}; PCB net assignment may fail."
                )
    return sorted(messages)


def resolve_pretty_directory(library_name: str) -> str | None:
    """Return path to ``{library_name}.pretty`` if found under any search root."""
    folder = f"{library_name}.pretty"
    for root in footprint_search_roots():
        path = os.path.join(root, folder)
        if os.path.isdir(path):
            return path
    return None


def collect_skidl_part_positions(board) -> dict[object, tuple[float, float]]:
    """Map each SKiDL ``Part`` to ``(x_mm, y_mm)`` using module placement + local grid."""
    positions: dict[object, tuple[float, float]] = {}
    all_mods = getattr(board, "all_modules", None)
    if not all_mods and hasattr(board, "_get_all_modules"):
        all_mods = board._get_all_modules()
    if not all_mods:
        all_mods = list(board.modules)

    for mod in all_mods:
        ax = float(mod.placed_x) if mod.placed_x is not None else 5.0
        ay = float(mod.placed_y) if mod.placed_y is not None else 5.0
        idx = 0
        for child in mod.components:
            if isinstance(child, Module):
                continue
            part = getattr(child, "part", None)
            if part is None:
                continue
            col = idx % 8
            row = idx // 8
            positions[part] = (ax + col * 4.5, ay + row * 4.5)
            idx += 1
    return positions


def _get_kicad_sexp_plugin(pcbnew):
    return pcbnew.PCB_IO_MGR.PluginFind(pcbnew.PCB_IO_MGR.KICAD_SEXP)


def _find_pad(fp, pin_num: str):
    key = str(pin_num)
    for pad in fp.Pads():
        try:
            if str(pad.GetPadName()) == key:
                return pad
        except Exception:
            pass
        try:
            if str(pad.GetNumber()) == key:
                return pad
        except Exception:
            pass
    return None


def _to_board_vec(pcbnew, x_mm: float, y_mm: float):
    x = int(pcbnew.FromMM(x_mm))
    y = int(pcbnew.FromMM(y_mm))
    try:
        return pcbnew.VECTOR2I(x, y)
    except AttributeError:
        return pcbnew.wxPoint(x, y)


def place_circuit_on_board(pcb, board, pcbnew_mod) -> None:
    """Add footprints for every part in the default SKiDL circuit and assign nets."""
    try:
        from skidl import NC as SKIDL_NC
    except Exception:
        SKIDL_NC = None

    circuit = get_default_circuit()
    for msg in pin_pad_coverage_warnings(circuit):
        logger.debug("%s", msg)

    part_positions = collect_skidl_part_positions(board)
    plugin = _get_kicad_sexp_plugin(pcbnew_mod)
    net_cache: dict[str, object] = {}
    fallback_i = 0

    for part in circuit.parts:
        fpid = parse_footprint_id(getattr(part, "footprint", None))
        if fpid is None:
            logger.warning("Part %s: no usable Library:Name footprint; skipping PCB placement.", part.ref)
            continue

        lib_name, fp_name = fpid
        pretty_dir = resolve_pretty_directory(lib_name)
        if not pretty_dir:
            raise LayoutGenerationError(
                f"Footprint library directory not found for '{lib_name}.pretty'. "
                f"Set KICAD8_FOOTPRINT_DIR (or KICAD9_FOOTPRINT_DIR) to your KiCad "
                f"footprints root (folder that contains *.pretty). Searched: {footprint_search_roots()}"
            )

        fp = plugin.FootprintLoad(pretty_dir, fp_name)
        if fp is None:
            raise LayoutGenerationError(
                f"Failed to load footprint '{fp_name}' from {pretty_dir} for part {part.ref}."
            )

        pcb.Add(fp)
        fp.SetReference(part.ref)
        val = getattr(part, "value", None) or part.name
        fp.SetValue(str(val))

        if part in part_positions:
            x_mm, y_mm = part_positions[part]
        else:
            col = fallback_i % 12
            row = fallback_i // 12
            x_mm, y_mm = 8.0 + col * 5.0, 8.0 + row * 5.0
            fallback_i += 1
            logger.debug("Part %s: no module anchor; using fallback grid (%.1f, %.1f) mm", part.ref, x_mm, y_mm)

        fp.SetPosition(_to_board_vec(pcbnew_mod, x_mm, y_mm))

        # Optional rotation hint (degrees) carried on SKiDL part fields.
        try:
            fields = getattr(part, "fields", None)
            rot = None
            if isinstance(fields, dict) and fields.get("OpenHaC_Rotation_Deg") is not None:
                rot = float(fields.get("OpenHaC_Rotation_Deg"))
            if rot is not None:
                # KiCad pcbnew uses tenths of degrees in older APIs; in newer it is degrees.
                # Try common setters; ignore if unavailable.
                if hasattr(fp, "SetOrientationDegrees"):
                    fp.SetOrientationDegrees(rot)
                elif hasattr(fp, "SetOrientation"):
                    try:
                        fp.SetOrientation(int(rot * 10))
                    except Exception:
                        fp.SetOrientation(rot)
        except Exception:
            pass

        for pin in part.pins:
            try:
                if SKIDL_NC is not None and pin.net is SKIDL_NC:
                    continue
            except Exception:
                pass
            if pin.net is None:
                continue
            net_name = str(pin.net.name)
            if not net_name:
                continue
            if net_name not in net_cache:
                ni = pcbnew_mod.NETINFO_ITEM(pcb, net_name)
                pcb.Add(ni)
                net_cache[net_name] = ni
            pad = _find_pad(fp, str(pin.num))
            if pad is None:
                logger.warning(
                    "Part %s: no pad matching SKiDL pin %s (%s); net %s not attached on PCB.",
                    part.ref,
                    pin.num,
                    getattr(pin, "name", ""),
                    net_name,
                )
                continue
            try:
                pad.SetNet(net_cache[net_name])
            except Exception as e:
                logger.warning("Part %s pin %s: SetNet failed: %s", part.ref, pin.num, e)

    try:
        pcb.BuildConnectivity()
    except Exception as e:
        logger.debug("BuildConnectivity: %s", e)
