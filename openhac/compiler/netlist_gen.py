import csv
import logging

from openhac.core.circuit import default_circuit
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
    "Placement_Notes",
    "Assembly_Orientation",
    "DNP",
    "Component_Type",
    "Voltage_Rating",
    "Tolerance",
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
    """Write native netlist to *netlist_path*; optional BOM CSV to *bom_path*."""
    logger.info("Compiling Netlist → %s", netlist_path)
    default_circuit.generate_netlist(netlist_path)
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
        parts = sorted(default_circuit.parts, key=lambda p: natural_key(p.refdes))
        for part in parts:
            # Determine component type and placement notes
            ref = part.refdes
            fp = part.footprint
            val = part.value
            
            # Component type detection
            comp_type = "Unknown"
            if ref.startswith('R'):
                comp_type = "Resistor"
            elif ref.startswith('C'):
                comp_type = "Capacitor"
            elif ref.startswith('L'):
                comp_type = "Inductor"
            elif ref.startswith('D'):
                comp_type = "Diode"
            elif ref.startswith('Q'):
                comp_type = "Transistor"
            elif ref.startswith('U'):
                comp_type = "IC"
            elif ref.startswith('Y'):
                comp_type = "Crystal"
            elif ref.startswith('J') or ref.startswith('P'):
                comp_type = "Connector"
            elif ref.startswith('LED'):
                comp_type = "LED"
            elif ref.startswith('F'):
                comp_type = "Fuse"
            elif ref.startswith('SW'):
                comp_type = "Switch"
            elif ref.startswith('TP'):
                comp_type = "TestPoint"
            
            # DNP detection (test points, fiducials, etc.)
            dnp = "Yes" if comp_type in ("TestPoint",) or "DNP" in str(val).upper() else "No"
            
            # Placement notes based on component type
            placement_notes = ""
            if comp_type == "IC":
                placement_notes = "Pin 1 marking required"
            elif comp_type == "Polarized Capacitor" or "electrolytic" in fp.lower():
                placement_notes = "Polarity marking required"
            elif comp_type == "LED":
                placement_notes = "Cathode marking required"
            elif comp_type == "Diode":
                placement_notes = "Cathode band marking required"
            
            # Assembly orientation
            orientation = "0°"  # Default, would be overridden by placement data
            if hasattr(part, 'fields') and part.fields.get('OpenHaC_Rotation_Deg'):
                orientation = f"{part.fields.get('OpenHaC_Rotation_Deg')}°"
            
            full = {
                "Reference": ref,
                "Value": val,
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
                "Footprint": fp,
                "Placement_Notes": placement_notes,
                "Assembly_Orientation": orientation,
                "DNP": dnp,
                "Component_Type": comp_type,
                "Voltage_Rating": part.fields.get("Voltage_Rating", ""),
                "Tolerance": part.fields.get("Tolerance", ""),
            }
            writer.writerow({k: full[k] for k in fieldnames})
