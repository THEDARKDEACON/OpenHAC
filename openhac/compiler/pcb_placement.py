"""
Place SKiDL parts on a KiCad board and assign pad nets (PCB-001 / PCB-002).

Loads footprints from KiCad ``*.pretty`` directories (resolved via ``KICAD*_FOOTPRINT_DIR``
or common install paths), positions them from OpenHaC module placement, then attaches
``NETINFO_ITEM`` so ratsnest / DSN export see connectivity.
"""

from __future__ import annotations

import logging
import math
import os
import re
import sys
from typing import Any

from openhac.circuit import get_default_circuit
from openhac.core.base import Component, LayoutGenerationError, Module

logger = logging.getLogger("openhac.pcb_placement")

# Best-effort compile post-report capture (dev/handoff diagnostics).
_PAD_MISMATCH_EVENTS: list[dict] = []
# FAB-003: refs skipped during placement (missing footprint); cleared at start of place.
_OMITTED_FOOTPRINT_REFS: list[str] = []


def drain_omitted_footprint_refs() -> list[str]:
    """Return and clear omitted footprint refs recorded during the last place pass."""
    out = list(_OMITTED_FOOTPRINT_REFS)
    _OMITTED_FOOTPRINT_REFS.clear()
    return out


def record_omitted_footprint_ref(ref: str) -> None:
    r = str(ref or "").strip() or "?"
    if r not in _OMITTED_FOOTPRINT_REFS:
        _OMITTED_FOOTPRINT_REFS.append(r)


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
    
    # Add openhac global directory for generated footprints (e.g. easyeda_generated.pretty)
    from pathlib import Path
    openhac_root = Path.home() / ".kiro" / "openhac"
    if openhac_root.is_dir():
        roots.append(str(openhac_root))
        
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

    def __init__(self, parts: tuple[Any, ...] | list[Any]):
        self.parts = tuple(parts)


def circuit_parts_from_board(board) -> list[Any]:
    """SKiDL parts attached under ``board.modules`` (same iteration as PCB placement)."""
    parts: list[Any] = []
    seen: set[int] = set()
    
    modules = []
    if hasattr(board, "_get_all_modules"):
        modules = board._get_all_modules()
    else:
        modules = getattr(board, "modules", []) or []

    for mod in modules:
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
    SKIDL_NC: Any = None
    try:
        from openhac.core.net import NC as SKIDL_NC  # type: ignore[no-redef]
    except Exception as e:
        logger.debug("NC sentinel unavailable for pad mismatch scan: %s", e)
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
            except Exception as e:
                logger.debug("NC check skipped for pin: %s", e)
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
    SKIDL_NC: Any = None
    try:
        from openhac.core.net import NC as SKIDL_NC  # type: ignore[no-redef]
    except Exception as e:
        logger.debug("NC sentinel unavailable for pad coverage: %s", e)

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
            except Exception as e:
                logger.debug("NC check skipped for pin: %s", e)
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


def _footprint_pack_bbox(fp):
    """Courtyard-scale bbox for packing — exclude Reference/Value silk text.

    Default ``GetBoundingBox()`` includes library text, which turns a 0603 (~3 mm)
    into ~15 mm and inflates Z3 rooms into hundreds of mm.
    """
    for args in ((False, False), (False,)):
        try:
            bb = fp.GetBoundingBox(*args)
            if bb is not None:
                return bb
        except TypeError:
            continue
    return fp.GetBoundingBox()


def _module_pack_cols(n_items: int) -> int:
    """Column count for module AABB packing (sqrt grid, not global GRID_COLS)."""
    n = max(1, int(n_items))
    raw = (os.environ.get("OPENHAC_MODULE_PACK_COLS") or "").strip()
    if raw:
        try:
            return max(1, min(int(raw), n))
        except Exception:
            pass
    return max(1, int(math.ceil(math.sqrt(n))))


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
        bb = _footprint_pack_bbox(fp)
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


