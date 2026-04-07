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
_NUMBER_RE = re.compile(r'\(number\s+"([^"]*)"\)')


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
    tree = _extract_symbol_tree(text, symbol_name)
    if tree is None:
        logger.debug("Symbol %r not found in %s", symbol_name, p)
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
    # For SKiDL-native parts (tool=SKIDL) we can emit a project-local library and use a stable nick.
    try:
        tool = getattr(part, "tool", None)
        import skidl  # local import to avoid hard dependency during docs builds

        if tool == getattr(skidl, "SKIDL", None):
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

    __slots__ = ("_cache",)

    def __init__(self) -> None:
        self._cache: dict[tuple[str, str], Optional[dict[str, tuple[float, float]]]] = {}

    def offset_for_pin(self, part, pin) -> tuple[float, float] | None:
        """Return (dx, dy) relative to the symbol instance origin, or None to use stub layout."""
        lib = part_library_name(part)
        name = (getattr(part, "name", None) or "").strip()
        if not lib or not name:
            return None
        key = (lib, name)
        if key not in self._cache:
            path = find_symbol_library_file(lib)
            if path is None:
                self._cache[key] = None
            else:
                self._cache[key] = load_symbol_pin_positions(path, name)
        pmap = self._cache[key]
        if not pmap:
            return None
        pnum = str(getattr(pin, "num", "") or "").strip()
        return pmap.get(pnum)
