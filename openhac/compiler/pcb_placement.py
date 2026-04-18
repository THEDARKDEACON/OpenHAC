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

# Best-effort compile post-report capture (dev/handoff diagnostics).
_PAD_MISMATCH_EVENTS: list[dict] = []


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


class _BoardCircuitView:
    __slots__ = ("parts",)

    def __init__(self, parts: tuple[object, ...] | list[object]):
        self.parts = tuple(parts)


def circuit_parts_from_board(board) -> list[object]:
    """SKiDL parts attached under ``board.modules`` (same iteration as PCB placement)."""
    parts: list[object] = []
    seen: set[int] = set()
    for mod in getattr(board, "modules", []) or []:
        for child in getattr(mod, "components", []) or []:
            part = getattr(child, "part", None)
            if part is None:
                continue
            pid = id(part)
            if pid in seen:
                continue
            seen.add(pid)
            parts.append(part)
    return parts


def circuit_view_from_board(board) -> _BoardCircuitView:
    """Circuit-like object with ``.parts`` for :func:`pin_pad_coverage_warnings`."""
    return _BoardCircuitView(circuit_parts_from_board(board))


def pin_pad_coverage_warnings_for_board(board) -> list[str]:
    """Same as :func:`pin_pad_coverage_warnings` but uses ``board.modules`` (recommended for OpenHaC designs)."""
    return pin_pad_coverage_warnings(circuit_view_from_board(board))


def pin_pad_mismatch_records(board) -> list[dict]:
    """Structured pad↔pin mismatches for reports (ref, footprint, pins, sample pads from ``.kicad_mod``)."""
    try:
        from skidl import NC as SKIDL_NC
    except Exception:
        SKIDL_NC = None
    out: list[dict] = []
    for part in circuit_parts_from_board(board):
        fpid = parse_footprint_id(getattr(part, "footprint", None))
        if fpid is None:
            continue
        pads = footprint_pad_numbers_from_library(fpid[0], fpid[1])
        if pads is None:
            continue
        def _pad_sort_key(x: str) -> tuple:
            xs = str(x)
            return (0, int(xs)) if xs.isdigit() else (1, xs.lower())

        pads_sample = sorted(pads, key=_pad_sort_key)[:48]
        for pin in _iter_unique_pins(part):
            try:
                if SKIDL_NC is not None and pin.net is SKIDL_NC:
                    continue
            except Exception:
                pass
            if pin.net is None:
                continue
            pnum = str(getattr(pin, "num", None) or getattr(pin, "number", None) or "")
            pname = str(getattr(pin, "name", "") or "").strip()
            if not pnum and not pname:
                continue
            if _pin_covers_footprint_pad(pnum, pname, pads):
                continue
            key = pnum or pname
            out.append(
                {
                    "refdes": str(getattr(part, "ref", "") or ""),
                    "generic_name": str(getattr(part, "name", "") or "").strip(),
                    "footprint": str(getattr(part, "footprint", "") or ""),
                    "pin_num": str(pnum),
                    "pin_name": str(pname),
                    "net": str(getattr(pin.net, "name", pin.net)),
                    "footprint_pads_sample": pads_sample,
                }
            )
    return sorted(out, key=lambda d: (d.get("refdes", ""), d.get("pin_num", ""), d.get("pin_name", "")))