def collect_skidl_part_positions(board) -> dict[Any, tuple[float, float]]:
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

    from openhac.compiler.placement_engine import shelf_pack

    for mod in all_mods:
        ax = float(mod.placed_x) if mod.placed_x is not None else 5.0
        ay = float(mod.placed_y) if mod.placed_y is not None else 5.0
        try:
            grid_mm = float(os.environ.get("OPENHAC_PLACEMENT_GRID_MM", "").strip() or 7.0)
        except Exception:
            grid_mm = 7.0

        items: list[object] = []
        for child in mod.components:
            if isinstance(child, Module):
                continue
            part = getattr(child, "part", None)
            if part is None:
                continue
            items.append(part)
        if not items:
            continue

        sized: list[tuple[object, float, float]] = []
        if use_fp and plugin is not None and pcbnew_mod is not None:
            for part in items:
                fw, fh = _fp_size_mm_for_part(part, plugin, pcbnew_mod, fp_cache, grid_mm=grid_mm)
                sized.append((part, fw, fh))
        else:
            sized = [(part, grid_mm, grid_mm) for part in items]
        local, _, _ = shelf_pack(sized, gap=gap_mm)
        for part, (lx, ly) in local.items():
            positions[part] = (ax + lx, ay + ly)
    return positions


def apply_pcbnew_pack_to_module_bboxes(board) -> int:
    """Shrink-wrap each module's ``width``/``height`` using the same row-pack as placement, with real pcbnew bboxes.

    Runs **after** :meth:`openhac.core.base.Module.recalculate_bbox_from_components` so the final
    module rectangle is the pcbnew shelf-pack (inflate slack only). Skips when pcbnew is unavailable,
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
        inflate = float(os.environ.get("OPENHAC_MODULE_PACK_INFLATE", "").strip() or 1.15)
    except Exception:
        inflate = 1.15
    if inflate > 1.5:
        logger.warning(
            "OPENHAC_MODULE_PACK_INFLATE=%.2f inflates module rooms (not routing channels); "
            "1.15–1.35 is typical. Affinity floorplan cannot hide oversized AABBs.",
            inflate,
        )

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

        sized: list[tuple[object, float, float]] = []
        for part in items:
            fw, fh = _fp_size_mm_for_part(part, plugin, pcbnew_mod, fp_cache, grid_mm=grid_mm)
            sized.append((part, fw, fh))
        from openhac.compiler.placement_engine import shelf_pack

        _pos, pack_w, pack_h = shelf_pack(sized, gap=gap_mm)
        w_pack = pack_w * inflate
        h_pack = pack_h * inflate
        if w_pack <= 0 or h_pack <= 0:
            continue

        old_w, old_h = float(mod.width), float(mod.height)
        # True shrink-wrap to courtyard pack (do not keep a larger heuristic box).
        mod.width = w_pack
        mod.height = h_pack
        mod._cluster_core_wh = (w_pack, h_pack)
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
        except Exception as e:
            logger.debug("pad key via %s failed: %s", getter, e)
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
            except Exception as e:
                logger.debug("FindPadByNumber(%r) failed: %s", c, e)
    except Exception as e:
        logger.debug("FindPadByNumber path unavailable: %s", e)

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
                except Exception as e:
                    logger.debug("FindPadByNumber alias %r failed: %s", try_num, e)
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
    SKIDL_NC: Any = None
    try:
        from openhac.core.net import NC as SKIDL_NC  # type: ignore[no-redef]
    except Exception as e:
        logger.debug("NC sentinel unavailable during placement: %s", e)

    _OMITTED_FOOTPRINT_REFS.clear()
    circuit = circuit_view_from_board(board)
    pad_msgs = pin_pad_coverage_warnings(circuit)
    for msg in pad_msgs:
        # FAB-002: pad mismatches are warnings by default (not debug-only).
        logger.warning("%s", msg)
    try:
        board._last_pad_pin_warnings = list(pad_msgs)
    except Exception as e:
        logger.debug("Could not stash pad/pin warnings on board: %s", e)

    part_positions = collect_skidl_part_positions(board)
    plugin = _get_kicad_sexp_plugin(pcbnew_mod)
    net_cache: dict[str, object] = {}
    fallback_i = 0
    circuit_parts = list(circuit.parts)  # type: Any
    fabrication = False
    try:
        fabrication = str(getattr(board, "effective_compile_goal", lambda: "")()).strip().lower() == "fabrication"
    except Exception as e:
        logger.debug("Could not resolve fabrication goal for placement: %s", e)
        fabrication = False

    for part in circuit.parts:  # type: Any
        fpid = parse_footprint_id(getattr(part, "footprint", None))
        if fpid is None:
            ref = getattr(part, "ref", "?")
            logger.warning("Part %s: no usable Library:Name footprint; skipping PCB placement.", ref)
            record_omitted_footprint_ref(str(ref))
            if fabrication:
                raise LayoutGenerationError(
                    f"FAB-003: part {ref} has no usable Library:Name footprint in fabrication mode."
                )
            continue

        lib_name, fp_name = fpid
        pretty_dir = resolve_pretty_directory(lib_name)
        if not pretty_dir:
            # --- EasyEDA auto-download fallback ---
            # The footprint isn't in any local KiCad library. Try to fetch it from
            # EasyEDA using the part's LCSC ID (same pipeline used for 3D models).
            lcsc_id = None
            fields = getattr(part, "fields", {}) or {}
            for field_key in ("LCSC", "lcsc", "lcsc_id", "supplier_sku", "Supplier_SKU"):
                v = fields.get(field_key)
                if v and str(v).strip().startswith("C"):
                    lcsc_id = str(v).strip()
                    break

            easyeda_fp_id = None
            if lcsc_id:
                try:
                    from openhac.database.easyeda_integration import generate_footprint_from_lcsc
                    logger.info(
                        "Part %s: footprint '%s:%s' not found locally — fetching from EasyEDA (LCSC: %s)...",
                        getattr(part, "ref", "?"), lib_name, fp_name, lcsc_id,
                    )
                    easyeda_fp_id = generate_footprint_from_lcsc(lcsc_id)
                    if easyeda_fp_id:
                        logger.info("Part %s: downloaded footprint '%s' via EasyEDA.", getattr(part, "ref", "?"), easyeda_fp_id)
                        part.footprint = easyeda_fp_id
                        fpid = parse_footprint_id(easyeda_fp_id)
                        if fpid:
                            lib_name, fp_name = fpid
                            pretty_dir = resolve_pretty_directory(lib_name)
                except Exception as e:
                    logger.warning("EasyEDA footprint fetch failed for %s (LCSC: %s): %s", getattr(part, "ref", "?"), lcsc_id, e)

            if not pretty_dir:
                msg = (
                    f"Footprint library directory not found for '{lib_name}.pretty'. "
                    f"Searched: {footprint_search_roots()}"
                    + (f" EasyEDA fallback also failed (LCSC: {lcsc_id})." if lcsc_id else " No LCSC ID available for EasyEDA fallback.")
                )
                if fabrication:
                    raise LayoutGenerationError(msg)
                logger.warning("%s; skipping part %s in PCB placement (handoff/dev).", msg, getattr(part, "ref", "?"))
                record_omitted_footprint_ref(str(getattr(part, "ref", "?")))
                continue

        if fpid is None:
            msg = f"Part {getattr(part, 'ref', '?')}: footprint id unresolved after library search."
            if fabrication:
                raise LayoutGenerationError(msg)
            logger.warning("%s; skipping part in PCB placement (handoff/dev).", msg)
            record_omitted_footprint_ref(str(getattr(part, "ref", "?")))
            continue
        lib, fp_name = fpid
        pretty_path = resolve_pretty_directory(lib)
        if pretty_path:
            fp = plugin.FootprintLoad(pretty_path, fp_name)
        else:
            fp = pcbnew_mod.FootprintLoad(lib, fp_name)
        if fp is None:
            msg = f"Failed to load footprint '{fp_name}' from {pretty_path or lib} for part {getattr(part, 'ref', '?')}."
            if fabrication:
                raise LayoutGenerationError(msg)
            logger.warning("%s Skipping part in PCB placement (handoff/dev).", msg)
            record_omitted_footprint_ref(str(getattr(part, "ref", "?")))
            continue
        
        pcb.Add(fp)
        fp.SetReference(part.ref)
        try:
            from openhac.schematic.kicad_links import bind_footprint_schematic_path

            bind_footprint_schematic_path(fp, part, pcbnew_mod, parts=circuit_parts)
        except Exception as e:
            logger.debug("Schematic path bind skipped for %s: %s", getattr(part, "ref", "?"), e)
        val = getattr(part, "value", None) or part.name
        fp.SetValue(str(val))
        
        # Attach 3D model if metadata exists (PCB-008)
        fields = getattr(part, "fields", {}) or {}
        m3d = fields.get("Model_3D_Local")
        if m3d and os.path.isfile(str(m3d)):
            try:
                m = pcbnew_mod.FP_3DMODEL()
                m.m_Filename = str(os.path.abspath(m3d))
                
                # Set explicit defaults (KiCad 8+ requires these to be set or they may default to 0)
                try:
                    # Try direct attribute assignment (common in KiCad 8/9 Python)
                    for attr, val in [("m_Scale", 1.0), ("m_Offset", 0.0), ("m_Rotation", 0.0)]:
                        vec = getattr(m, attr)
                        if hasattr(vec, "x"):
                            vec.x, vec.y, vec.z = val, val, val
                        elif hasattr(pcbnew_mod, "VECTOR3D"):
                            setattr(m, attr, pcbnew_mod.VECTOR3D(val, val, val))
                except Exception as e:
                    logger.debug("Minor: 3D model property init partial for %s: %s", part.ref, e)

                # Clear existing models to prevent duplicates (KiCad 8+)
                if hasattr(fp, "Models"):
                    try:
                        # Only clear if we actually have a replacement model to add
                        fp.Models().clear()
                    except Exception as e:
                        logger.debug("Could not clear existing 3D models on %s: %s", part.ref, e)
                    fp.Models().push_back(m)
                elif hasattr(fp, "AddModel"):
                    fp.AddModel(m)
                logger.info("Attached 3D model to %s: %s", part.ref, m3d)
            except Exception as e:
                logger.warning("Failed to attach 3D model to %s: %s", part.ref, e)

        if part in part_positions:
            x_mm, y_mm = part_positions[part]
        else:
            col = fallback_i % 12
            row = fallback_i // 12
            x_mm, y_mm = 8.0 + col * 5.0, 8.0 + row * 5.0
            fallback_i += 1
            logger.debug("Part %s: no module anchor; using fallback grid (%.1f, %.1f) mm", part.ref, x_mm, y_mm)

        # Pack cells are courtyard AABB top-left; KiCad origins are often pad-center.
        try:
            bb = _footprint_pack_bbox(fp)
            x_mm -= float(pcbnew_mod.ToMM(int(bb.GetLeft())))
            y_mm -= float(pcbnew_mod.ToMM(int(bb.GetTop())))
        except Exception:
            pass
        fp.SetPosition(_to_board_vec(pcbnew_mod, x_mm, y_mm))

        # Optional rotation hint (degrees) carried on SKiDL part fields.
        try:
            fields = getattr(part, "fields", None)
            rot = None
            if isinstance(fields, dict) and fields.get("OpenHaC_Rotation_Deg") is not None:
                rot = float(str(fields.get("OpenHaC_Rotation_Deg")))
            if rot is not None:
                # KiCad pcbnew uses tenths of degrees in older APIs; in newer it is degrees.
                # Try common setters; ignore if unavailable.
                if hasattr(fp, "SetOrientationDegrees"):
                    fp.SetOrientationDegrees(rot)
                elif hasattr(fp, "SetOrientation"):
                    try:
                        fp.SetOrientation(int(rot * 10))
                    except Exception as e:
                        logger.debug("SetOrientation tenths failed for %s: %s", part.ref, e)
                        fp.SetOrientation(rot)
        except Exception as e:
            logger.debug("Rotation apply skipped for %s: %s", getattr(part, "ref", "?"), e)

        for pin in _iter_unique_pins(part):
            try:
                if SKIDL_NC is not None and pin.net is SKIDL_NC:
                    continue
            except Exception as e:
                logger.debug("NC check skipped during pad net assign: %s", e)
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
                except Exception as e:
                    logger.debug("Could not record pad mismatch event: %s", e)
                continue
            try:
                pad.SetNet(net_cache[net_name])
            except Exception as e:
                logger.warning("Part %s pin %s: SetNet failed: %s", part.ref, pnum, e)

    try:
        pcb.BuildConnectivity()
    except Exception as e:
        logger.debug("BuildConnectivity: %s", e)
