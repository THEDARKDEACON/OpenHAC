"""
Declarative catalog overlays: merge JSON-defined rows over SQLite `components` on read.

Use for any board — not tied to tests — when JLC/sync data is wrong or pinouts use symbolic
pad names that do not match KiCad footprints (PCB-002).

Resolution order for a given ``generic_name``:

1. SQLite row (best duplicate: longest ``pinout_json``).
2. Bundled ``package_catalog_overlays/*.json`` (unless ``OPENHAC_NO_BUNDLED_CATALOG_OVERLAYS=1``).
3. Paths from :envvar:`OPENHAC_CATALOG_OVERLAY` and :class:`OpenHaCCompileContext.catalog_overlay_paths`
   (CLI ``--catalog-overlay``); later files override earlier ones.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger("openhac.catalog_overlay")

# Keys written onto the component dict returned from get_component (SQLite column names).
_MERGE_KEYS = frozenset(
    {
        "kicad_footprint",
        "kicad_symbol",
        "category",
        "mpn",
        "supplier_sku",
        "description",
        "manufacturer",
        "pinout_json",
        "symbol_data",
        "datasheet_url",
        "product_url",
        "spice_include",
        "spice_subckt",
        "spice_model_path",
        "spice_pin_map_json",
        "model_3d_local",
        "model_3d_sha256",
        "model_3d_license",
        "model_3d_source",
        "catalog_tier",
        "pinout_source",
        "easyeda_sku",
    }
)

_PACKAGE_OVERLAY_DIR = Path(__file__).resolve().parent / "package_catalog_overlays"

_bundled_index_cache: dict[str, dict[str, Any]] | None = None
_user_index_cache: tuple[tuple[str, ...], dict[str, dict[str, Any]]] | None = None


def _parse_overlay_payload(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        return [x for x in raw if isinstance(x, dict)]
    if isinstance(raw, dict):
        return [raw]
    return []


def _normalize_entry(entry: dict[str, Any]) -> dict[str, Any] | None:
    gn = str(entry.get("generic_name") or "").strip()
    if not gn:
        return None
    out: dict[str, Any] = {"generic_name": gn}
    pinout = entry.get("pinout")
    if isinstance(pinout, list) and pinout:
        out["pinout_json"] = json.dumps(pinout)
    elif entry.get("pinout_json"):
        out["pinout_json"] = str(entry["pinout_json"])
    for k in _MERGE_KEYS:
        if k == "pinout_json":
            continue
        if k in entry and entry[k] is not None:
            out[k] = entry[k]
    if out.get("pinout_json") and "catalog_tier" not in out:
        out["catalog_tier"] = "verified"
        out.setdefault("pinout_source", "overlay")
    src = str(out.get("model_3d_source") or "").strip()
    if out.get("model_3d_local") and not src:
        out["model_3d_source"] = "overlay"
    local = out.get("model_3d_local")
    if local and not out.get("model_3d_sha256"):
        from pathlib import Path

        p = Path(str(local)).expanduser()
        if p.is_file():
            import hashlib

            h = hashlib.sha256()
            h.update(p.read_bytes())
            out["model_3d_sha256"] = h.hexdigest()
    return out


def reset_catalog_overlay_caches() -> None:
    """Clear memoized overlay indexes (for tests or hot-reload)."""
    global _bundled_index_cache, _user_index_cache
    _bundled_index_cache = None
    _user_index_cache = None


def _merge_index(base: dict[str, dict[str, Any]], entries: Iterable[dict[str, Any]]) -> None:
    for e in entries:
        ne = _normalize_entry(e)
        if not ne:
            continue
        gn = ne.pop("generic_name")
        if gn not in base:
            base[gn] = {}
        base[gn].update(ne)


def _collect_json_files(paths: Iterable[str | os.PathLike[str]]) -> list[Path]:
    files: list[Path] = []
    for p in paths:
        path = Path(p).expanduser().resolve()
        if not path.exists():
            logger.warning("Catalog overlay path missing (skipped): %s", path)
            continue
        if path.is_file() and path.suffix.lower() == ".json":
            files.append(path)
        elif path.is_dir():
            for f in sorted(path.glob("*.json")):
                if f.is_file():
                    files.append(f)
    return files


def _load_json_file(path: Path) -> list[dict[str, Any]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("Catalog overlay JSON unreadable %s: %s", path, e)
        return []
    return _parse_overlay_payload(raw)


def load_bundled_overlay_index() -> dict[str, dict[str, Any]]:
    global _bundled_index_cache
    if _bundled_index_cache is not None:
        return _bundled_index_cache
    idx: dict[str, dict[str, Any]] = {}
    if os.environ.get("OPENHAC_NO_BUNDLED_CATALOG_OVERLAYS", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    ):
        _bundled_index_cache = idx
        return idx
    if _PACKAGE_OVERLAY_DIR.is_dir():
        for f in sorted(_PACKAGE_OVERLAY_DIR.glob("*.json")):
            # LIB-007: reference BOMs are opt-in via --catalog-overlay, not every lookup.
            if "reference_bom" in f.name.lower():
                continue
            _merge_index(idx, _load_json_file(f))
    _bundled_index_cache = idx
    return idx


def _compile_context_overlay_paths() -> tuple[str, ...]:
    try:
        from openhac.core.compile_context import get_compile_context

        ctx = get_compile_context()
        if ctx is not None:
            raw = getattr(ctx, "catalog_overlay_paths", None) or ()
            out: list[str] = []
            for p in raw:
                s = str(p).strip()
                if s:
                    out.append(s)
            return tuple(out)
    except Exception:
        pass
    return ()


def _env_overlay_paths() -> tuple[str, ...]:
    raw = (os.environ.get("OPENHAC_CATALOG_OVERLAY") or "").strip()
    if not raw:
        return ()
    sep = os.pathsep
    parts = [x.strip() for x in raw.split(sep) if x.strip()]
    return tuple(parts)


def active_overlay_path_strings() -> tuple[str, ...]:
    """Paths from compile context plus env (deduped, context first)."""
    seen: set[str] = set()
    ordered: list[str] = []
    for p in _compile_context_overlay_paths() + _env_overlay_paths():
        if p not in seen:
            seen.add(p)
            ordered.append(p)
    return tuple(ordered)


def load_user_overlay_index() -> dict[str, dict[str, Any]]:
    global _user_index_cache
    key = active_overlay_path_strings()
    if _user_index_cache is not None and _user_index_cache[0] == key:
        return _user_index_cache[1]
    idx: dict[str, dict[str, Any]] = {}
    for fpath in _collect_json_files(key):
        _merge_index(idx, _load_json_file(fpath))
    _user_index_cache = (key, idx)
    return idx


def merge_overlay_into_row(row: dict) -> dict:
    """Apply bundled then user overlays for ``row['generic_name']``."""
    gn = row.get("generic_name")
    if not gn:
        return row
    gns = str(gn)
    bundled = load_bundled_overlay_index().get(gns)
    user = load_user_overlay_index().get(gns)
    if not bundled and not user:
        return row
    out = dict(row)
    for patch in (bundled, user):
        if not patch:
            continue
        for k, v in patch.items():
            if v is not None:
                out[k] = v
    return out


def pcb002_failure_hint() -> str:
    return (
        "Hint: add footprint-aligned pinouts via JSON overlays — "
        "`python3 -m openhac compile SCRIPT.py --catalog-overlay DIR` "
        "or set OPENHAC_CATALOG_OVERLAY. "
        "See openhac/database/package_catalog_overlays/README.md."
    )


def log_active_overlay_sources() -> None:
    paths = active_overlay_path_strings()
    if not paths:
        return
    logger.info(
        "Catalog overlays (user): %s file(s)/dir(s) — %s",
        len(paths),
        ", ".join(paths),
    )
