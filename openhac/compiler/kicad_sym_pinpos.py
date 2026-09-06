"""
Resolve KiCad ``.kicad_sym`` pin positions for schematic wire endpoints (SCH-001).

When a symbol library file can be found, wire stubs attach at library pin ``(at x y)``
coordinates (mm, symbol-local). Otherwise callers should fall back to index-based stubs.
"""

from __future__ import annotations

import logging
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Optional

logger = logging.getLogger("openhac.kicad_sym")

def symbol_library_search_paths() -> list[Path]:
    """Ordered search paths for ``*.kicad_sym`` (env first, then common installs)."""
    paths: list[Path] = []
    
    # Add standard JLC2KiCAD output directory
    jlc_dir = Path.home() / ".kiro" / "openhac" / "jlc2kicad_generated"
    if jlc_dir.is_dir():
        paths.append(jlc_dir)
        
    extra = os.environ.get("OPENHAC_KICAD_SYMBOL_DIRS", "")
    for p in extra.split(os.pathsep):
        p = p.strip()
        if p:
            paths.append(Path(p).expanduser().resolve())
    for key in (
        "KICAD9_SYMBOL_DIR",
        "KICAD8_SYMBOL_DIR",
        "KICAD7_SYMBOL_DIR",
        "KICAD6_SYMBOL_DIR",
        "KICAD_SYMBOL_DIR",
    ):
        v = (os.environ.get(key) or "").strip()
        if v:
            paths.append(Path(v).expanduser().resolve())
    paths.append(Path("/usr/share/kicad/symbols"))
    # De-dup while preserving order
    seen: set[Path] = set()
    out: list[Path] = []
    for p in paths:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def find_symbol_library_file(lib_name: str) -> Path | None:
    """Return path to ``{lib_name}.kicad_sym`` if found on the search path."""
    if not lib_name:
        return None
    fn = f"{lib_name}.kicad_sym"
    for d in symbol_library_search_paths():
        p = d / fn
        if p.is_file():
            return p
    return None


def _balanced_paren(s: str, start: int) -> str:
    if start >= len(s) or s[start] != "(":
        raise ValueError("expected '('")
    depth = 0
    for j in range(start, len(s)):
        c = s[j]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return s[start : j + 1]
    raise ValueError("unbalanced S-expression")


def _extract_symbol_tree(lib_text: str, symbol_name: str) -> str | None:
    """Return the full ``(symbol "symbol_name" ...)`` subtree, or None."""
    esc = re.escape(symbol_name)
    pat = re.compile(rf'\(symbol\s+"{esc}"\s*[\(]')
    m = pat.search(lib_text)
    if not m:
        return None
    return _balanced_paren(lib_text, m.start())


def _iter_pin_blocks(symbol_tree: str) -> list[str]:
    out: list[str] = []
    i = 0
    while True:
        j = symbol_tree.find("(pin ", i)
        if j < 0:
            break
        try:
            blk = _balanced_paren(symbol_tree, j)
        except ValueError:
            break
        out.append(blk)
        i = j + len(blk)
    return out


_AT_RE = re.compile(r"\(at\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\)")
# Pin ``(name ...)`` / ``(number ...)`` are often followed by ``(effects ...)`` on the next
# line; do not require the closing ``)`` immediately after the opening quoted token.
_NUMBER_RE = re.compile(r'\(number\s+"([^"]*)"')
_NAME_RE = re.compile(r'\(name\s+"([^"]*)"')
_LENGTH_RE = re.compile(r"\(length\s+([-\d.]+)\)")
_EXTENDS_RE = re.compile(r'\(extends\s+"([^"]+)"\s*\)')


def _pin_electrical_type(blk: str) -> str:
    """First token after ``(pin`` in a pin block (e.g. ``passive``, ``power_in``)."""
    m = re.match(r"\(pin\s+(\S+)", blk.lstrip())
    return m.group(1) if m else "bidirectional"


