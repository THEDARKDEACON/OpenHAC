"""Online enrichment helpers (multi-vendor) with DB persistence.

This module is the single entrypoint for "missing data -> online lookup -> cache in SQLite".
It is used both by the compile pipeline and (optionally) by Component construction.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("openhac.enrich")

_VENDOR_API_WARNED = False


def _guess_mpn_tail_from_generic_name(gn: str) -> str | None:
    """Best-effort MPN from ``PREFIX_MPN`` style generic names (e.g. ``BUCK_TPS63001DRCR`` → ``TPS63001DRCR``)."""
    s = str(gn or "").strip()
    if "_" not in s:
        return None
    tail = s.split("_")[-1].strip()
    if len(tail) < 5:
        return None
    if not any(c.isdigit() for c in tail):
        return None
    return tail


def _search_strings_for_enrich(gn: str, mpn_eff: str | None) -> list[str]:
    """Ordered distinct query strings to try with :func:`lookup_part_live`."""
    seen: set[str] = set()
    out: list[str] = []
    for s in (mpn_eff, _guess_mpn_tail_from_generic_name(gn), gn):
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


@dataclass(frozen=True)
class EnrichResult:
    attempted: bool
    updated: bool
    vendor: str | None = None
    reason: str | None = None


def _truthy(v: str | None) -> bool:
    return str(v or "").strip().lower() in ("1", "true", "yes", "on")


def network_allowed() -> bool:
    """Policy gate for network access (defaults to allowed)."""
    if _truthy(os.environ.get("OPENHAC_NO_NETWORK")):
        return False
    # Deterministic builds should not silently depend on network.
    if _truthy(os.environ.get("OPENHAC_DETERMINISTIC")) and not _truthy(os.environ.get("OPENHAC_ALLOW_NETWORK")):
        return False
    return True


def _pinout_is_meaningful(pinout: Any) -> bool:
    """Reject placeholder pinouts where name==num for all pins."""
    if not isinstance(pinout, list) or not pinout:
        return False
    ok = False
    for p in pinout:
        if not isinstance(p, dict):
            continue
        num = str(p.get("num") or "").strip()
        name = str(p.get("name") or "").strip()
        if not num:
            continue
        if name and name != num:
            ok = True
            break
    return ok


def enrich_component_in_db(
    *,
    db,
    generic_name: str,
    mpn: str | None = None,
    jlcpcb_sku: str | None = None,
    preferred_vendor: str = "auto",
    allow_network: bool | None = None,
) -> EnrichResult:
    """Attempt to enrich a DB row for *generic_name* using online vendor APIs.

    Returns an :class:`EnrichResult` indicating whether an online request was attempted and
    whether any fields were updated in the SQLite DB.
    """
    if allow_network is None:
        allow_network = network_allowed()
    if not allow_network:
        return EnrichResult(attempted=False, updated=False, vendor=None, reason="network_disallowed")

    gn = str(generic_name or "").strip()
    if not gn:
        return EnrichResult(attempted=False, updated=False, vendor=None, reason="missing_generic_name")

    # Read current row.
    try:
        row = db.get_component(gn)
    except Exception:
        row = None
    if not row:
        return EnrichResult(attempted=False, updated=False, vendor=None, reason="not_in_db")

    # Skip if already covered.
    if row.get("pinout_json") or row.get("symbol_data"):
        return EnrichResult(attempted=False, updated=False, vendor=None, reason="already_has_pinout")

    mpn_eff = str(mpn or row.get("mpn") or "").strip() or None
    sku_eff = str(jlcpcb_sku or row.get("supplier_sku") or "").strip() or None

    # Only pass a JLC SKU if it looks like a C-number.
    jlc_eff = sku_eff if (sku_eff and sku_eff.upper().startswith("C") and sku_eff[1:].isdigit()) else None

    if not mpn_eff and not jlc_eff:
        return EnrichResult(attempted=False, updated=False, vendor=None, reason="no_mpn_or_sku")

    global _VENDOR_API_WARNED
    try:
        from openhac.database.vendor_apis import lookup_part_live, vendor_apis_configured
    except Exception:
        lookup_part_live = None  # type: ignore[assignment]
        vendor_apis_configured = lambda: False  # type: ignore[misc, assignment]

    if not vendor_apis_configured():
        if not _VENDOR_API_WARNED:
            logger.warning(
                "Part enrichment needs vendor API credentials (e.g. DIGIKEY_CLIENT_ID + DIGIKEY_CLIENT_SECRET, "
                "MOUSER_API_KEY, TME_API_TOKEN + TME_API_SECRET, or JLCPCB_API_KEY). "
                "Without them, online pinout enrichment cannot run."
            )
            _VENDOR_API_WARNED = True
        return EnrichResult(attempted=False, updated=False, vendor=None, reason="no_vendor_api_keys")

    part = None
    for q in _search_strings_for_enrich(gn, mpn_eff):
        try:
            part = lookup_part_live(
                q,
                preferred_vendor=str(preferred_vendor or "auto"),
                jlcpcb_sku=jlc_eff,
            )
        except Exception as e:
            return EnrichResult(attempted=True, updated=False, vendor=None, reason=f"lookup_failed:{e}")
        if part is not None:
            break

    if part is None:
        return EnrichResult(attempted=True, updated=False, vendor=None, reason="not_found")

    # If vendor provided no pinout, do not claim success; still persist other fields.
    # Validate pinout before writing (avoid polluting DB with placeholders).
    pinout = getattr(part, "pinout", None)
    if pinout and not _pinout_is_meaningful(pinout):
        try:
            logger.info("Ignoring placeholder pinout for %s from %s.", gn, getattr(part, "source_vendor", None))
        except Exception:
            pass
        try:
            part.pinout = None  # type: ignore[attr-defined]
        except Exception:
            pass

    # Best-effort: verify/resolve footprint if present and unresolved.
    try:
        from openhac.database.sync_jlc import _verify_and_resolve_kicad_footprint  # type: ignore

        raw_fp = str(row.get("kicad_footprint") or "").strip()
        if raw_fp:
            chosen, verified, resolved, notes = _verify_and_resolve_kicad_footprint(raw_fp)
            # Persist resolver outputs regardless of pinout.
            try:
                db.update_component_fields(
                    gn,
                    {
                        "kicad_footprint": chosen,
                        "footprint_verified": int(bool(verified)) if verified is not None else None,
                        "footprint_resolved": resolved,
                        "footprint_notes": notes,
                    },
                )
            except Exception:
                pass
    except Exception:
        pass

    # Ensure provenance fields are populated even if vendor APIs don't provide them.
    try:
        if getattr(part, "last_updated", None) is None:
            part.last_updated = datetime.now(timezone.utc)  # type: ignore[attr-defined]
    except Exception:
        pass

    try:
        updated = bool(db.update_component_from_vendor(gn, part))
    except Exception as e:
        return EnrichResult(attempted=True, updated=False, vendor=getattr(part, "source_vendor", None), reason=f"db_update_failed:{e}")

    return EnrichResult(
        attempted=True,
        updated=updated,
        vendor=getattr(part, "source_vendor", None),
        reason="ok" if updated else "no_change",
    )


def discover_enrich_targets_from_board(board: Any) -> list[dict[str, Any]]:
    """Build enrich targets from a loaded :class:`~openhac.core.board.Board` plus the SQLite catalog.

    Walks every component instance (unique ``generic_name``). For each part whose cached/DB row
    has neither ``pinout_json`` nor ``symbol_data``, returns a dict suitable for
    :func:`batch_enrich_targets` (``generic_name`` plus ``mpn`` / ``supplier_sku`` when the DB has them).

    Parts with no DB row still get ``{"generic_name": ...}`` so :func:`enrich_component_in_db` can
    report ``not_in_db`` (use ``--sync-jlc-before`` or a seed file to populate the catalog first).
    """
    try:
        modules = board._get_all_modules()
    except Exception:
        modules = getattr(board, "modules", []) or []
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for mod in modules:
        for comp in getattr(mod, "components", []) or []:
            gn = str(getattr(comp, "generic_name", "") or "").strip()
            if not gn or gn in seen:
                continue
            seen.add(gn)
            try:
                cd = getattr(comp, "_comp_data", {}) or {}
            except Exception:
                cd = {}
            if cd.get("pinout_json") or cd.get("symbol_data"):
                continue
            row = None
            try:
                row = comp.db.get_component(gn)  # type: ignore[attr-defined]
            except Exception:
                row = None
            if row:
                if row.get("pinout_json") or row.get("symbol_data"):
                    continue
                rec: dict[str, Any] = {"generic_name": gn}
                mpn = row.get("mpn")
                if mpn:
                    rec["mpn"] = mpn
                sku = row.get("supplier_sku")
                if sku:
                    rec["supplier_sku"] = sku
                out.append(rec)
            else:
                out.append({"generic_name": gn})
    return out


def parse_enrich_targets_from_json(raw: Any) -> list[dict[str, Any]]:
    """Parse the JSON shape accepted by ``openhac database enrich --skus-file``."""
    targets: list[dict[str, Any]] = []
    if isinstance(raw, list):
        for rec in raw:
            if isinstance(rec, dict):
                targets.append(rec)
            elif isinstance(rec, (list, tuple)) and len(rec) >= 1:
                targets.append({"generic_name": str(rec[0])})
    elif isinstance(raw, dict):
        items = raw.get("parts") if isinstance(raw.get("parts"), list) else []
        for rec in items:
            if isinstance(rec, dict):
                targets.append(rec)
    return targets


def batch_enrich_targets(
    targets: list[dict[str, Any]],
    *,
    db,
    vendor: str = "auto",
    limit: int = 0,
    quiet: bool = False,
) -> tuple[int, int]:
    """Run :func:`enrich_component_in_db` for each record. Returns (attempted, updated)."""
    attempted = 0
    updated = 0
    for rec in targets:
        if limit and attempted >= limit:
            break
        gn = str(rec.get("generic_name") or rec.get("name") or rec.get("lcsc") or "").strip()
        if not gn:
            continue
        mpn = rec.get("mpn")
        sku = rec.get("supplier_sku") or rec.get("sku") or rec.get("lcsc")
        res = enrich_component_in_db(db=db, generic_name=gn, mpn=mpn, jlcpcb_sku=sku, preferred_vendor=vendor)
        if res.attempted:
            attempted += 1
        if res.updated:
            updated += 1
        if not quiet:
            logger.info(
                "Enrich %s: attempted=%s updated=%s vendor=%s reason=%s",
                gn,
                res.attempted,
                res.updated,
                res.vendor,
                res.reason,
            )
    return attempted, updated


def batch_enrich_from_json_file(
    path: str | os.PathLike[str],
    *,
    db,
    vendor: str = "auto",
    limit: int = 0,
    quiet: bool = False,
) -> tuple[int, int]:
    """Parse JSON and run :func:`batch_enrich_targets`."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    targets = parse_enrich_targets_from_json(raw)
    return batch_enrich_targets(targets, db=db, vendor=vendor, limit=limit, quiet=quiet)

