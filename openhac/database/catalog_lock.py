"""Catalog lockfile (LOCK-001). Offline pin of SKU / pinout hash / footprint."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from openhac.core.exceptions import CatalogLockError
from openhac.database.catalog_coverage import catalog_grade, sha256_file
from openhac.database.pin_policy import parse_pinout, pinout_hash

logger = logging.getLogger("openhac.catalog_lock")

LOCK_SCHEMA = "openhac.lock.v1"


def _truthy(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in ("1", "true", "yes", "on")


def discover_lock_path(
    *,
    script_path: str | os.PathLike[str] | None = None,
    output_dir: str | os.PathLike[str] | None = None,
    project_name: str | None = None,
    explicit: str | os.PathLike[str] | None = None,
) -> Path | None:
    if explicit:
        p = Path(explicit)
        return p if p.is_file() else p
    env = (os.environ.get("OPENHAC_LOCK_FILE") or "").strip()
    if env:
        p = Path(env)
        if p.is_file():
            return p
    candidates: list[Path] = []
    if script_path:
        sp = Path(script_path)
        d = sp.parent if sp.suffix else sp
        if sp.is_file():
            d = sp.parent
        stem = sp.stem if sp.is_file() else (project_name or "board")
        candidates.extend(
            [
                d / "openhac.lock",
                d / f"{stem}.openhac-lock.json",
            ]
        )
    if output_dir and project_name:
        candidates.append(Path(output_dir) / f"{project_name}.openhac-lock.json")
        candidates.append(Path(output_dir) / "openhac.lock")
    for c in candidates:
        if c.is_file():
            return c
    return None


def _row_lock_entry(generic_name: str, row: dict[str, Any] | None, *, instance: dict[str, Any] | None = None) -> dict[str, Any]:
    rec = dict(row or {})
    inst = dict(instance or {})
    sku = str(inst.get("supplier_sku") or rec.get("supplier_sku") or "").strip()
    mpn = str(inst.get("mpn") or rec.get("mpn") or "").strip()
    fp = str(inst.get("kicad_footprint") or rec.get("kicad_footprint") or rec.get("footprint") or "").strip()
    po = inst.get("pinout_json") or rec.get("pinout_json")
    spice_inc = str(inst.get("spice_include") or rec.get("spice_include") or "").strip()
    spice_sha = str(rec.get("spice_sha256") or "").strip()
    if spice_inc and not spice_sha:
        p = Path(os.path.expanduser(spice_inc.replace("${OPENHAC_SPICE_VENDOR_DIR}", os.environ.get("OPENHAC_SPICE_VENDOR_DIR") or "")))
        if p.is_file():
            try:
                spice_sha = sha256_file(p)
            except Exception:
                spice_sha = ""
    entry: dict[str, Any] = {
        "generic_name": generic_name,
        "sku": sku,
        "mpn": mpn,
        "pinout_hash": pinout_hash(po) if po else "",
        "footprint": fp,
        "catalog_tier": str(rec.get("catalog_tier") or catalog_grade(rec) or "").strip(),
    }
    sha3 = str(rec.get("model_3d_sha256") or "").strip()
    if sha3:
        entry["model_3d_sha256"] = sha3
    if spice_inc:
        entry["spice_include"] = spice_inc
    if spice_sha:
        entry["spice_sha256"] = spice_sha
    return entry


def collect_lock_entries(board, db=None) -> list[dict[str, Any]]:
    from openhac.core.base import Component

    mgr = db if db is not None else Component.db
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    try:
        mods = list(board._get_all_modules())
    except Exception:
        mods = list(getattr(board, "modules", None) or [])
    for mod in mods:
        for comp in getattr(mod, "components", None) or []:
            gn = str(getattr(comp, "generic_name", "") or "").strip()
            if not gn or gn in seen:
                continue
            seen.add(gn)
            row = None
            try:
                row = mgr.get_component(gn)
            except Exception:
                row = None
            inst = dict(getattr(comp, "_comp_data", None) or {})
            sku = str(getattr(comp, "supplier_sku", "") or inst.get("supplier_sku") or "")
            if sku:
                inst["supplier_sku"] = sku
            part = getattr(comp, "part", None)
            if part is not None:
                inst.setdefault("kicad_footprint", getattr(part, "footprint", None))
            out.append(_row_lock_entry(gn, dict(row) if row else None, instance=inst))
    out.sort(key=lambda d: str(d.get("generic_name") or ""))
    return out


def collect_resolved_bom_entries(board) -> list[dict[str, Any]]:
    """Resolved BOM identity from the board graph + local catalog (no HTTP)."""
    return collect_lock_entries(board)


def write_lockfile(path: str | os.PathLike[str], entries: list[dict[str, Any]], *, project: str | None = None) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": LOCK_SCHEMA,
        "project": project or "",
        "parts": list(entries),
    }
    p.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    logger.info("Wrote catalog lock %s (%s parts)", p, len(entries))
    return p


def load_lockfile(path: str | os.PathLike[str]) -> dict[str, Any]:
    p = Path(path)
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise CatalogLockError(f"LOCK-001: lockfile is not a JSON object: {p}")
    return data


def compare_lock_to_bom(lock_parts: list[dict[str, Any]], bom_parts: list[dict[str, Any]]) -> list[str]:
    """Return disagreement messages for pinout hash / SKU / footprint."""
    by_gn = {str(p.get("generic_name") or ""): p for p in lock_parts if p.get("generic_name")}
    bom_by = {str(p.get("generic_name") or ""): p for p in bom_parts if p.get("generic_name")}
    msgs: list[str] = []
    for gn, locked in by_gn.items():
        rec = bom_by.get(gn)
        if rec is None:
            msgs.append(f"{gn}: locked part missing from resolved BOM")
            continue
        for key, label in (("sku", "SKU"), ("pinout_hash", "pinout hash"), ("footprint", "footprint")):
            a = str(locked.get(key) or "").strip()
            b = str(rec.get(key) or "").strip()
            if a and b and a != b:
                msgs.append(f"{gn}: {label} lock={a!r} resolved={b!r}")
            elif a and not b:
                msgs.append(f"{gn}: {label} locked {a!r} but resolved empty")
    return msgs


def enforce_lock(
    board,
    lock_path: str | os.PathLike[str],
    *,
    fail_closed: bool,
) -> list[str]:
    if _truthy("OPENHAC_ALLOW_NETWORK") and _truthy("OPENHAC_NO_NETWORK"):
        pass
    data = load_lockfile(lock_path)
    lock_parts = list(data.get("parts") or [])
    bom = collect_resolved_bom_entries(board)
    msgs = compare_lock_to_bom(lock_parts, bom)
    if msgs and fail_closed:
        raise CatalogLockError(
            "LOCK-001: resolved BOM disagrees with catalog lock "
            f"{lock_path}:\n" + "\n".join(f"  - {m}" for m in msgs)
        )
    if msgs:
        for m in msgs:
            logger.warning("LOCK-001 (handoff): %s", m)
    return msgs
