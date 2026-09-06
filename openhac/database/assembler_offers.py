"""CAT-011: second assembler catalogs as ``part_offers``, not a second pin/footprint SoT.

PCBWay / Seeed stock is recorded as ranked offers. Pin tables stay on the
primary ``components`` row (overlay / Digi-Key / verified JLC).
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("openhac.assembler_offers")

ASSEMBLER_SUPPLIERS = frozenset({"pcbway", "seeed", "seeedstudio", "jlcpcb", "jlc"})


def ingest_part_offers(
    db,
    generic_name: str,
    offers: list[dict[str, Any]],
    *,
    start_rank: int = 1,
) -> int:
    """Insert offer rows. Never writes ``pinout_json`` on the component."""
    gn = str(generic_name or "").strip()
    if not gn:
        return 0
    n = 0
    rank = int(start_rank)
    for rec in offers or []:
        if not isinstance(rec, dict):
            continue
        supplier = str(rec.get("supplier") or rec.get("assembler") or "").strip()
        if not supplier:
            continue
        db.insert_part_offer(
            {
                "generic_name": gn,
                "rank": rank,
                "supplier": supplier,
                "supplier_sku": str(rec.get("supplier_sku") or rec.get("sku") or ""),
                "mpn": str(rec.get("mpn") or ""),
                "note": str(rec.get("note") or ""),
            },
            ignore_duplicate=True,
        )
        n += 1
        rank += 1
    return n


def ingest_pcbway_seeed_offers(db, generic_name: str, offers: list[dict[str, Any]]) -> int:
    """Documented ingest path for PCBWay / Seeed (live APIs may be stubbed)."""
    return ingest_part_offers(db, generic_name, offers)