def _stm32_symbol_name_aliases(symbol_name: str) -> list[str]:
    """KiCad libraries often use ``STM32F405RGTx`` while MPNs/catalog rows use ``STM32F405RGT6``."""
    s = str(symbol_name or "").strip()
    if not s:
        return []
    m = re.match(r"^(STM32F\d+RG)T\d$", s, flags=re.IGNORECASE)
    if not m:
        return []
    alt = f"{m.group(1)}Tx"
    return [alt] if alt.lower() != s.lower() else []


def _symbol_tree_has_pin_blocks(symbol_tree: str) -> bool:
    if not symbol_tree or "(pin " not in symbol_tree:
        return False
    # Pin ``(number ...)`` may be indented on its own line; do not require a single-line match.
    for blk in _iter_pin_blocks(symbol_tree):
        if _NUMBER_RE.search(blk):
            return True
    return False


def resolve_symbol_tree_for_pins(lib_text: str, symbol_name: str, *, _depth: int = 0) -> str | None:
    """Return a symbol subtree that contains pin definitions, following ``(extends ...)`` stubs.

    KiCad 8/9 often defines derivatives (e.g. ``TPS63001``) as a short stub that only
    ``(extends "TPS63000")`` while pins live under the base symbol. STM32 parts may use
    ``STM32F405RGTx`` in the library while the BOM says ``STM32F405RGT6``.
    """
    if _depth > 8:
        return None
    sym = str(symbol_name or "").strip()
    if not sym:
        return None
    candidates = [sym, *_stm32_symbol_name_aliases(sym)]
    tree: str | None = None
    for cand in candidates:
        tree = _extract_symbol_tree(lib_text, cand)
        if tree is not None:
            break
    if tree is None:
        return None
    if _symbol_tree_has_pin_blocks(tree):
        return tree
    m = _EXTENDS_RE.search(tree)
    if not m:
        return None
    parent = str(m.group(1) or "").strip()
    if not parent or parent == sym:
        return None
    return resolve_symbol_tree_for_pins(lib_text, parent, _depth=_depth + 1)


@lru_cache(maxsize=64)
def _cached_lib_symbol_sexp(path: str, inst_name: str, mtime_ns: int) -> str | None:
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    tree = resolve_symbol_tree_for_pins(text, inst_name)
    if tree is None:
        return None
    pm = re.match(r'\(symbol\s+"([^"]+)"', tree.lstrip())
    source_name = pm.group(1) if pm else inst_name
    lib = p.stem
    tree = _EXTENDS_RE.sub("", tree, count=1)
    tree = tree.replace(f'(symbol "{source_name}"', f'(symbol "{lib}:{inst_name}"', 1)
    if source_name != inst_name:
        tree = re.sub(
            rf'\(symbol\s+"{re.escape(source_name)}_(\d+)_(\d+)"',
            rf'(symbol "{inst_name}_\1_\2"',
            tree,
        )
    return tree


def schematic_lib_symbol_sexp(lib_id: str) -> str | None:
    """Return a ``lib_symbols``-ready ``(symbol "Lib:Name" ...)`` body, or None.

    Flattens ``(extends ...)`` so the cached copy is self-contained. Unit children
    are named ``{short}_N_M`` to match the name after the colon (KiCad 9).
    """
    parsed = parse_kicad_symbol_id(lib_id)
    if not parsed:
        return None
    lib, inst_name = parsed
    if lib in ("OpenHaC",):
        return None
    path = find_symbol_library_file(lib)
    if path is None:
        return None
    try:
        mtime = int(path.stat().st_mtime_ns)
    except OSError:
        mtime = 0
    return _cached_lib_symbol_sexp(str(path.resolve()), inst_name, mtime)


def parse_kicad_symbol_id(symbol_library_id: str) -> tuple[str, str] | None:
    """Split ``Library:SymbolName`` (same convention as ``kicad_footprint``)."""
    s = str(symbol_library_id or "").strip()
    if ":" not in s:
        return None
    lib, name = s.split(":", 1)
    lib, name = lib.strip(), name.strip()
    if not lib or not name:
        return None
    return lib, name


