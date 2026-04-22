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


def enrich_strict_pinout_pads() -> bool:
    """When true, pad mismatches during enrich raise instead of only logging."""
    return _truthy(os.environ.get("OPENHAC_ENRICH_STRICT_PINOUT_PADS"))


def _warn_if_pinout_mismatches_footprint_pads(db, gn: str) -> None:
    """After a successful DB update, log if stored pinout keys do not appear on the KiCad footprint."""
    try:
        row = db.get_component(gn)
    except Exception:
        return
    if not row:
        return
    fp = str(row.get("kicad_footprint") or "").strip()
    raw = row.get("pinout_json")
    if not fp or not raw:
        return
    if isinstance(raw, str):
        try:
            pinout = json.loads(raw)
        except Exception:
            return
    else:
        pinout = raw
    if not isinstance(pinout, list) or not pinout:
        return
    from openhac.compiler.pcb_placement import (
        footprint_pad_numbers_from_library,
        parse_footprint_id,
        _pin_covers_footprint_pad,
    )

    fpid = parse_footprint_id(fp)
    if fpid is None:
        return
    pads = footprint_pad_numbers_from_library(fpid[0], fpid[1])
    if not pads:
        return
    bad: list[str] = []
    for p in pinout:
        if not isinstance(p, dict):
            continue
        num = str(p.get("num") or "")
        name = str(p.get("name") or "")
        if not num and not name:
            continue
        if not _pin_covers_footprint_pad(num, name, pads):
            bad.append(f"{num or '?'}/{name or '?'}")
    if bad:
        msg = (
            f"Enriched pinout for {gn} may not match footprint {fp} pads (examples: "
            f"{', '.join(bad[:12])}). Align pin num/name with the `.kicad_mod` pad list."
        )
        if enrich_strict_pinout_pads():
            raise RuntimeError(msg)
        logger.warning(msg)


def _pinout_legacy_name_diversity(pinout: Any) -> bool:
    """True when some pin has a human-readable name that differs from its number (datasheet-style)."""
    if not isinstance(pinout, list) or not pinout:
        return False
    for p in pinout:
        if not isinstance(p, dict):
            continue
        num = str(p.get("num") or "").strip()
        name = str(p.get("name") or "").strip()
        if not num:
            continue
        if name and name != num:
            return True
    return False


def _pinout_numeric_fallback(pinout: Any) -> bool:
    """Conservative OK when footprint pads are unknown: distinct non-empty numeric-ish nums only."""
    if not isinstance(pinout, list) or not pinout:
        return False
    nums: list[str] = []
    for p in pinout:
        if not isinstance(p, dict):
            continue
        num = str(p.get("num") or "").strip()
        if not num:
            return False
        nums.append(num)
    if len(nums) != len(set(nums)):
        return False
    if not (1 <= len(nums) <= 256):
        return False
    return True


def _pinout_footprint_aligned(pinout: Any, row: dict[str, Any]) -> bool:
    """True if every pinout entry with num/name resolves to a pad on ``row['kicad_footprint']``."""
    if not isinstance(pinout, list) or not pinout or not row:
        return False
    pads = _footprint_pad_set_for_row(row)
    if not pads:
        return False
    from openhac.compiler.pcb_placement import _pin_covers_footprint_pad

    for p in pinout:
        if not isinstance(p, dict):
            continue
        num = str(p.get("num") or "")
        name = str(p.get("name") or "")
        if not num and not name:
            continue
        if not _pin_covers_footprint_pad(num, name, pads):
            return False
    return True


def _pinout_is_sufficient(pinout: Any, catalog_row: dict[str, Any] | None = None) -> bool:
    """Pinout is complete enough to skip re-enrichment: legacy diversity, footprint parity, or numeric fallback."""
    if not isinstance(pinout, list) or not pinout:
        return False
    if _pinout_legacy_name_diversity(pinout):
        return True
    if catalog_row is not None and _pinout_footprint_aligned(pinout, catalog_row):
        return True
    if catalog_row is None or not _footprint_pad_set_for_row(catalog_row):
        return _pinout_numeric_fallback(pinout)
    return False


def _pinout_is_meaningful(pinout: Any) -> bool:
    """Backward-compatible alias: legacy name/num diversity only (vendor placeholder heuristic)."""
    return _pinout_legacy_name_diversity(pinout)


