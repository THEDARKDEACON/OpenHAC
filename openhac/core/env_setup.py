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
    """Locate the KiCad 8 symbol directory.

    Checks, in order:
      1. The ``KICAD8_SYMBOL_DIR`` environment variable (user override).
      2. The standard install paths for the detected platform.

    Returns:
        The validated absolute path to the symbol directory.

    Raises:
        KiCadNotFoundError: If no valid symbol directory is found.
    """
    # 1. Honour explicit environment variable
    env_path = os.environ.get("KICAD8_SYMBOL_DIR")
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
        f"KiCad 8 symbol library not found.\n"
        f"Searched: {tried}\n"
        f"Install KiCad 8 in the default directory, or set the "
        f"KICAD8_SYMBOL_DIR environment variable to a valid symbol path."
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

    # Default footprint root for pcbnew .pretty resolution (no-op if user already set env)
    if not os.environ.get("KICAD9_FOOTPRINT_DIR") and not os.environ.get("KICAD8_FOOTPRINT_DIR"):
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