def parse_pinout_from_symbol_tree(symbol_tree: str) -> list[dict]:
    """Extract pin records ``[{num, name, type}, ...]`` from a KiCad symbol S-expression subtree."""
    out: list[dict] = []
    seen: set[str] = set()
    for blk in _iter_pin_blocks(symbol_tree):
        nm = _NUMBER_RE.search(blk)
        if not nm:
            continue
        pin_num = nm.group(1).strip()
        if pin_num in seen:
            continue
        seen.add(pin_num)
        name_m = _NAME_RE.search(blk)
        pin_name = name_m.group(1) if name_m else ""
        etype = _pin_electrical_type(blk)
        out.append({"num": pin_num, "name": pin_name, "type": etype})
    return out


def iter_library_symbol_names(lib_file: Path) -> list[str]:
    """Top-level symbol names in a ``.kicad_sym`` (excludes ``_N_M`` unit children)."""
    try:
        text = Path(lib_file).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    names: list[str] = []
    seen: set[str] = set()
    for m in re.finditer(r'\(symbol\s+"([^"]+)"', text):
        name = m.group(1).strip()
        if not name or name in seen:
            continue
        if re.search(r"_\d+_\d+$", name):
            continue
        seen.add(name)
        names.append(name)
    return names


def normalize_symbol_pin_name(name: str) -> str:
    """Strip KiCad/SKiDL decoration so SCS matches ~{SCS} and ALERT/RDY matches ALERT."""
    s = str(name or "").strip().upper()
    s = s.replace("~", "").replace("{", "").replace("}", "")
    if "/" in s:
        s = s.split("/", 1)[0]
    return re.sub(r"[^A-Z0-9]+", "", s)


def rewrite_symbol_pin_electrical_types(tree: str, by_num: dict[str, str]) -> str:
    """Replace ``(pin <type>`` on numbered pins. Geometry and names stay library-owned."""
    if not tree or not by_num:
        return tree
    out = tree
    for blk in _iter_pin_blocks(tree):
        nm = _NUMBER_RE.search(blk)
        if not nm:
            continue
        new_t = str(by_num.get(nm.group(1).strip()) or "").strip()
        if not new_t:
            continue
        new_blk = re.sub(r"^\(pin\s+\S+", f"(pin {new_t}", blk, count=1)
        if new_blk != blk:
            out = out.replace(blk, new_blk, 1)
    return out


def map_graph_pin_to_library_number(
    pin,
    pmap: dict,
    pinout_by_num: dict | None = None,
) -> str | None:
    """Library pin number for a graph pin: same number if names agree, else unique name match.

    Offline / SKiDL tables often number VDD as 24 while KiCad's body uses 24 for an LED.
    Connecting by name keeps ERC on the library pin that actually is VDD/SDA/SCS.
    """
    gnum = str(getattr(pin, "num", None) or getattr(pin, "number", "") or "").strip()
    gname = normalize_symbol_pin_name(str(getattr(pin, "name", "") or ""))
    pinout_by_num = pinout_by_num or {}

    def _lib_name(num: str) -> str:
        rec = pinout_by_num.get(str(num)) or {}
        return normalize_symbol_pin_name(str(rec.get("name") or ""))

    mapped = None
    if gnum and gnum in pmap:
        ln = _lib_name(gnum)
        if not gname or not ln or gname == ln:
            mapped = gnum
    if mapped is None and gname:
        hits = [n for n in pmap if _lib_name(n) == gname]
        if len(hits) == 1:
            mapped = hits[0]
        elif gnum in hits:
            mapped = gnum
        elif hits:
            mapped = sorted(hits, key=lambda s: (len(s), s))[0]
    if mapped is None and gnum and gnum in pmap:
        mapped = gnum
    if mapped is None:
        mapped = gnum or None
    # Hidden library NC pads are not VIO/VCC: attaching a power symbol there is ERC pin_not_connected.
    if mapped and _library_pin_is_nc(pinout_by_num, mapped) and gname not in ("NC", "NOCONNECT"):
        return None
    return mapped


