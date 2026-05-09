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


def parse_pin_positions_from_symbol_tree(symbol_tree: str) -> dict[str, tuple[float, float]]:
    """Map pin number string → (x, y) in symbol-local mm (first ``(at ...)`` in each pin block)."""
    pos: dict[str, tuple[float, float]] = {}
    for blk in _iter_pin_blocks(symbol_tree):
        nm = _NUMBER_RE.search(blk)
        if not nm:
            continue
        pin_num = nm.group(1).strip()
        am = _AT_RE.search(blk)
        if not am:
            continue
        x, y = float(am.group(1)), float(am.group(2))
        # Later pin blocks for same number should not overwrite; keep first.
        if pin_num not in pos:
            pos[pin_num] = (x, y)
    return pos


@lru_cache(maxsize=64)
def _cached_pin_map(path: str, symbol_name: str, mtime_ns: int) -> dict[str, tuple[float, float]] | None:
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


def load_symbol_pin_positions(lib_file: Path, symbol_name: str) -> dict[str, tuple[float, float]] | None:
    """Return pin map for *symbol_name* in *lib_file*, or None if missing."""
    try:
        st = lib_file.stat()
        mtime = int(st.st_mtime_ns)
    except OSError:
        mtime = 0
    return _cached_pin_map(str(lib_file.resolve()), symbol_name, mtime)


def part_library_name(part) -> str:
    """KiCad library nick (e.g. ``Device``) for *part*; SKiDL stores a ``SchLib`` on ``part.lib``."""
    # Native OpenHaC parts don't have a 'tool' or 'lib' attribute, they are dynamically generated.
    if type(part).__name__ == "Part" and type(part).__module__ == "openhac.core.part":
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

    def offset_for_pin(self, part, pin) -> tuple[float, float] | None:
        return None


class SymbolPinResolver:
    """Resolve SKiDL part + pin to schematic-local offset (mm) from symbol library files."""

    __slots__ = ("_cache", "_explicit_libs")

    def __init__(self) -> None:
        self._cache: dict[tuple[str, str], Optional[dict[str, tuple[float, float]]]] = {}
        self._explicit_libs: dict[str, Path] = {}

    def add_explicit_library(self, lib_name: str, path: str | Path) -> None:
        self._explicit_libs[str(lib_name).strip()] = Path(path)

    def offset_for_pin(self, part, pin) -> tuple[float, float] | None:
        """Return (dx, dy) relative to the symbol instance origin, or None to use stub layout."""
        lib = part_library_name(part)
        name = (getattr(part, "name", None) or "").strip()
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
        pmap = self._cache[key]
        if not pmap:
            logger.debug(f"Resolver fail: No pin map for {key}")
            return None
        pnum = str(getattr(pin, "num", "") or "").strip()
        if pnum not in pmap:
            logger.debug(f"Resolver fail: Pin {pnum} not in pmap {list(pmap.keys())} for {name}")
        return pmap.get(pnum)
