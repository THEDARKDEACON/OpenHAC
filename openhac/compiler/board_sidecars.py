"""Local catalog next to a board script — loaded before ``Component()`` runs.

``openhac compile board.py`` should not require ``--pre-seed-file`` / ``openhac sync``
when the board ships its parts beside the script.

Discovery (all optional, local files only — safe under ``--production``):

* ``{stem}.openhac-seed.json`` — packed ``seed_from_file`` rows
* ``{dir}/openhac.seed.json`` — same, project-wide
* ``{dir}/catalog_overlays/`` — JSON overlays (``OPENHAC_CATALOG_OVERLAY``)
* ``{stem}.openhac.json`` — manifest:

  .. code-block:: json

     {"schema": "openhac.board-sidecars.v1",
      "seed": ["extra.seed.json"],
      "catalog_overlay": ["overlays/"],
      "vendor_cassettes": "../tests/fixtures/vendor"}

Disable with ``OPENHAC_NO_BOARD_SIDECARS=1`` or ``--no-board-sidecars``.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("openhac.board_sidecars")

SCHEMA = "openhac.board-sidecars.v1"
_SKIP_ENV = "OPENHAC_NO_BOARD_SIDECARS"


@dataclass(frozen=True)
class BoardSidecars:
    seed_files: tuple[Path, ...] = ()
    overlay_paths: tuple[Path, ...] = ()
    cassette_dirs: tuple[Path, ...] = ()

    def is_empty(self) -> bool:
        return not (self.seed_files or self.overlay_paths or self.cassette_dirs)


def sidecars_disabled() -> bool:
    return os.environ.get(_SKIP_ENV, "").strip().lower() in ("1", "true", "yes", "on")


def _as_path_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple)):
        return [str(x) for x in value if str(x).strip()]
    return []


def _resolve(script_dir: Path, raw: str) -> Path:
    p = Path(raw)
    if not p.is_absolute():
        p = (script_dir / p).resolve()
    return p


def discover_board_sidecars(script_path: str | Path) -> BoardSidecars:
    script = Path(script_path).expanduser().resolve()
    script_dir = script.parent
    stem_base = script.with_suffix("")

    seeds: list[Path] = []
    overlays: list[Path] = []
    cassettes: list[Path] = []

    auto_seed = Path(str(stem_base) + ".openhac-seed.json")
    if auto_seed.is_file():
        seeds.append(auto_seed)
    project_seed = script_dir / "openhac.seed.json"
    if project_seed.is_file() and project_seed not in seeds:
        seeds.append(project_seed)

    auto_ov = script_dir / "catalog_overlays"
    if auto_ov.is_dir():
        overlays.append(auto_ov)

    manifest = Path(str(stem_base) + ".openhac.json")
    if manifest.is_file():
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("Ignoring unreadable board sidecar manifest %s: %s", manifest, e)
            data = {}
        if not isinstance(data, dict):
            data = {}
        for raw in _as_path_list(data.get("seed") or data.get("seed_files")):
            p = _resolve(script_dir, raw)
            if p.is_file() and p not in seeds:
                seeds.append(p)
        for raw in _as_path_list(data.get("catalog_overlay") or data.get("catalog_overlays")):
            p = _resolve(script_dir, raw)
            if (p.is_file() or p.is_dir()) and p not in overlays:
                overlays.append(p)
        for raw in _as_path_list(data.get("vendor_cassettes")):
            p = _resolve(script_dir, raw)
            if p.is_dir() and p not in cassettes:
                cassettes.append(p)

    return BoardSidecars(
        seed_files=tuple(seeds),
        overlay_paths=tuple(overlays),
        cassette_dirs=tuple(cassettes),
    )


def restore_catalog_overlay_env(previous: str | None) -> None:
    if previous is None:
        os.environ.pop("OPENHAC_CATALOG_OVERLAY", None)
    else:
        os.environ["OPENHAC_CATALOG_OVERLAY"] = previous
    try:
        from openhac.database.catalog_overlay import reset_catalog_overlay_caches

        reset_catalog_overlay_caches()
    except Exception:
        pass


def _prepend_overlay_env(paths: tuple[Path, ...]) -> None:
    if not paths:
        return
    cur = [p for p in (os.environ.get("OPENHAC_CATALOG_OVERLAY") or "").split(os.pathsep) if p]
    extra = [str(p) for p in paths]
    merged: list[str] = []
    for p in extra + cur:
        if p not in merged:
            merged.append(p)
    os.environ["OPENHAC_CATALOG_OVERLAY"] = os.pathsep.join(merged)
    try:
        from openhac.database.catalog_overlay import reset_catalog_overlay_caches

        reset_catalog_overlay_caches()
    except Exception:
        pass


def apply_board_sidecars(script_path: str | Path, *, enabled: bool = True) -> BoardSidecars:
    """Seed SQLite and register overlays before the board script is imported."""
    if not enabled or sidecars_disabled():
        return BoardSidecars()
    found = discover_board_sidecars(script_path)
    if found.is_empty():
        return found

    from openhac.database.db_manager import DatabaseManager
    from openhac.database.sync_jlc import seed_from_file
    from openhac.database.vendor_cassettes import ingest_cassette_directory

    logger.info(
        "Board sidecar: seeds=%s cassettes=%s overlays=%s",
        len(found.seed_files),
        len(found.cassette_dirs),
        len(found.overlay_paths),
    )
    db = DatabaseManager()
    for seed in found.seed_files:
        logger.info("Board sidecar: seeding catalog from %s", seed)
        seed_from_file(str(seed), verbose=True)
    for cas in found.cassette_dirs:
        logger.info("Board sidecar: ingesting vendor cassettes from %s", cas)
        ingest_cassette_directory(db, cas)
    _prepend_overlay_env(found.overlay_paths)
    return found