def _library_pin_is_nc(pinout_by_num: dict, num: str | None) -> bool:
    rec = pinout_by_num.get(str(num or "")) or {}
    return str(rec.get("type") or "").lower() in ("no_connect", "free")


def pinout_from_kicad_symbol_id(kicad_symbol: str) -> list[dict] | None:
    """Load ``Library:Name`` from search paths and return pinout records, or None if unavailable."""
    parsed = parse_kicad_symbol_id(kicad_symbol)
    if not parsed:
        return None
    lib, sym = parsed
    path = find_symbol_library_file(lib)
    if path is None:
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        logger.debug("Could not read symbol library %s: %s", path, e)
        return None
    tree = resolve_symbol_tree_for_pins(text, sym)
    if tree is None:
        logger.debug("Symbol %r not found (or no pins after extends) in %s", sym, path)
        return None
    po = parse_pinout_from_symbol_tree(tree)
    return po if po else None


def parse_pin_positions_from_symbol_tree(symbol_tree: str) -> dict[str, tuple[float, float, float, float]]:
    """Map pin number string -> (x, y, rot, len) in symbol-local mm."""
    pos: dict[str, tuple[float, float, float, float]] = {}
    for blk in _iter_pin_blocks(symbol_tree):
        nm = _NUMBER_RE.search(blk)
        if not nm:
            continue
        pin_num = nm.group(1).strip()
        am = _AT_RE.search(blk)
        if not am:
            continue
        x, y, rot = float(am.group(1)), float(am.group(2)), float(am.group(3))
        
        lm = _LENGTH_RE.search(blk)
        plen = float(lm.group(1)) if lm else 2.54 # KiCad default
        
        # Later pin blocks for same number should not overwrite; keep first.
        if pin_num not in pos:
            pos[pin_num] = (x, y, rot, plen)
    return pos


@lru_cache(maxsize=64)
def _cached_pin_map(path: str, symbol_name: str, mtime_ns: int) -> dict[str, tuple[float, float, float, float]] | None:
    """Load and parse symbol; cache key includes mtime for dev edits."""
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        logger.debug("Could not read %s: %s", p, e)
        return None
    tree = resolve_symbol_tree_for_pins(text, symbol_name)
    if tree is None:
        logger.debug("Symbol %r not found (or no pins after extends) in %s", symbol_name, p)
        return None
    return parse_pin_positions_from_symbol_tree(tree)


def clear_symbol_pin_cache() -> None:
    """Drop memoized symbol parses (for tests that rewrite fixture libraries)."""
    _cached_pin_map.cache_clear()
    _cached_lib_symbol_sexp.cache_clear()


def load_symbol_pin_positions(lib_file: Path, symbol_name: str) -> dict[str, tuple[float, float, float, float]] | None:
    """Return pin map for *symbol_name* in *lib_file*, or None if missing."""
    try:
        st = lib_file.stat()
        mtime = int(st.st_mtime_ns)
    except OSError:
        mtime = 0
    return _cached_pin_map(str(lib_file.resolve()), symbol_name, mtime)


def part_library_name(part) -> str:
    """KiCad library nick (e.g. ``Device``) for *part*; SKiDL stores a ``SchLib`` on ``part.lib``."""
    # Native OpenHaC parts may have a custom symbol override from the database (e.g. jlc2kicad_generated:C1234)
    if type(part).__name__ == "Part" and type(part).__module__ == "openhac.core.part":
        sym = getattr(part, "kicad_symbol", "") or ""
        if ":" in str(sym):
            return str(sym).split(":")[0]
        return "OpenHaC"
        
    try:
        tool = getattr(part, "tool", None)
        if tool == "OpenHaC":
            return "OpenHaC"
    except Exception:
        pass
    L = getattr(part, "lib", None)
    if L is None:
        return ""
    fn = getattr(L, "filename", None)
    if fn is not None:
        return str(fn).strip()
    if isinstance(L, str):
        return L.strip()
    return ""


