"""Package version and HTTP User-Agent string (single source of truth)."""

from __future__ import annotations


def get_version() -> str:
    try:
        from importlib.metadata import version

        return version("openhac")
    except Exception:
        return "0.2.0"


def user_agent() -> str:
    return f"OpenHaC/{get_version()}"
