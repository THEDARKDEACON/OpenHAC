import csv
import logging
from skidl import generate_netlist

from openhac.circuit import get_default_circuit
from openhac.util.sort_keys import natural_key

logger = logging.getLogger("openhac.netlist")

# Full BOM column set (dev / default).
_BOM_ALL_FIELDNAMES: tuple[str, ...] = (
    "Reference",
    "Value",
    "Manufacturer",
    "MPN",
    "Supplier_SKU",
    "Alternate_SKUs",
    "Alternate_Notes",
    "Alternate_Group_ID",
    "Alternate_Count",
    "Ranked_Offers",
    "Primary_Offer",
    "Secondary_Offer",
    "Offer_Count",
    "OpenHaC_JIT_Confidence",
    "OpenHaC_JIT_Score",
    "Mouser_SKU",
    "DigiKey_SKU",
    "JLC_Class",
    "OpenHaC_Watermark",
    "Footprint",
)

# LIB-004: production-style BOM omits internal / alternate-expansion columns for CM handoff.
BOM_PROFILE_PROD_OMITTED_COLUMNS: frozenset[str] = frozenset(
    {
        "Alternate_SKUs",
        "Alternate_Notes",
        "Alternate_Group_ID",
        "Alternate_Count",
        "Ranked_Offers",
        "Primary_Offer",
        "Secondary_Offer",
        "Offer_Count",
        "OpenHaC_JIT_Confidence",
        "OpenHaC_JIT_Score",
        "OpenHaC_Watermark",
    }
)


def bom_fieldnames_for_profile(bom_profile: str | None) -> list[str]:
    """Return CSV columns for *bom_profile* (``prod`` / ``production`` / ``cm`` strips dev columns)."""
    if not bom_profile:
        return list(_BOM_ALL_FIELDNAMES)
    p = str(bom_profile).strip().lower()
    if p in ("prod", "production", "cm"):
        return [c for c in _BOM_ALL_FIELDNAMES if c not in BOM_PROFILE_PROD_OMITTED_COLUMNS]
    return list(_BOM_ALL_FIELDNAMES)


def generate_logic_and_bom(
    netlist_path: str, *, bom_path: str | None = None, bom_profile: str | None = None
):
    """Write SKiDL netlist to *netlist_path*; optional BOM CSV to *bom_path*."""
    logger.info("Compiling Netlist → %s", netlist_path)
    generate_netlist(file_=netlist_path)
    logger.info("Generated %s", netlist_path)

    if bom_path is None:
        return

    fieldnames = bom_fieldnames_for_profile(bom_profile)
    if bom_profile and str(bom_profile).strip().lower() in ("prod", "production", "cm"):
        logger.info(
            "LIB-004: BOM profile %r → omitting columns %s",
            bom_profile,
            sorted(BOM_PROFILE_PROD_OMITTED_COLUMNS),
        )
    logger.info("Exporting BOM to %s...", bom_path)
    with open(bom_path, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        parts = sorted(get_default_circuit().parts, key=lambda p: natural_key(getattr(p, "ref", "")))
        for part in parts:
            full = {
                "Reference": part.ref,
                "Value": part.value,
                "Manufacturer": part.fields.get("Manufacturer", ""),
                "MPN": part.fields.get("MPN", ""),
                "Supplier_SKU": part.fields.get("Supplier_SKU", ""),
                "Alternate_SKUs": part.fields.get("Alternate_SKUs", ""),
                "Alternate_Notes": part.fields.get("Alternate_Notes", ""),
                "Alternate_Group_ID": part.fields.get("Alternate_Group_ID", ""),
                "Alternate_Count": part.fields.get("Alternate_Count", ""),
                "Ranked_Offers": part.fields.get("Ranked_Offers", ""),
                "Primary_Offer": part.fields.get("Primary_Offer", ""),
                "Secondary_Offer": part.fields.get("Secondary_Offer", ""),
                "Offer_Count": part.fields.get("Offer_Count", ""),
                "OpenHaC_JIT_Confidence": part.fields.get("OpenHaC_JIT_Confidence", ""),
                "OpenHaC_JIT_Score": part.fields.get("OpenHaC_JIT_Score", ""),
                "Mouser_SKU": part.fields.get("Mouser_SKU", ""),
                "DigiKey_SKU": part.fields.get("DigiKey_SKU", ""),
                "JLC_Class": part.fields.get("JLC_Class", ""),
                "OpenHaC_Watermark": part.fields.get("OpenHaC_WATERMARK", ""),
                "Footprint": part.footprint,
            }
            writer.writerow({k: full[k] for k in fieldnames})
