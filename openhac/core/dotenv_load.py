"""Load repo-root environment files for OpenHaC CLI and tools.

Reads ``.env`` then ``.env.local`` from the repository root (next to ``openhac/``).

- ``.env``: ``setdefault`` for most keys (shell exports win), **except** placement /
  density tuning keys which always override so trial-and-error in ``.env`` is not
  blocked by a stale ``export`` from an earlier session.
- ``.env.local``: always overrides (machine-specific).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger("openhac.dotenv")

# Knobs users tune in .env for packing density — must win over leftover shell exports.
_DOTENV_FORCE_OVERRIDE_PREFIXES = (
    "OPENHAC_MODULE_",
    "OPENHAC_PLACEMENT_",
    "OPENHAC_AUTO_BOARD_",
    "OPENHAC_DEOVERLAP_",
    "OPENHAC_FREEROUTING_",
    "OPENHAC_PRODUCTION_SCHEMATIC",
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _force_override_key(key: str) -> bool:
    return any(key.startswith(p) or key == p for p in _DOTENV_FORCE_OVERRIDE_PREFIXES)


def _apply_env_file(path: Path, *, override: bool) -> int:
    if not path.is_file():
        return 0
    n = 0
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        logger.warning("Could not read %s: %s", path, e)
        return 0
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if not key:
            continue
        if override or _force_override_key(key):
            os.environ[key] = val
        else:
            os.environ.setdefault(key, val)
        n += 1
    return n


def load_repo_dotenv(*, quiet: bool = True) -> None:
    """Load ``REPO/.env`` then ``REPO/.env.local`` if present."""
    root = _repo_root()
    n = _apply_env_file(root / ".env", override=False)
    n += _apply_env_file(root / ".env.local", override=True)
    if not quiet and n:
        logger.info("Loaded %s environment entries from .env / .env.local under %s", n, root)


def apply_kicad_env_aliases() -> None:
    """Mirror KiCad environment variables across all versions (6, 7, 8, 9, 10).

    Auto-detects standard system installs across platforms when not explicitly set in env.
    Call this immediately after :func:`load_repo_dotenv`.
    """
    try:
        from openhac.core.kicad_version import apply_universal_kicad_env
        apply_universal_kicad_env()
    except Exception as e:
        logger.debug("apply_universal_kicad_env failed: %s", e)

    sym = (os.environ.get("KICAD_SYMBOL_DIR") or os.environ.get("KICAD9_SYMBOL_DIR") or "").strip()
    if not sym and Path("/usr/share/kicad/symbols").is_dir():
        sym = "/usr/share/kicad/symbols"
        os.environ["KICAD9_SYMBOL_DIR"] = sym

    if sym:
        for key in (
            "KICAD_SYMBOL_DIR",
            "KICAD10_SYMBOL_DIR",
            "KICAD9_SYMBOL_DIR",
            "KICAD8_SYMBOL_DIR",
            "KICAD7_SYMBOL_DIR",
            "KICAD6_SYMBOL_DIR",
        ):
            os.environ.setdefault(key, sym)

    fp = (os.environ.get("KICAD_FOOTPRINT_DIR") or os.environ.get("KICAD9_FOOTPRINT_DIR") or "").strip()
    if not fp and Path("/usr/share/kicad/footprints").is_dir():
        fp = "/usr/share/kicad/footprints"
        os.environ["KICAD9_FOOTPRINT_DIR"] = fp

    if fp:
        for key in (
            "KICAD_FOOTPRINT_DIR",
            "KICAD10_FOOTPRINT_DIR",
            "KICAD9_FOOTPRINT_DIR",
            "KICAD8_FOOTPRINT_DIR",
            "KICAD7_FOOTPRINT_DIR",
            "KICAD6_FOOTPRINT_DIR",
        ):
            os.environ.setdefault(key, fp)