class EmptySymbolPinResolver:
    """Always fall back to index-based stub offsets (tests / deterministic baselines)."""

    __slots__ = ()

    def offset_for_pin(self, part, pin, symbol_name: str | None = None) -> tuple[float, float, float] | None:
        idx = 0
        try:
            if hasattr(part, "get_pins"):
                pins = part.get_pins()
            elif isinstance(getattr(part, "pins", None), dict):
                pins = list(part.pins.values())
            else:
                pins = list(getattr(part, "pins", []) or [])
            for i, p in enumerate(pins):
                if p is pin:
                    idx = i
                    break
        except Exception:
            pass
        # Legacy 50 mil vertical stubs (±2.54 mm) for deterministic test baselines.
        dy = 2.54 if (idx % 2) else -2.54
        return (0.0, dy, 0.0)


class SymbolPinResolver:
    """Resolve SKiDL part + pin to schematic-local offset (mm) from symbol library files."""

    __slots__ = ("_cache", "_explicit_libs")

    def __init__(self) -> None:
        self._cache: dict[tuple[str, str], Optional[dict[str, tuple[float, float, float, float]]]] = {}
        self._explicit_libs: dict[str, Path] = {}

    def add_explicit_library(self, lib_name: str, path: str | Path) -> None:
        self._explicit_libs[str(lib_name).strip()] = Path(path)

    def offset_for_pin(self, part, pin, symbol_name: str | None = None) -> tuple[float, float, float] | None:
        """Return (dx, dy) relative to the symbol instance origin, or None to use stub layout."""
        lib = part_library_name(part)
        if not lib and "OpenHaC" in self._explicit_libs:
            lib = "OpenHaC"
        if symbol_name and ":" in str(symbol_name):
            parsed = parse_kicad_symbol_id(str(symbol_name))
            if parsed:
                lib, name = parsed
            else:
                name = str(symbol_name).split(":", 1)[-1]
        elif symbol_name:
            name = symbol_name
        else:
            name = (getattr(part, "name", None) or "").strip()
            if not name or name == "?":
                name = (getattr(part, "value", None) or "").strip()
            if not name or name == "?":
                name = (getattr(part, "ref", None) or getattr(part, "refdes", None) or "").strip()
            if not name or name == "?":
                name = "PART"
            
        if not lib or not name:
            logger.debug(f"Resolver skip: lib='{lib}' name='{name}' for part {part}")
            return None
        key = (lib, name)
        if key not in self._cache:
            if lib in self._explicit_libs:
                path = self._explicit_libs[lib]
            else:
                path = find_symbol_library_file(lib)
            if path is None:
                logger.debug(f"Resolver miss: No library found for {lib}")
                self._cache[key] = None
            else:
                logger.debug(f"Resolver loading: {path} for {name}")
                self._cache[key] = load_symbol_pin_positions(path, name)
            nkey = (lib, name, "names")
            po: list[dict] = []
            if path is not None:
                try:
                    text = Path(path).read_text(encoding="utf-8", errors="replace")
                    tree = resolve_symbol_tree_for_pins(text, name)
                    if tree:
                        po = parse_pinout_from_symbol_tree(tree)
                except OSError:
                    po = []
            self._cache[nkey] = {str(r.get("num") or ""): r for r in po if r.get("num") not in (None, "")}
        pmap = self._cache[key]
        if not pmap:
            logger.debug(f"Resolver fail: No pin map for {key}")
            return None
        nkey = (lib, name, "names")
        by_num = self._cache.get(nkey) or {}
        pnum = map_graph_pin_to_library_number(pin, pmap, by_num)
        pdata = pmap.get(pnum) if pnum else None
        if pdata is None:
            return None
            
        x, y, rot, plen = pdata
        
        # KiCad's (at x y rotation) in a pin definition IS the electrical connection point (the tip).
        # We should return these raw coordinates.  The previous attempt to translate from base to tip
        # was based on a misunderstanding of the KiCad format spec.
        # Returning raw x, y ensures that wire endpoints land EXACTLY where KiCad expects them.
        return x, y, rot
