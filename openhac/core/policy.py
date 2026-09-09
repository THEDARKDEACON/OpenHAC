"""Compile-goal / fabrication policy helpers (single source of truth).

Leaf gates (network, invented pins, Module fail-closed, empty-native circuit)
must use :func:`is_fabrication_mode` instead of reading ``OPENHAC_COMPILE_GOAL``
alone. Board-API users set ``Board(compile_goal="fabrication")`` without env;
CLI sets the env before import. Both must engage the same policy.
"""

from __future__ import annotations

import os
from contextvars import ContextVar, Token
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openhac.core.board import Board

FABRICATION_GOAL_ALIASES = frozenset(
    {
        "fabrication",
        "fab",
        "push_button_fab",
        "push-button-fab",
        "pushbuttonfab",
    }
)
HANDOFF_GOAL_ALIASES = frozenset(
    {
        "handoff",
        "hand-off",
        "hand_off",
        "kicad",
        "review",
    }
)

# Last Board() construction stamps this when env is unset, so construction-time
# gates (Component init, network_allowed) see Board(compile_goal=...).
_design_compile_goal: ContextVar[str | None] = ContextVar(
    "openhac_design_compile_goal", default=None
)


def is_fabrication_goal(goal: str | None) -> bool:
    """True when *goal* normalizes to fabrication."""
    s = str(goal or "").strip().lower()
    return s in FABRICATION_GOAL_ALIASES


def normalize_compile_goal(v: str | None) -> str:
    """Normalize to ``handoff`` or ``fabrication`` (raises on unknown non-empty)."""
    s = str(v or "").strip().lower()
    if not s:
        return "handoff"
    if s in HANDOFF_GOAL_ALIASES:
        return "handoff"
    if s in FABRICATION_GOAL_ALIASES:
        return "fabrication"
    raise ValueError(f"compile_goal must be 'handoff' or 'fabrication', got {v!r}")


def set_design_compile_goal(goal: str | None) -> Token:
    """Stamp the active design compile goal (called from :class:`Board` init)."""
    try:
        normalized = normalize_compile_goal(goal)
    except ValueError:
        normalized = "handoff"
    return _design_compile_goal.set(normalized)


def get_design_compile_goal() -> str | None:
    return _design_compile_goal.get()


def resolve_compile_goal(*, board: Board | None = None) -> str:
    """Effective compile goal: env → explicit board → compile context → design stamp."""
    env = (os.environ.get("OPENHAC_COMPILE_GOAL") or "").strip()
    if env:
        try:
            return normalize_compile_goal(env)
        except ValueError:
            pass
    if board is not None:
        raw = getattr(board, "compile_goal", None)
        try:
            return normalize_compile_goal(raw)
        except ValueError:
            return "handoff"
    try:
        from openhac.core.compile_context import get_compile_context

        ctx = get_compile_context()
        if ctx is not None and getattr(ctx, "board", None) is not None:
            raw = getattr(ctx.board, "compile_goal", None)
            try:
                return normalize_compile_goal(raw)
            except ValueError:
                return "handoff"
    except Exception:
        pass
    dg = _design_compile_goal.get()
    if dg:
        return dg
    return "handoff"


def is_fabrication_mode(*, board: Board | None = None) -> bool:
    """True when fabrication / production fail-closed policy applies."""
    return resolve_compile_goal(board=board) == "fabrication"


def sync_compile_goal_env(goal: str) -> tuple[bool, str | None]:
    """Set ``OPENHAC_COMPILE_GOAL`` when unset. Returns ``(owned, previous)``."""
    prev = os.environ.get("OPENHAC_COMPILE_GOAL")
    if (prev or "").strip():
        return False, prev
    os.environ["OPENHAC_COMPILE_GOAL"] = normalize_compile_goal(goal)
    return True, prev


def restore_compile_goal_env(owned: bool, previous: str | None) -> None:
    """Undo :func:`sync_compile_goal_env` when *owned*."""
    if not owned:
        return
    if previous is None:
        os.environ.pop("OPENHAC_COMPILE_GOAL", None)
    else:
        os.environ["OPENHAC_COMPILE_GOAL"] = previous
