"""Per-compile context (contextvars) so policy does not rely on mutating :class:`Component` class state.

``Board.compile`` / ``Board.simulate`` set an :class:`OpenHaCCompileContext` for the duration of the
call. :class:`Component` resolves strict JIT / risky lookups from (1) this context, (2) the host
:class:`Board` stamped on modules via :meth:`Board.add_module`, or (3) legacy class attributes /
environment (CLI and scripts without a host board).
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openhac.core.board import Board

_ctx: ContextVar["OpenHaCCompileContext | None"] = ContextVar("openhac_compile_ctx", default=None)


@dataclass
class OpenHaCCompileContext:
    board: Board
    allow_risky_part_lookups: bool = False
    #: Extra catalog overlay files or directories (JSON). Merged after bundled overlays; see ``catalog_overlay`` module.
    catalog_overlay_paths: tuple[str | Path, ...] = field(default_factory=tuple)


def get_compile_context() -> OpenHaCCompileContext | None:
    return _ctx.get()


def compile_context_set(ctx: OpenHaCCompileContext):
    """Return the token for :func:`compile_context_reset`."""
    return _ctx.set(ctx)


def compile_context_reset(token) -> None:
    _ctx.reset(token)
