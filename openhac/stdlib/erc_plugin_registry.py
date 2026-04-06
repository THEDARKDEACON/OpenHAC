"""Named ERC plugin registry (ARCH / SCH-005).

Built-ins mirror :data:`openhac.stdlib.erc_rule_packs.ERC_RULE_PACK_EXPORTS`: each
``apply_*_pack`` function is registered under the name with the ``apply_`` prefix
removed (e.g. ``apply_i2c_pullup_pack`` → ``i2c_pullup_pack``).

Projects can :func:`register_erc_plugin` for custom callables with the same
``(board, *args, **kwargs)`` shape as the pack helpers.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from openhac.core.base import OpenHaCError

_BUILTINS: dict[str, Callable[..., Any]] = {}
_USER: dict[str, Callable[..., Any]] = {}
_builtins_loaded = False


def _pack_registry_key(export_name: str) -> str:
    if not export_name.startswith("apply_"):
        return export_name
    return export_name[len("apply_") :]


def _load_builtins() -> None:
    global _builtins_loaded
    if _builtins_loaded:
        return
    from openhac.stdlib import erc_rule_packs as erp

    for export_name in erp.ERC_RULE_PACK_EXPORTS:
        fn = getattr(erp, export_name)
        key = _pack_registry_key(export_name)
        _BUILTINS[key] = fn
    _builtins_loaded = True


def register_erc_plugin(
    name: str,
    fn: Callable[..., Any],
    *,
    overwrite: bool = False,
) -> None:
    """Register a callable ``fn(board, *args, **kwargs)`` under *name*.

    Cannot replace a built-in key unless *overwrite* is True (use a distinct
    *name* for project plugins).
    """
    _load_builtins()
    key = str(name).strip()
    if not key:
        raise OpenHaCError("ERC plugin name must be non-empty")
    if key in _BUILTINS and not overwrite:
        raise OpenHaCError(
            f"ERC plugin {key!r} is reserved (built-in pack); choose another name or pass overwrite=True to shadow"
        )
    if key in _USER and not overwrite:
        raise OpenHaCError(f"ERC plugin {key!r} is already registered")
    _USER[key] = fn


def unregister_erc_plugin(name: str) -> None:
    """Remove a **user** registration. Built-ins cannot be removed."""
    _load_builtins()
    key = str(name).strip()
    if key in _BUILTINS:
        raise OpenHaCError(f"Cannot unregister built-in ERC plugin {key!r}")
    _USER.pop(key, None)


def clear_user_erc_plugins() -> None:
    """Clear all user registrations (intended for tests)."""
    _USER.clear()


def list_erc_plugin_names() -> tuple[str, ...]:
    """All known plugin names (built-ins + user), sorted."""
    _load_builtins()
    return tuple(sorted({*_BUILTINS.keys(), *_USER.keys()}))


def apply_erc_plugin(board, name: str, *args: Any, **kwargs: Any) -> None:
    """Invoke the registered plugin *name* with ``(board, *args, **kwargs)``."""
    _load_builtins()
    key = str(name).strip()
    fn = _USER.get(key) or _BUILTINS.get(key)
    if fn is None:
        known = ", ".join(list_erc_plugin_names()) or "(none)"
        raise OpenHaCError(f"Unknown ERC plugin {key!r}; known: {known}")
    fn(board, *args, **kwargs)