def _pinout_list_from_raw(raw: Any) -> list | None:
    if raw is None:
        return None
    if isinstance(raw, list):
        return raw if raw else None
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return None
        try:
            data = json.loads(s)
        except Exception:
            return None
        return data if isinstance(data, list) else None
    return None


def needs_pinout_database_enrich(
    pinout_json_raw: Any,
    *,
    catalog_row: dict[str, Any] | None = None,
) -> bool:
    """True when the catalog row should still receive pinout enrichment (missing or not pad-safe)."""
    po = _pinout_list_from_raw(pinout_json_raw)
    if po is None:
        return True
    return not _pinout_is_sufficient(po, catalog_row)


def _footprint_pad_set_for_row(row: dict[str, Any]) -> set[str] | None:
    fp = str(row.get("kicad_footprint") or "").strip()
    if not fp:
        return None
    from openhac.compiler.pcb_placement import footprint_pad_numbers_from_library, parse_footprint_id

    fpid = parse_footprint_id(fp)
    if fpid is None:
        return None
    pads = footprint_pad_numbers_from_library(fpid[0], fpid[1])
    return pads if pads else None


def _filter_pinout_to_footprint_pads(pinout: list[dict], pads: set[str] | None) -> list[dict]:
    if not pads:
        return pinout
    from openhac.compiler.pcb_placement import _pin_covers_footprint_pad

    out: list[dict] = []
    for p in pinout:
        num = str(p.get("num") or "")
        name = str(p.get("name") or "")
        if _pin_covers_footprint_pad(num, name, pads):
            out.append(p)
    return out if out else pinout


def _local_pinout_for_row(row: dict[str, Any]) -> list[dict] | None:
    ks = str(row.get("kicad_symbol") or "").strip()
    if not ks:
        return None
    from openhac.compiler.kicad_sym_pinpos import pinout_from_kicad_symbol_id

    raw = pinout_from_kicad_symbol_id(ks)
    if not raw:
        return None
    pads = _footprint_pad_set_for_row(row)
    return _filter_pinout_to_footprint_pads(raw, pads)


def _best_enrich_pin_name(num: str, loc_name: str, ven_name: str) -> str:
    if ven_name and ven_name not in (num, "~") and ven_name != str(num):
        return ven_name
    if loc_name and loc_name not in ("", "~"):
        return loc_name
    return ven_name or loc_name or num


def _merge_pinouts_local_vendor_by_local_nums(
    local: list[dict],
    vendor: list[dict] | None,
    *,
    local_nums_only: bool = False,
) -> list[dict]:
    """Build merged pinout: pad numbers from *local* KiCad symbol order; names/types filled from vendor.

    When *local_nums_only* is True (pad-aligned KiCad local pinout), do not append extra vendor-only
    ``num`` keys (e.g. signal names that are not footprint pads).
    """
    v_by_num: dict[str, dict] = {}
    for p in vendor or []:
        if isinstance(p, dict) and str(p.get("num") or "").strip():
            v_by_num[str(p["num"]).strip()] = p
    order: list[str] = []
    seen: set[str] = set()
    for p in local or []:
        if not isinstance(p, dict):
            continue
        n = str(p.get("num") or "").strip()
        if not n or n in seen:
            continue
        seen.add(n)
        order.append(n)
    if not local_nums_only:
        for p in vendor or []:
            if not isinstance(p, dict):
                continue
            n = str(p.get("num") or "").strip()
            if n and n not in seen:
                seen.add(n)
                order.append(n)

    merged: list[dict] = []
    for n in order:
        loc = next(
            (x for x in (local or []) if isinstance(x, dict) and str(x.get("num") or "").strip() == n),
            None,
        )
        ven = v_by_num.get(n)
        loc_name = str((loc or {}).get("name") or "").strip() if loc else ""
        ven_name = str((ven or {}).get("name") or "").strip() if ven else ""
        name = _best_enrich_pin_name(n, loc_name, ven_name)
        typ = (loc or {}).get("type") if loc else None
        if typ is None and ven:
            typ = ven.get("type")
        if typ is None:
            typ = "bidirectional"
        merged.append({"num": n, "name": name, "type": typ})
    return merged


