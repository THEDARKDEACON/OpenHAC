"""
OpenHaC Environment Bootstrapper.

Automatically detects the host OS, locates the default KiCad 8 symbol
library installation, and injects the path into SKiDL's search registry.

This module is imported automatically via ``openhac.core.__init__`` so
that end-users never need to manually set KICAD8_SYMBOL_DIR or any other
environment variable.  The bootstrapper is idempotent — calling it
multiple times is safe.
"""

import os
import sys
import warnings

# Standard KiCad 8 symbol directories per platform.
_KICAD_SYMBOL_PATHS = {
    "linux": [
        "/usr/share/kicad/symbols",
        os.path.expanduser("~/.local/share/kicad/8.0/symbols"),
    ],
    "win32": [
        r"C:\Program Files\KiCad\8.0\share\kicad\symbols",
        r"C:\Program Files (x86)\KiCad\8.0\share\kicad\symbols",
    ],
    "darwin": [
        "/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols",
        "/Applications/KiCad.app/Contents/SharedSupport/symbols",
    ],
}

_bootstrapped = False


class KiCadNotFoundError(EnvironmentError):
    """Raised when no KiCad 8 symbol library can be located."""


def _resolve_symbol_path() -> str:
    """Locate a KiCad symbol directory (prefer user env, then common installs).

    Checks, in order:
      1. One of the ``KICAD*_SYMBOL_DIR`` environment variables (user override).
      2. Standard install paths for the detected platform.

    Returns:
        The validated absolute path to the symbol directory.

    Raises:
        KiCadNotFoundError: If no valid symbol directory is found.
    """
    # 1. Honour explicit environment variable(s)
    for key in (
        "KICAD9_SYMBOL_DIR",
        "KICAD8_SYMBOL_DIR",
        "KICAD7_SYMBOL_DIR",
        "KICAD6_SYMBOL_DIR",
        "KICAD_SYMBOL_DIR",
    ):
        env_path = os.environ.get(key)
        if env_path and os.path.isdir(env_path):
            return env_path

    # 2. Platform-specific defaults
    platform = sys.platform
    candidates = _KICAD_SYMBOL_PATHS.get(platform, [])

    for path in candidates:
        if os.path.isdir(path):
            return path

    # 3. Nothing found — raise
    tried = ", ".join(candidates) if candidates else f"(no known paths for {platform})"
    raise KiCadNotFoundError(
        f"KiCad symbol library not found.\n"
        f"Searched: {tried}\n"
        f"Install KiCad, or set a KICAD*_SYMBOL_DIR environment variable to a valid symbol path."
    )


def bootstrap_environment() -> None:
    """Detect KiCad 8 and inject symbol paths into SKiDL.

    This function is idempotent.  It silently succeeds on repeat calls
    and only warns (never crashes) if SKiDL itself cannot be configured,
    so that test environments without KiCad can still import OpenHaC.
    """
    global _bootstrapped
    if _bootstrapped:
        return

    try:
        sym_path = _resolve_symbol_path()
    except KiCadNotFoundError as e:
        warnings.warn(
            f"OpenHaC Environment Bootstrapper: {e}\n"
            f"Compilation will fall back to synthetic parts.",
            UserWarning,
            stacklevel=2,
        )
        _bootstrapped = True
        return

    # If symbol path was auto-detected and no explicit KiCad symbol env hints are set,
    # seed a default so other components (doctor/reporting) see a consistent env state.
    if not any(
        (os.environ.get(k) or "").strip()
        for k in (
            "KICAD9_SYMBOL_DIR",
            "KICAD8_SYMBOL_DIR",
            "KICAD7_SYMBOL_DIR",
            "KICAD6_SYMBOL_DIR",
            "KICAD_SYMBOL_DIR",
        )
    ):
        os.environ.setdefault("KICAD8_SYMBOL_DIR", sym_path)
    os.environ.setdefault("OPENHAC_KICAD_SYMBOL_DIRS", sym_path)

    # Default footprint root for pcbnew .pretty resolution (no-op if user already set env)
    if not any((os.environ.get(k) or "").strip() for k in ("KICAD9_FOOTPRINT_DIR", "KICAD8_FOOTPRINT_DIR", "KICAD_FOOTPRINT_DIR")):
        for _fp in (
            "/usr/share/kicad/footprints",
            "/usr/local/share/kicad/footprints",
            os.path.expanduser("~/.local/share/kicad/8.0/footprints"),
        ):
            if os.path.isdir(_fp):
                os.environ.setdefault("KICAD8_FOOTPRINT_DIR", _fp)
                break

    try:
        from skidl import KICAD8, lib_search_paths, set_default_tool

        set_default_tool(KICAD8)
        if sym_path not in lib_search_paths[KICAD8]:
            lib_search_paths[KICAD8].append(sym_path)
    except ImportError:
        warnings.warn(
            "OpenHaC Environment Bootstrapper: SKiDL is not installed. "
            "Component creation will fail.",
            UserWarning,
            stacklevel=2,
        )
    except Exception as e:
        warnings.warn(
            f"OpenHaC Environment Bootstrapper: Failed to configure SKiDL: {e}",
            UserWarning,
            stacklevel=2,
        )

    _bootstrapped = True
