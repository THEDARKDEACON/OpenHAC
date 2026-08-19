"""Pin resolution pipeline: explicit → DB pinout → package template → fallback.

Extracted from ``Component`` methods in ``base.py`` so the logic can be tested
and reused without instantiating a full component.
"""

from __future__ import annotations

import json
import logging
import os
import re
import warnings
from typing import TYPE_CHECKING

from openhac.core.exceptions import OpenHaCError
from openhac.core.part import Pin

if TYPE_CHECKING:
    from openhac.database.db_manager import DatabaseManager

logger = logging.getLogger("openhac.core")


def _fabrication_mode() -> bool:
    """True when OPENHAC_COMPILE_GOAL is fabrication (FAB-001 fail-closed)."""
    g = (os.environ.get("OPENHAC_COMPILE_GOAL") or "").strip().lower()
    return g in ("fabrication", "fab", "push_button_fab", "push-button-fab", "pushbuttonfab")


def _strict_pinout() -> bool:
    """Refuse invented Pin_N even in handoff when OPENHAC_STRICT_PINOUT is set."""
    return (os.environ.get("OPENHAC_STRICT_PINOUT") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def pins_from_explicit(pins: dict) -> list[Pin]:
    """Convert explicit pin definitions to :class:`Pin` objects.

    Args:
        pins: ``{pin_number: ("pin_name", "pin_type"), ...}`` or
              ``{pin_number: "pin_name", ...}`` (defaults to ``"bidirectional"``).
    """
    result: list[Pin] = []
    for num, info in pins.items():
        if isinstance(info, tuple):
            name, pin_type = info
            result.append(Pin(str(num), name, pin_type))
        else:
            result.append(Pin(str(num), info, "bidirectional"))
    return result


def get_pins_from_data(
    comp_data: dict,
    *,
    explicit_pins: dict | None = None,
    refuse_invented: bool | None = None,
) -> list[Pin]:
    """Resolve pinout for a component using a priority waterfall.

    Priority:
        1. *explicit_pins* provided by the caller / constructor
        2. ``pinout_json`` in *comp_data*
        3. Package template (via :func:`get_package_template_pins`)
        4. Generic numbered pins (last resort; refused in fabrication — FAB-001)

    When *refuse_invented* is True (default under fabrication), corrupt or missing
    pinout does not fall through to invented ``Pin_N`` pins.
    """
    if refuse_invented is None:
        refuse_invented = _fabrication_mode()
    gn = str(comp_data.get("generic_name") or "?")

    # Priority 1
    if explicit_pins:
        return pins_from_explicit(explicit_pins)

    # Priority 2
    pinout_json = comp_data.get("pinout_json")
    if pinout_json:
        try:
            pinout = json.loads(pinout_json)
            if not isinstance(pinout, list) or not pinout:
                raise KeyError("empty pinout")
            out = []
            for p in pinout:
                try:
                    unit = max(1, int(p.get("unit") or 1))
                except (TypeError, ValueError):
                    unit = 1
                out.append(
                    Pin(p["num"], p["name"], p.get("type", "bidirectional"), unit=unit)
                )
            return out
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            if refuse_invented:
                raise OpenHaCError(
                    f"FAB-001: invalid pinout_json for {gn!r}; refusing invented pins in fabrication mode."
                ) from e
            logger.warning("Invalid pinout_json for %r (%s); falling back.", gn, e)

    # Priority 3
    package = comp_data.get("package", "")
    category = comp_data.get("category", "")
    if package:
        template_pins = get_package_template_pins(package, category)
        if template_pins:
            return template_pins

    # Priority 4 — invent pins (handoff only; loud; optional strict refuse)
    pins = generate_generic_pins(comp_data)
    invented = any(str(getattr(p, "name", "")).startswith("Pin_") for p in pins)
    if invented:
        msg = (
            f"FAB-001: invented Pin_N pins for {gn!r} "
            f"(package={comp_data.get('package')!r}). "
            "Enrich pinout_json or provide explicit pins. "
            "Set OPENHAC_STRICT_PINOUT=1 to refuse outside fabrication."
        )
        if refuse_invented:
            raise OpenHaCError(
                f"FAB-001: no explicit pinout for {gn!r}; refusing invented Pin_N pins in fabrication mode. "
                "Enrich pinout_json or provide explicit pins."
            )
        if _strict_pinout():
            raise OpenHaCError(f"FAB-001 (OPENHAC_STRICT_PINOUT): {msg}")
        logger.warning("%s", msg)
        warnings.warn(msg, UserWarning, stacklevel=2)
        try:
            from openhac.core import base as core_base

            core_base._IMPLICIT_PIN_EVENTS.append(
                {
                    "generic_name": gn,
                    "refdes": "",
                    "pin_name": "Pin_N",
                    "invented": True,
                }
            )
        except Exception:
            pass
    return pins


def get_package_template_pins(package: str, category: str) -> list[Pin] | None:
    """Get pins from package templates for standard packages."""
    from openhac.templates.packages import get_package_template
    return get_package_template(package, category)


def generate_generic_pins(comp_data: dict) -> list[Pin]:
    """Generate generic numbered pins as fallback."""
    generic = str(comp_data.get("generic_name") or "").strip().upper()
    sym = str(comp_data.get("kicad_symbol") or "").strip().upper()
    if generic == "PWR_FLAG" or sym.endswith(":PWR_FLAG") or sym == "PWR_FLAG":
        return [Pin("1", "pwr", "power_out")]
    package = comp_data.get("package", "")
    pin_count = estimate_pin_count(package)
    return [Pin(str(i), f"Pin_{i}", "bidirectional") for i in range(1, pin_count + 1)]


def estimate_pin_count(package: str) -> int:
    """Estimate number of pins from package name."""
    if not package:
        return 2
    # Try to extract pin count from package name (e.g., "QFN-10", "SOIC-8")
    match = re.search(r'(\d+)', str(package))
    if match:
        return int(match.group(1))
    # Default guesses based on package type
    pkg = str(package).upper()
    if any(x in pkg for x in ['SOT-23', 'SOT23']):
        return 3
    if any(x in pkg for x in ['SOT-223', 'SOT223']):
        return 4
    if any(x in pkg for x in ['0805', '0603', '0402', '1206']):
        return 2
    return 8  # Default


def infer_package(pin_count: int) -> str:
    """Infer package name from pin count."""
    if pin_count <= 2:
        return "0805"
    if pin_count <= 3:
        return "SOT-23"
    if pin_count <= 8:
        return "SOIC-8"
    if pin_count <= 16:
        return "QFN-16"
    return f"QFP-{pin_count}"


def _fallback_footprint(pin_count: int) -> str:
    """Map a pin count to a real KiCad footprint that exists in the installed library.
    
    These are generic but valid KiCad standard footprints that are always present
    under /usr/share/kicad/footprints when KiCad is installed.
    """
    if pin_count <= 2:
        return "Resistor_SMD:R_0805_2012Metric"
    if pin_count <= 3:
        return "Package_TO_SOT_SMD:SOT-23"
    if pin_count <= 5:
        return "Package_TO_SOT_SMD:SOT-23-5"
    if pin_count <= 6:
        return "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm"
    if pin_count <= 8:
        return "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm"
    if pin_count <= 14:
        return "Package_SO:SOIC-14_3.9x8.7mm_P1.27mm"
    if pin_count <= 16:
        return "Package_SO:SOIC-16_3.9x9.9mm_P1.27mm"
    if pin_count <= 20:
        return "Package_SO:SOIC-20W_7.5x12.8mm_P1.27mm"
    if pin_count <= 28:
        return "Package_DIP:DIP-28_W7.62mm"
    if pin_count <= 32:
        return "Package_QFP:LQFP-32_7x7mm_P0.8mm"
    if pin_count <= 48:
        return "Package_QFP:LQFP-48_7x7mm_P0.5mm"
    if pin_count <= 64:
        return "Package_QFP:LQFP-64_10x10mm_P0.5mm"
    if pin_count <= 100:
        return "Package_QFP:LQFP-100_14x14mm_P0.5mm"
    if pin_count <= 128:
        return "Package_BGA:BGA-128_11.35x13.0mm_Layout16x8_P0.8mm"
    if pin_count <= 256:
        return "Package_BGA:BGA-256_17.0x17.0mm_Layout16x16_P1.0mm_Ball0.5mm_Pad0.4mm_NSMD"
    return "Package_BGA:BGA-256_17.0x17.0mm_Layout16x16_P1.0mm_Ball0.5mm_Pad0.4mm_NSMD"


def create_comp_data_from_explicit_pins(
    generic_name: str,
    pins: dict,
    db: "DatabaseManager | None" = None,
) -> dict:
    """Create minimal component data from explicit pin definitions.

    Optionally caches the record in *db* for reuse.
    """
    pinout = [
        {
            "num": str(k),
            "name": v[0] if isinstance(v, tuple) else v,
            "type": v[1] if isinstance(v, tuple) else "bidirectional",
        }
        for k, v in pins.items()
    ]

    pin_count = len(pins)
    package = infer_package(pin_count)

    comp_data = {
        "generic_name": generic_name,
        "mpn": generic_name.split("_")[-1] if "_" in generic_name else generic_name,
        "manufacturer": "",
        "description": f"User-defined component with {pin_count} pins",
        "category": "unknown",
        "package": package,
        "kicad_symbol": f"Device:IC_Generic",
        "kicad_footprint": _fallback_footprint(pin_count),
        "pinout_json": json.dumps(pinout),
    }

    if db is not None:
        try:
            db.insert_component(comp_data, ignore_duplicate=True)
            logger.info("Created component '%s' with %s explicit pins", generic_name, pin_count)
        except Exception as e:
            logger.warning("Could not cache component '%s': %s", generic_name, e)

    return comp_data


def generate_fallback_pins(comp_data: dict) -> list[Pin]:
    """Generate generic pins based on footprint as last resort."""
    footprint = comp_data.get("kicad_footprint", "").lower()

    # SOIC/SOP packages
    match = re.search(r'so(?:ic|-)?(?:\D+)?(\d+)', footprint)
    if match:
        count = int(match.group(1))
        return [Pin(str(i), str(i), "bidirectional") for i in range(1, count + 1)]

    # QFN/QFP packages
    match = re.search(r'q(?:fn|fp)-?(?:\D+)?(\d+)', footprint)
    if match:
        count = int(match.group(1))
        return [Pin(str(i), str(i), "bidirectional") for i in range(1, count + 1)]

    # Passive components (resistors, capacitors, inductors, LEDs, diodes)
    if any(x in footprint for x in ['_r_', '_c_', '_l_', 'led_', 'd_']):
        return [Pin("1", "1", "passive"), Pin("2", "2", "passive")]

    # Default: 8 pins
    return [Pin(str(i), str(i), "bidirectional") for i in range(1, 9)]
