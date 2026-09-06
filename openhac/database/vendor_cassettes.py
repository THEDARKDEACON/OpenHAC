"""Ingest recorded vendor JSON (Digi-Key-shaped + jlcsearch) into SQLite. No HTTP."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("openhac.database.vendor_cassettes")


def ingest_cassette_directory(dm, cassette_dir: str | Path) -> dict[str, int]:
    """Parse ``*digikey.json`` / ``*jlcsearch.json`` in *cassette_dir* and insert rows."""
    root = Path(cassette_dir)
    if not root.is_dir():
        raise FileNotFoundError(f"vendor cassette directory not found: {root}")
    dk_rows: list[dict[str, Any]] = []
    jlc_blob: dict[str, list[dict[str, Any]]] = {}
    for path in sorted(root.glob("*digikey.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            dk_rows.extend(x for x in raw if isinstance(x, dict))
    for path in sorted(root.glob("*jlcsearch.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            for cat, items in raw.items():
                if isinstance(items, list):
                    jlc_blob.setdefault(str(cat), []).extend(
                        x for x in items if isinstance(x, dict)
                    )
    return ingest_cassette_payloads(dm, dk_rows=dk_rows, jlc_blob=jlc_blob)


def ingest_cassette_payloads(
    dm,
    *,
    dk_rows: list[dict[str, Any]] | None = None,
    jlc_blob: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, int]:
    """Parse in-memory cassette payloads with the real vendor parsers. No HTTP."""
    from openhac.database.pin_policy import should_store_vendor_pinout
    from openhac.database.sync_jlc import _component_row_from_jlc_item
    from openhac.database.vendor_apis import DigiKeyAPI, JLCPCBAPI

    dk_api = DigiKeyAPI(client_id="cassette", client_secret="cassette")
    jlc_api = JLCPCBAPI(api_key=None)

    n_dk = 0
    for rec in dk_rows or []:
        product = rec.get("product")
        if not isinstance(product, dict):
            continue
        info = dk_api._parse_product(product)
        setattr(info, "source_vendor", "digikey")
        gn = str(rec.get("generic_name") or "").strip()
        if not gn:
            continue
        pinout = info.pinout
        cat = str(rec.get("db_category") or info.category or "")
        if pinout and not should_store_vendor_pinout(pinout, category=cat, generic_name=gn):
            pinout = None
        row = {
            "generic_name": gn,
            "kicad_symbol": rec.get("kicad_symbol") or "Device:R",
            "kicad_footprint": rec.get("kicad_footprint") or "",
            "manufacturer": info.manufacturer or "",
            "mpn": info.mpn or gn,
            "supplier_sku": info.supplier_sku or "",
            "description": info.description or "",
            "category": cat,
            "package": info.package or "",
            "jlc_class": "Basic",
            "catalog_tier": "warehouse",
            "datasheet_url": info.datasheet_url or "",
            "product_url": info.product_url or "",
            "attributes_json": "{}",
        }
        if pinout:
            row["pinout_json"] = json.dumps(pinout)
            row["pinout_source"] = "digikey"
            row["catalog_tier"] = "verified"
        dm.insert_component(row, ignore_duplicate=True)
        dm.update_component_from_vendor(gn, info)
        # Sidecar packing wins over a previously EasyEDA-poisoned SQLite row.
        packing = {
            "kicad_symbol": row["kicad_symbol"],
            "kicad_footprint": row["kicad_footprint"],
        }
        if row.get("pinout_json"):
            packing["pinout_json"] = row["pinout_json"]
            packing["pinout_source"] = row.get("pinout_source") or "digikey"
            packing["catalog_tier"] = row.get("catalog_tier") or "verified"
        dm.update_component_fields(gn, packing)
        n_dk += 1

    n_jlc = 0
    for category, items in (jlc_blob or {}).items():
        for item in items:
            info = jlc_api._parse_jlcsearch_item(item)
            setattr(info, "source_vendor", "jlcpcb")
            packed = _component_row_from_jlc_item(category, item)
            if not packed:
                continue
            dm.insert_component(packed, ignore_duplicate=True)
            dm.update_component_from_vendor(packed["generic_name"], info)
            packing = {
                k: packed[k]
                for k in ("kicad_symbol", "kicad_footprint")
                if packed.get(k)
            }
            if packing:
                dm.update_component_fields(packed["generic_name"], packing)
            n_jlc += 1

    logger.info("Ingested vendor cassettes: digikey=%s jlcsearch=%s", n_dk, n_jlc)
    return {"digikey": n_dk, "jlcsearch": n_jlc}