def _merge_kicad_and_vendor_pinouts(
    local: list[dict] | None,
    vendor: list[dict] | None,
    *,
    preference: str = "auto",
    row: dict[str, Any] | None = None,
) -> list[dict] | None:
    pref = (preference or "auto").strip().lower()
    pads = _footprint_pad_set_for_row(row) if row else None
    pads_known = bool(pads)
    loc_aligned = bool(local) and row is not None and _pinout_footprint_aligned(local, row)
    ven_aligned = bool(vendor) and row is not None and _pinout_footprint_aligned(vendor, row)

    def _lm_eff() -> bool:
        if not local:
            return False
        return bool(
            loc_aligned
            or _pinout_legacy_name_diversity(local)
            or (not pads_known and _pinout_numeric_fallback(local))
        )

    def _vm_eff() -> bool:
        if not vendor:
            return False
        if pads_known:
            return ven_aligned
        return _pinout_legacy_name_diversity(vendor) or _pinout_numeric_fallback(vendor)

    if pref == "vendor":
        if vendor and _vm_eff():
            return list(vendor)
        return list(local) if local else None
    if pref == "kicad_symbol":
        if local and _lm_eff():
            return list(local)
        return list(vendor) if vendor else None

    if not local and not vendor:
        return None

    if local and vendor and loc_aligned and pref == "auto":
        return _merge_pinouts_local_vendor_by_local_nums(local, vendor, local_nums_only=True)

    le, ve = _lm_eff(), _vm_eff()

    if not vendor:
        return list(local) if le else None

    if not local:
        if ve:
            return list(vendor)
        if vendor and pads_known and not ven_aligned:
            if enrich_strict_pinout_pads():
                return None
            return list(vendor)
        if vendor:
            return list(vendor)
        return None

    if not ve and le:
        return list(local)
    if not le and ve:
        return list(vendor)
    if not le and not ve:
        cand = vendor or local
        if cand and pads_known and not _pinout_footprint_aligned(cand, row):
            if enrich_strict_pinout_pads():
                return None
        return list(cand) if cand else None

    return _merge_pinouts_local_vendor_by_local_nums(local, vendor, local_nums_only=False)


def _persist_pinout_only(
    db,
    generic_name: str,
    pinout: list[dict],
    *,
    pinout_source: str,
) -> bool:
    try:
        return bool(
            db.update_component_fields(
                generic_name,
                {
                    "pinout_json": json.dumps(pinout),
                    "pinout_source": pinout_source,
                    "enriched_at_utc": datetime.now(timezone.utc).isoformat(),
                },
            )
        )
    except Exception:
        return False