def pin_pad_coverage_warnings(circuit) -> list[str]:
    """Pre-flight: SKiDL pins on nets whose numbers are absent from the footprint's ``.kicad_mod``.

    Does not require ``pcbnew``. Use before ``place_circuit_on_board`` to catch pad-name mismatches (PCB-002).
    Pass a circuit with ``.parts`` (e.g. from :func:`circuit_view_from_board`).
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
        for pin in _iter_unique_pins(part):
            try:
                if SKIDL_NC is not None and pin.net is SKIDL_NC:
                    continue
            except Exception:
                pass
            if pin.net is None:
                continue
            pnum = str(getattr(pin, "num", None) or getattr(pin, "number", None) or "")
            pname = str(getattr(pin, "name", "") or "").strip()
            if not pnum and not pname:
                continue
            if _pin_covers_footprint_pad(pnum, pname, pads):
                continue
            key = pnum or pname
            messages.append(
                f"Part {part.ref}: footprint {part.footprint!r} has no pad matching pin {key!r} "
                f"(name={pname!r}) for net {getattr(pin.net, 'name', pin.net)}; PCB net assignment may fail."
            )
    return sorted(messages)


def _pin_synonyms_for_matching(pnum: str, pname: str) -> set[str]:
    """Extra tokens to match against KiCad footprint pad names (USB-C, naming drift)."""
    out: set[str] = set()
    for s in (pnum, pname):
        s = str(s or "").strip()
        if not s:
            continue
        out.add(s)
        out.add(s.replace("_", ""))
        out.add(s.replace("-", ""))
    n = str(pname or "").strip().lower()
    p = str(pnum or "").strip().lower()
    blob = f"{n} {p}".strip()
    # USB 2.0 / Type-C common synonyms (footprints vary: D+/D-, A6/A7, pad names)
    usb_pairs = (
        (("dp", "usb_dp", "d+"), ("D+", "DP", "USB_DP", "A6", "B6")),
        (("dm", "usb_dm", "d-"), ("D-", "DM", "USB_DM", "A7", "B7")),
        (("cc1",), ("CC1", "A5")),
        (("cc2",), ("CC2", "B5")),
        (("sbu1",), ("SBU1",)),
        (("sbu2",), ("SBU2",)),
        (("vbus",), ("VBUS", "A4", "B4", "A9", "B9")),
        (("gnd", "ground"), ("GND", "A1", "B1", "A12", "B12")),
    )
    for keys, vals in usb_pairs:
        if any(k in blob for k in keys):
            out.update(vals)
    return {x for x in out if x}


def _pin_covers_footprint_pad(pnum: str, pname: str, pads: set[str]) -> bool:
    """Return True if *pnum* or *pname* (case-insensitive) exists on the footprint pad set."""
    if not pads:
        return False
    low = {str(p).lower() for p in pads}
    for tok in _pin_synonyms_for_matching(pnum, pname):
        if tok in pads:
            return True
        t = tok.lower()
        if t in low:
            return True
    # LED A/K ↔ 1/2 when footprint is numeric-only
    alias = {"a": "1", "k": "2", "c": "2", "anode": "1", "cathode": "2"}
    n = str(pnum or "").strip()
    nm = str(pname or "").strip()
    for lbl in (nm, n):
        al = lbl.lower()
        if al in alias and alias[al] in pads:
            return True
    return False


def resolve_pretty_directory(library_name: str) -> str | None:
    """Return path to ``{library_name}.pretty`` if found under any search root."""
    folder = f"{library_name}.pretty"
    for root in footprint_search_roots():
        path = os.path.join(root, folder)
        if os.path.isdir(path):
            return path
    return None


def _fp_size_mm_for_part(
    part,
    plugin,
    pcbnew_mod,
    cache: dict[tuple[str, str], tuple[float, float]],
    *,
    grid_mm: float,
) -> tuple[float, float]:
    """Return footprint width/height in mm from pcbnew load, or ``(grid_mm, grid_mm)``."""
    fpid = parse_footprint_id(getattr(part, "footprint", None))
    if fpid is None:
        return (grid_mm, grid_mm)
    if fpid in cache:
        return cache[fpid]
    pretty_dir = resolve_pretty_directory(fpid[0])
    if not pretty_dir:
        cache[fpid] = (grid_mm, grid_mm)
        return cache[fpid]
    try:
        fp = plugin.FootprintLoad(pretty_dir, fpid[1])
        if fp is None:
            raise ValueError("FootprintLoad returned None")
        bb = fp.GetBoundingBox()
        if hasattr(bb, "GetWidth") and hasattr(bb, "GetHeight"):
            w_iu = abs(int(bb.GetWidth()))
            h_iu = abs(int(bb.GetHeight()))
        else:
            w_iu = abs(int(bb.GetRight()) - int(bb.GetLeft()))
            h_iu = abs(int(bb.GetBottom()) - int(bb.GetTop()))
        w_mm = float(pcbnew_mod.ToMM(w_iu))
        h_mm = float(pcbnew_mod.ToMM(h_iu))
        out = (max(w_mm, 0.4), max(h_mm, 0.4))
    except Exception:
        out = (grid_mm, grid_mm)
    cache[fpid] = out
    return out


def collect_skidl_part_positions(board) -> dict[object, tuple[float, float]]:
    """Map each SKiDL ``Part`` to ``(x_mm, y_mm)`` using module placement + local grid.

    When ``OPENHAC_PLACEMENT_USE_FP_BBOX`` is enabled (default) and pcbnew can load
    footprints, parts are laid out in rows using each footprint's bounding-box size
    plus ``OPENHAC_PLACEMENT_FP_GAP_MM`` so large packages do not sit on a fixed
    7 mm pitch. Falls back to a fixed ``OPENHAC_PLACEMENT_GRID_MM`` grid otherwise.
    """
    positions: dict[object, tuple[float, float]] = {}
    all_mods = getattr(board, "all_modules", None)
    if not all_mods and hasattr(board, "_get_all_modules"):
        all_mods = board._get_all_modules()
    if not all_mods:
        all_mods = list(board.modules)

    use_fp = os.environ.get("OPENHAC_PLACEMENT_USE_FP_BBOX", "1").strip().lower() not in ("0", "false", "no", "off")
    plugin = None
    pcbnew_mod = None
    fp_cache: dict[tuple[str, str], tuple[float, float]] = {}
    if use_fp:
        try:
            import pcbnew as _pn  # type: ignore

            pcbnew_mod = _pn
            plugin = _get_kicad_sexp_plugin(_pn)
        except Exception:
            use_fp = False

    try:
        gap_mm = float(os.environ.get("OPENHAC_PLACEMENT_FP_GAP_MM", "").strip() or 1.0)
    except Exception:
        gap_mm = 1.0

    for mod in all_mods:
        ax = float(mod.placed_x) if mod.placed_x is not None else 5.0
        ay = float(mod.placed_y) if mod.placed_y is not None else 5.0
        try:
            grid_mm = float(os.environ.get("OPENHAC_PLACEMENT_GRID_MM", "").strip() or 7.0)
        except Exception:
            grid_mm = 7.0
        try:
            cols = int(os.environ.get("OPENHAC_PLACEMENT_GRID_COLS", "").strip() or 6)
        except Exception:
            cols = 6
        cols = max(1, cols)

        items: list[object] = []
        for child in mod.components:
            if isinstance(child, Module):
                continue
            part = getattr(child, "part", None)
            if part is None:
                continue
            items.append(part)

        if use_fp and plugin is not None and pcbnew_mod is not None:
            x_cursor = ax
            y_row = ay
            row_max_h = 0.0
            col = 0
            for part in items:
                fw, fh = _fp_size_mm_for_part(part, plugin, pcbnew_mod, fp_cache, grid_mm=grid_mm)
                positions[part] = (x_cursor, y_row)
                row_max_h = max(row_max_h, fh + gap_mm)
                col += 1
                x_cursor += fw + gap_mm
                if col >= cols:
                    col = 0
                    x_cursor = ax
                    y_row += row_max_h
                    row_max_h = 0.0
        else:
            for idx, part in enumerate(items):
                c = idx % cols
                r = idx // cols
                positions[part] = (ax + c * grid_mm, ay + r * grid_mm)
    return positions


def apply_pcbnew_pack_to_module_bboxes(board) -> int:
    """Shrink-wrap each module's ``width``/``height`` using the same row-pack as placement, with real pcbnew bboxes.

    Runs **after** :meth:`openhac.core.base.Module.recalculate_bbox_from_components` so the final
    module rectangle is ``max(heuristic, pcbnew_pack * inflate)``. Skips when pcbnew is unavailable,
    ``OPENHAC_MODULE_BBOX_FROM_FP_PACK`` is disabled, or ``OPENHAC_PLACEMENT_USE_FP_BBOX`` is off.

    Returns:
        Number of modules whose width or height **increased** from this pass.
    """
    if os.environ.get("OPENHAC_MODULE_BBOX_FROM_FP_PACK", "1").strip().lower() in (
        "0",
        "false",
        "no",
        "off",
    ):
        return 0
    if os.environ.get("OPENHAC_PLACEMENT_USE_FP_BBOX", "1").strip().lower() in ("0", "false", "no", "off"):
        return 0
    try:
        import pcbnew as pcbnew_mod  # type: ignore
    except Exception:
        logger.debug("apply_pcbnew_pack_to_module_bboxes: pcbnew not available")
        return 0

    plugin = _get_kicad_sexp_plugin(pcbnew_mod)
    fp_cache: dict[tuple[str, str], tuple[float, float]] = {}
    try:
        gap_mm = float(os.environ.get("OPENHAC_PLACEMENT_FP_GAP_MM", "").strip() or 1.0)
    except Exception:
        gap_mm = 1.0
    try:
        grid_mm = float(os.environ.get("OPENHAC_PLACEMENT_GRID_MM", "").strip() or 7.0)
    except Exception:
        grid_mm = 7.0
    try:
        cols = int(os.environ.get("OPENHAC_PLACEMENT_GRID_COLS", "").strip() or 6)
    except Exception:
        cols = 6
    cols = max(1, cols)
    try:
        inflate = float(os.environ.get("OPENHAC_MODULE_PACK_INFLATE", "").strip() or 1.15)
    except Exception:
        inflate = 1.15

    all_mods = getattr(board, "all_modules", None)
    if not all_mods and hasattr(board, "_get_all_modules"):
        all_mods = board._get_all_modules()
    if not all_mods:
        all_mods = list(getattr(board, "modules", []) or [])

    enlarged = 0
    for mod in all_mods:
        items: list[object] = []
        for child in getattr(mod, "components", []) or []:
            if isinstance(child, Module):
                continue
            part = getattr(child, "part", None)
            if part is None:
                continue
            items.append(part)
        if not items:
            continue

        ax, ay = 0.0, 0.0
        x_cursor, y_row = ax, ay
        row_max_h = 0.0
        col = 0
        max_r = ax
        max_b = ay
        for part in items:
            fw, fh = _fp_size_mm_for_part(part, plugin, pcbnew_mod, fp_cache, grid_mm=grid_mm)
            left, top = x_cursor, y_row
            max_r = max(max_r, left + fw)
            max_b = max(max_b, top + fh)
            row_max_h = max(row_max_h, fh + gap_mm)
            col += 1
            x_cursor += fw + gap_mm
            if col >= cols:
                col = 0
                x_cursor = ax
                y_row += row_max_h
                row_max_h = 0.0

        w_pack = max(0.0, max_r - ax) * inflate
        h_pack = max(0.0, max_b - ay) * inflate
        if w_pack <= 0 or h_pack <= 0:
            continue

        old_w, old_h = float(mod.width), float(mod.height)
        mod.width = max(old_w, w_pack)
        mod.height = max(old_h, h_pack)
        if mod.width > old_w + 1e-9 or mod.height > old_h + 1e-9:
            enlarged += 1
            logger.debug(
                "Module %r bbox from pcbnew pack: %.2fx%.2f mm (was %.2fx%.2f)",
                getattr(mod, "name", "?"),
                mod.width,
                mod.height,
                old_w,
                old_h,
            )
    return enlarged


def _get_kicad_sexp_plugin(pcbnew):
    return pcbnew.PCB_IO_MGR.PluginFind(pcbnew.PCB_IO_MGR.KICAD_SEXP)


def _pad_keys(pad) -> list[str]:
    """Best-effort pad identifiers from a pcbnew ``PAD`` (name vs number differ per library)."""
    keys: list[str] = []
    for getter in ("GetPadName", "GetNumber"):
        try:
            fn = getattr(pad, getter, None)
            if not fn:
                continue
            s = str(fn()).strip()
            if s and s not in keys:
                keys.append(s)
        except Exception:
            pass
    return keys


def find_pad_for_pin(fp, pin_num: str, pin_name: str | None = None):
    """Map a SKiDL/native logical pin to a pcbnew footprint pad.

    Tries, in order:

    1. ``FindPadByNumber`` / pad match for **pin number** (KiCad convention: matches footprint pad).
    2. Same for **pin name** when it differs from the number (designs use ``part['VIN']`` while pads are ``VIN``).
    3. Case-insensitive name match on ``GetPadName`` / ``GetNumber``.
    4. LED/diode shorthand: ``A``/``K`` ↔ ``1``/``2`` when the footprint only exposes numeric pads.

    Returns ``None`` if no pad matches.
    """
    raw_num = str(pin_num or "").strip()
    raw_name = (str(pin_name).strip() if pin_name else "") or ""

    candidates: list[str] = []
    if raw_num:
        candidates.append(raw_num)
    if raw_name and raw_name not in candidates:
        candidates.append(raw_name)
    seen_c: set[str] = set(candidates)
    for syn in _pin_synonyms_for_matching(raw_num, raw_name):
        if syn and syn not in seen_c:
            seen_c.add(syn)
            candidates.append(syn)

    # KiCad FOOTPRINT API (preferred — matches GUI behavior)
    try:
        for c in candidates:
            try:
                p = fp.FindPadByNumber(c)
                if p is not None:
                    return p
            except Exception:
                pass
    except Exception:
        pass

    # Walk pads (fallback + case-insensitive)
    def _norm(s: str) -> str:
        return str(s).strip().lower()

    want = {_norm(x) for x in candidates if x}
    if not want:
        return None

    pads = list(fp.Pads())
    for pad in pads:
        for k in _pad_keys(pad):
            if _norm(k) in want:
                return pad

    # LED / diode: symbol pins A/K often map to footprint 1/2
    alias_map = {
        "a": ("1", "2"),
        "k": ("2", "1"),
        "c": ("2", "1"),
        "anode": ("1", "2"),
        "cathode": ("2", "1"),
    }
    for label in (raw_name, raw_num):
        al = _norm(label)
        if al in alias_map:
            for try_num in alias_map[al]:
                try:
                    p = fp.FindPadByNumber(try_num)
                    if p is not None:
                        return p
                except Exception:
                    pass
                for pad in pads:
                    for k in _pad_keys(pad):
                        if k == try_num:
                            return pad

    return None


def _iter_unique_pins(part) -> list:
    """Deduplicate pins: native :class:`~openhac.core.part.Part` indexes the same ``Pin`` by number and by name."""
    pins_raw = part.pins.values() if isinstance(getattr(part, "pins", None), dict) else getattr(part, "pins", [])
    if isinstance(pins_raw, dict):
        pins_raw = pins_raw.values()
    seen: set[int] = set()
    out = []
    for pin in pins_raw:
        pid = id(pin)
        if pid in seen:
            continue
        seen.add(pid)
        out.append(pin)
    return out


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

    circuit = circuit_view_from_board(board)
    for msg in pin_pad_coverage_warnings(circuit):
        logger.debug("%s", msg)

    part_positions = collect_skidl_part_positions(board)
    plugin = _get_kicad_sexp_plugin(pcbnew_mod)
    net_cache: dict[str, object] = {}
    fallback_i = 0
    fabrication = False
    try:
        fabrication = str(getattr(board, "effective_compile_goal", lambda: "")()).strip().lower() == "fabrication"
    except Exception:
        fabrication = False

    for part in circuit.parts:
        fpid = parse_footprint_id(getattr(part, "footprint", None))
        if fpid is None:
            logger.warning("Part %s: no usable Library:Name footprint; skipping PCB placement.", part.ref)
            continue

        lib_name, fp_name = fpid
        pretty_dir = resolve_pretty_directory(lib_name)
        if not pretty_dir:
            msg = (
                f"Footprint library directory not found for '{lib_name}.pretty'. "
                f"Searched: {footprint_search_roots()}"
            )
            if fabrication:
                raise LayoutGenerationError(msg)
            logger.warning("%s; skipping part %s in PCB placement (handoff/dev).", msg, getattr(part, "ref", "?"))
            continue

        fp = plugin.FootprintLoad(pretty_dir, fp_name)
        if fp is None:
            msg = f"Failed to load footprint '{fp_name}' from {pretty_dir} for part {getattr(part, 'ref', '?')}."
            if fabrication:
                raise LayoutGenerationError(msg)
            logger.warning("%s Skipping part in PCB placement (handoff/dev).", msg)
            continue

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

        for pin in _iter_unique_pins(part):
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
            pnum = str(getattr(pin, "num", None) or getattr(pin, "number", None) or "")
            pname = str(getattr(pin, "name", "") or "").strip()
            if not pnum and not pname:
                continue
            pad = find_pad_for_pin(fp, pnum, pname or None)
            if pad is None:
                logger.warning(
                    "Part %s: no pad matching SKiDL pin %s (%s); net %s not attached on PCB.",
                    part.ref,
                    pnum or "?",
                    pname,
                    net_name,
                )
                try:
                    _PAD_MISMATCH_EVENTS.append(
                        {
                            "refdes": str(getattr(part, "ref", "") or ""),
                            "generic_name": str(getattr(part, "name", "") or "").strip(),
                            "footprint": str(getattr(part, "footprint", "") or ""),
                            "pin_num": str(pnum),
                            "pin_name": str(getattr(pin, "name", "") or ""),
                            "net": str(net_name),
                        }
                    )
                except Exception:
                    pass
                continue
            try:
                pad.SetNet(net_cache[net_name])
            except Exception as e:
                logger.warning("Part %s pin %s: SetNet failed: %s", part.ref, pnum, e)

    try:
        pcb.BuildConnectivity()
    except Exception as e:
        logger.debug("BuildConnectivity: %s", e)
