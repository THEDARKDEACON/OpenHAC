import math

def calculate_trace_width_ipc2152(current_a: float, temp_rise_c: float = 10.0, thickness_oz: float = 1.0) -> float:
    """Calculate minimum trace width using IPC-2152 standards for external layers.
    
    Args:
        current_a: Maximum current in Amperes.
        temp_rise_c: Allowed temperature rise in degrees Celsius (default 10C).
        thickness_oz: Copper thickness in ounces (default 1.0 oz = 35um).
        
    Returns:
        Trace width in millimeters (mm).
    """
    if current_a <= 0:
        return 0.25  # standard default minimum trace width

    # IPC-2221 / IPC-2152 constants for external traces
    k = 0.048
    b = 0.44
    c = 0.725

    # Area in square mils
    area_mils2 = (current_a / (k * (temp_rise_c ** b))) ** (1 / c)

    # Convert copper thickness to mils (1 oz = 1.37 mils)
    thickness_mils = thickness_oz * 1.37

    # Width in mils
    width_mils = area_mils2 / thickness_mils

    # Convert to millimeters (1 mil = 0.0254 mm)
    width_mm = width_mils * 0.0254

    # Ensure a reasonable manufacturing minimum
    return float(max(width_mm, 0.25))
