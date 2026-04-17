"""Load repo-root environment files for OpenHaC CLI and tools.

Reads ``.env`` then ``.env.local`` from the repository root (next to ``openhac/``).
Uses ``os.environ.setdefault`` for ``.env`` and overwrites from ``.env.local`` so local
overrides work without committing machine-specific paths.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger("openhac.dotenv")


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


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
        if override:
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
