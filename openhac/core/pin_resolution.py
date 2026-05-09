"""Pin resolution pipeline: explicit → DB pinout → package template → fallback.

Extracted from ``Component`` methods in ``base.py`` so the logic can be tested
and reused without instantiating a full component.
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING

from openhac.core.part import Pin

if TYPE_CHECKING:
    from openhac.database.db_manager import DatabaseManager

logger = logging.getLogger("openhac.core")


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
) -> list[Pin]:
    """Resolve pinout for a component using a priority waterfall.

    Priority:
        1. *explicit_pins* provided by the caller / constructor
        2. ``pinout_json`` in *comp_data*
        3. Package template (via :func:`get_package_template_pins`)
        4. Generic numbered pins (last resort)
    """
    # Priority 1
    if explicit_pins:
        return pins_from_explicit(explicit_pins)

    # Priority 2
    pinout_json = comp_data.get("pinout_json")
    if pinout_json:
        try:
            pinout = json.loads(pinout_json)
            return [Pin(p["num"], p["name"], p.get("type", "bidirectional")) for p in pinout]
        except (json.JSONDecodeError, KeyError):
            pass

    # Priority 3
    package = comp_data.get("package", "")
    category = comp_data.get("category", "")
    if package:
        template_pins = get_package_template_pins(package, category)
        if template_pins:
            return template_pins

    # Priority 4
    return generate_generic_pins(comp_data)


def get_package_template_pins(package: str, category: str) -> list[Pin] | None:
    """Get pins from package templates for standard packages."""
    from openhac.templates.packages import get_package_template
    return get_package_template(package, category)


def generate_generic_pins(comp_data: dict) -> list[Pin]:
    """Generate generic numbered pins as fallback."""
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
        "kicad_symbol": f"Device:IC_{pin_count}PIN",
        "kicad_footprint": f"Package_SMD:Generic_{pin_count}PIN",
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
