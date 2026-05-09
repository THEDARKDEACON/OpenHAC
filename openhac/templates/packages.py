"""Package templates for standard component packages.

Provides pinout definitions for common SMD packages.
This is used when explicit pin definitions are not provided by the user.
"""

from openhac.core.part import Pin


# Standard package pin definitions
PACKAGE_TEMPLATES = {
    # Resistors, capacitors, inductors - 2 terminal
    "0201": [Pin("1", "1", "passive"), Pin("2", "2", "passive")],
    "0402": [Pin("1", "1", "passive"), Pin("2", "2", "passive")],
    "0603": [Pin("1", "1", "passive"), Pin("2", "2", "passive")],
    "0805": [Pin("1", "1", "passive"), Pin("2", "2", "passive")],
    "1206": [Pin("1", "1", "passive"), Pin("2", "2", "passive")],
    "1210": [Pin("1", "1", "passive"), Pin("2", "2", "passive")],
    "2512": [Pin("1", "1", "passive"), Pin("2", "2", "passive")],
    
    # LEDs
    "LED_0603": [Pin("1", "K", "passive"), Pin("2", "A", "passive")],  # Cathode, Anode
    "LED_0805": [Pin("1", "K", "passive"), Pin("2", "A", "passive")],
    "LED_1206": [Pin("1", "K", "passive"), Pin("2", "A", "passive")],
    
    # SOT-23 (3-pin transistor package)
    "SOT-23": [
        Pin("1", "G", "input"),      # Gate/Base
        Pin("2", "S", "power_in"),   # Source/Emitter
        Pin("3", "D", "output"),     # Drain/Collector
    ],
    
    # SOT-23-5 (5-pin regulator/driver package)
    "SOT-23-5": [
        Pin("1", "IN", "power_in"),
        Pin("2", "GND", "ground"),
        Pin("3", "EN", "input"),
        Pin("4", "NC", "no_connect"),
        Pin("5", "OUT", "power_out"),
    ],
    
    # SOT-23-6 (6-pin package)
    "SOT-23-6": [
        Pin("1", "1", "bidirectional"),
        Pin("2", "2", "bidirectional"),
        Pin("3", "3", "bidirectional"),
        Pin("4", "4", "bidirectional"),
        Pin("5", "5", "bidirectional"),
        Pin("6", "6", "bidirectional"),
    ],
    
    # SOT-223 (4-pin regulator package)
    "SOT-223": [
        Pin("1", "IN", "power_in"),
        Pin("2", "GND", "ground"),
        Pin("3", "OUT", "power_out"),
        Pin("4", "OUT", "power_out"),  # Tab is also OUT
    ],
    
    # SOIC-8 (8-pin IC package)
    "SOIC-8": [
        Pin("1", "1", "bidirectional"),
        Pin("2", "2", "bidirectional"),
        Pin("3", "3", "bidirectional"),
        Pin("4", "4", "bidirectional"),
        Pin("5", "5", "bidirectional"),
        Pin("6", "6", "bidirectional"),
        Pin("7", "7", "bidirectional"),
        Pin("8", "8", "bidirectional"),
    ],
    
    # SOIC-16 (16-pin IC package)
    "SOIC-16": [Pin(str(i), str(i), "bidirectional") for i in range(1, 17)],
    
    # QFN-10 (10-pin DFN/QFN package - e.g., TPS63001)
    "QFN-10": [
        Pin("1", "1", "bidirectional"),
        Pin("2", "2", "bidirectional"),
        Pin("3", "3", "bidirectional"),
        Pin("4", "4", "bidirectional"),
        Pin("5", "5", "bidirectional"),
        Pin("6", "6", "bidirectional"),
        Pin("7", "7", "bidirectional"),
        Pin("8", "8", "bidirectional"),
        Pin("9", "9", "bidirectional"),
        Pin("10", "10", "bidirectional"),
    ],
    
    # VSON-10 (10-pin VSON package - TI specific)
    "VSON-10": [
        Pin("1", "1", "bidirectional"),
        Pin("2", "2", "bidirectional"),
        Pin("3", "3", "bidirectional"),
        Pin("4", "4", "bidirectional"),
        Pin("5", "5", "bidirectional"),
        Pin("6", "6", "bidirectional"),
        Pin("7", "7", "bidirectional"),
        Pin("8", "8", "bidirectional"),
        Pin("9", "9", "bidirectional"),
        Pin("10", "10", "bidirectional"),
    ],
    
    # LQFP-64 (64-pin MCU package)
    "LQFP-64": [Pin(str(i), str(i), "bidirectional") for i in range(1, 65)],
    
    # LQFP-100 (100-pin MCU package)
    "LQFP-100": [Pin(str(i), str(i), "bidirectional") for i in range(1, 101)],
    
    # LGA-16 (16-pin LGA - e.g., MPU9250)
    "LGA-16": [Pin(str(i), str(i), "bidirectional") for i in range(1, 17)],
    
    # QFN-24 (24-pin QFN - e.g., MPU9250 alternative)
    "QFN-24": [Pin(str(i), str(i), "bidirectional") for i in range(1, 25)],
}


def get_package_template(package: str, category: str = "") -> list[Pin] | None:
    """Get pin template for a standard package.
    
    Args:
        package: Package name (e.g., "0603", "SOT-23", "QFN-10")
        category: Optional category hint for better matching
        
    Returns:
        List of Pin objects if template exists, None otherwise
    """
    # Direct match
    if package in PACKAGE_TEMPLATES:
        return PACKAGE_TEMPLATES[package]
    
    # Normalized match (handle variations)
    normalized = package.upper().replace("-", "").replace("_", "")
    
    # Try common variations
    if normalized in ["0201", "0402", "0603", "0805", "1206", "1210", "2512"]:
        return PACKAGE_TEMPLATES.get(normalized)
    
    # Handle SOT variants
    if normalized in ["SOT23", "SOT223"]:
        return PACKAGE_TEMPLATES.get(normalized.replace("SOT", "SOT-"))
    
    # Handle LED packages
    if category and "led" in category.lower():
        if "0603" in package:
            return PACKAGE_TEMPLATES.get("LED_0603")
        if "0805" in package:
            return PACKAGE_TEMPLATES.get("LED_0805")
        if "1206" in package:
            return PACKAGE_TEMPLATES.get("LED_1206")
    
    # Handle crystal oscillators
    if category and "crystal" in category.lower():
        # Crystals typically have 2 or 4 pins
        return [Pin("1", "1", "passive"), Pin("2", "2", "passive")]
    
    return None


def register_custom_template(package: str, pins: list[Pin]) -> None:
    """Register a custom package template at runtime.
    
    Useful for adding support for non-standard packages.
    
    Args:
        package: Package identifier
        pins: List of Pin objects defining the package pinout
    """
    PACKAGE_TEMPLATES[package] = pins
