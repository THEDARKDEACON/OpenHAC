"""PIN-001: overlay JSON stub from catalog row and/or KiCad symbol oracle. No datasheet scrape."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from openhac.core.exceptions import PinoutAuthoringError
from openhac.database.pin_policy import (
    is_ic_like_category,
    is_two_terminal_category,
    kicad_symbol_is_pin_name_oracle,
    parse_pinout,
    pinout_hash,
    pinout_is_numeric_only,
)

logger = logging.getLogger("openhac.pinout_init")


def _row_for_query(query: str, db) -> dict[str, Any] | None:
    q = str(query or "").strip()
    if not q:
        return None
    row = db.get_component(q)
    if row:
        return dict(row)
    try:
        found = db.get_component_by_supplier_sku(q)
        if found:
            return dict(found)
    except Exception:
        pass
    return None


def build_pinout_stub(query: str, *, db=None, kicad_pinout=None) -> dict[str, Any]:
    from openhac.core.base import Component
    from openhac.database.enrich import fill_pin_names_from_kicad_symbol

    mgr = db if db is not None else Component.db
    row = _row_for_query(query, mgr)
    gn = str((row or {}).get("generic_name") or query).strip()
    if not gn:
        raise PinoutAuthoringError("PIN-001: empty generic_name / ref")

    pins = parse_pinout((row or {}).get("pinout_json")) if row else None
    ks = str((row or {}).get("kicad_symbol") or "").strip()
    category = str((row or {}).get("category") or "")

    oracle_pins = None
    if kicad_pinout is not None:
        oracle_pins = parse_pinout(kicad_pinout)
    elif ks and kicad_symbol_is_pin_name_oracle(ks):
        try:
            oracle_pins = fill_pin_names_from_kicad_symbol(row or {"kicad_symbol": ks, "generic_name": gn})
        except Exception as e:
            logger.debug("PIN-001 KiCad oracle failed: %s", e)
            oracle_pins = None
        if oracle_pins is None:
            try:
                from openhac.compiler.kicad_sym_pinpos import pinout_from_kicad_symbol_id

                oracle_pins = pinout_from_kicad_symbol_id(ks)
            except Exception:
                oracle_pins = None

    if oracle_pins:
        pins = parse_pinout(oracle_pins) or pins

    if not pins:
        raise PinoutAuthoringError(
            f"PIN-001: no pin table for {gn!r} (catalog empty and KiCad symbol is not a pin-name oracle). "
            "No datasheet scrape."
        )

    ic_like = is_ic_like_category(category, gn) or (
        not is_two_terminal_category(category, gn) and len(pins) > 2
    )
    if ic_like and pinout_is_numeric_only(pins):
        raise PinoutAuthoringError(
            f"PIN-001: refusing numeric-only IC pinout for {gn!r}. "
            "Name the pins (CAT-004) or use a real KiCad symbol lib id (CAT-013)."
        )

    digest = pinout_hash(pins)
    stub = {
        "generic_name": gn,
        "kicad_symbol": ks,
        "kicad_footprint": str((row or {}).get("kicad_footprint") or ""),
        "category": category,
        "mpn": str((row or {}).get("mpn") or ""),
        "supplier_sku": str((row or {}).get("supplier_sku") or ""),
        "pinout": pins,
        "pinout_hash": digest,
        "note": "PIN-001 stub — review pin names before compile. Not scraped from a datasheet.",
    }
    return stub


def write_pinout_overlay(stub: dict[str, Any], dest: str | Path) -> Path:
    p = Path(dest)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps([stub], indent=2, sort_keys=True), encoding="utf-8")
    logger.info("Wrote pinout overlay stub %s", p)
    return p
