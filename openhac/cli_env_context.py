"""Context manager for temporary environment variable scoping.

Replaces the ~80 lines of manual save/restore boilerplate in each CLI command.

Usage::

    with env_scope(
        OPENHAC_SKIP_LAYOUT="1",
        OPENHAC_COMPILE_GOAL="handoff",
        OPENHAC_DETERMINISTIC=None,   # unset for this scope
    ):
        # ... compile logic; env is restored on exit (even on exception)
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any


@contextmanager
def env_scope(**overrides: Any):
    """Temporarily set / unset environment variables; restore originals on exit.

    Pass ``key=value`` to set, ``key=None`` to unset for the duration.
    """
    saved: dict[str, str | None] = {}
    for key, value in overrides.items():
        saved[key] = os.environ.get(key)
        if value is not None:
            os.environ[key] = str(value)
        else:
            os.environ.pop(key, None)
    try:
        yield
    finally:
        for key, orig in saved.items():
            if orig is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = orig