def enrich_component_in_db(
    *,
    db,
    generic_name: str,
    mpn: str | None = None,
    jlcpcb_sku: str | None = None,
    preferred_vendor: str = "auto",
    allow_network: bool | None = None,
) -> EnrichResult:
    """Enrich a DB row using vendor APIs and/or the catalogued ``kicad_symbol`` library pinout.

    KiCad symbol pinouts are merged with vendor pinouts (see ``OPENHAC_ENRICH_PINOUT_PREFERENCE``)
    and can be persisted offline when the footprint/symbol resolve on disk.
    """
    if allow_network is None:
        allow_network = network_allowed()

    gn = str(generic_name or "").strip()
    if not gn:
        return EnrichResult(attempted=False, updated=False, vendor=None, reason="missing_generic_name")

    try:
        row = db.get_component(gn)
    except Exception:
        row = None
    if not row:
        return EnrichResult(attempted=False, updated=False, vendor=None, reason="not_in_db")

    existing_po = _pinout_list_from_raw(row.get("pinout_json"))
    row_d = dict(row)
    if _pinout_is_sufficient(existing_po, row_d):
        return EnrichResult(attempted=False, updated=False, vendor=None, reason="already_has_pinout")

    pref = (os.environ.get("OPENHAC_ENRICH_PINOUT_PREFERENCE") or "auto").strip().lower()
    local_po = _local_pinout_for_row(row)

    def _persist_kicad_symbol_pinout(*, attempted: bool) -> EnrichResult | None:
        if not local_po or pref == "vendor":
            return None
        if not _pinout_is_sufficient(local_po, row_d):
            return None
        if not _persist_pinout_only(db, gn, local_po, pinout_source="kicad_symbol"):
            return None
        try:
            _warn_if_pinout_mismatches_footprint_pads(db, gn)
        except Exception:
            pass
        return EnrichResult(attempted=attempted, updated=True, vendor=None, reason="kicad_symbol")

    mpn_eff = str(mpn or row.get("mpn") or "").strip() or None
    sku_eff = str(jlcpcb_sku or row.get("supplier_sku") or "").strip() or None
    jlc_eff = sku_eff if (sku_eff and sku_eff.upper().startswith("C") and sku_eff[1:].isdigit()) else None

    if not mpn_eff and not jlc_eff:
        r = _persist_kicad_symbol_pinout(attempted=False)
        if r is not None:
            return r
        return EnrichResult(attempted=False, updated=False, vendor=None, reason="no_mpn_or_sku")

    if not allow_network:
        r = _persist_kicad_symbol_pinout(attempted=False)
        if r is not None:
            return r
        return EnrichResult(attempted=False, updated=False, vendor=None, reason="network_disallowed")

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
                "Without them, only KiCad symbol pinout enrichment runs when ``kicad_symbol`` resolves."
            )
            _VENDOR_API_WARNED = True
        r = _persist_kicad_symbol_pinout(attempted=False)
        if r is not None:
            return r
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
            r = _persist_kicad_symbol_pinout(attempted=True)
            if r is not None:
                return r
            return EnrichResult(attempted=True, updated=False, vendor=None, reason=f"lookup_failed:{e}")
        if part is not None:
            break

    if part is None:
        r = _persist_kicad_symbol_pinout(attempted=True)
        if r is not None:
            return r
        return EnrichResult(attempted=True, updated=False, vendor=None, reason="not_found")

    vendor_po_raw = getattr(part, "pinout", None)
    had_usable_vendor_pinout = _pinout_is_sufficient(vendor_po_raw, row_d)
    pinout = getattr(part, "pinout", None)
    if pinout and not _pinout_is_sufficient(pinout, row_d):
        try:
            logger.info("Ignoring unusable pinout for %s from %s.", gn, getattr(part, "source_vendor", None))
        except Exception:
            pass
        try:
            part.pinout = None  # type: ignore[attr-defined]
        except Exception:
            pass

    vendor_po = getattr(part, "pinout", None)
    merged = _merge_kicad_and_vendor_pinouts(local_po, vendor_po, preference=pref, row=row_d)
    if merged:
        part.pinout = merged  # type: ignore[attr-defined]
    elif local_po and _pinout_footprint_aligned(local_po, row_d):
        part.pinout = list(local_po)  # type: ignore[attr-defined]
    else:
        try:
            part.pinout = None  # type: ignore[attr-defined]
        except Exception:
            pass

    if part.pinout:
        ven_tag = str(getattr(part, "source_vendor", None) or "").strip()
        if local_po and _pinout_is_sufficient(local_po, row_d):
            if had_usable_vendor_pinout and ven_tag:
                try:
                    setattr(part, "source_vendor", f"kicad_symbol+{ven_tag}")  # type: ignore[misc]
                except Exception:
                    pass
            elif not had_usable_vendor_pinout:
                try:
                    setattr(part, "source_vendor", "kicad_symbol")  # type: ignore[misc]
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

    if updated:
        try:
            _warn_if_pinout_mismatches_footprint_pads(db, gn)
        except Exception:
            pass

    return EnrichResult(
        attempted=True,
        updated=updated,
        vendor=getattr(part, "source_vendor", None),
        reason="ok" if updated else "no_change",
    )


def discover_enrich_targets_from_board(board: Any) -> list[dict[str, Any]]:
    """Build enrich targets from a loaded :class:`~openhac.core.board.Board` plus the SQLite catalog.

    Walks every component instance (unique ``generic_name``). For each part whose cached/DB row
    still needs a *meaningful* ``pinout_json`` (see :func:`needs_pinout_database_enrich`), returns
    a dict suitable for :func:`batch_enrich_targets`.

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
            row = None
            try:
                row = comp.db.get_component(gn)  # type: ignore[attr-defined]
            except Exception:
                row = None
            row_d = dict(row) if row else None
            if not needs_pinout_database_enrich(cd.get("pinout_json"), catalog_row=row_d):
                continue
            if row:
                if not needs_pinout_database_enrich(row.get("pinout_json"), catalog_row=row_d):
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

