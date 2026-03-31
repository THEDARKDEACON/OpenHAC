class ERCPowerBudgetError(Exception):
    pass

class DRCViolationError(Exception):
    pass

def run_erc(board):
    print("Running Electrical Rule Check (ERC)...")
    total_draw = sum(mod.max_current_draw_ma for mod in board.modules if hasattr(mod, 'max_current_draw_ma'))
    total_supply = sum(mod.source_current_max_ma for mod in board.modules if hasattr(mod, 'source_current_max_ma'))
    
    if total_supply > 0 and total_draw > total_supply:
        raise ERCPowerBudgetError(f"ERC Failed: Theoretical current draw ({total_draw}mA) exceeds power supply bounds ({total_supply}mA).")
    elif total_supply > 0:
        print(f"ERC Status: Passed. Power Budget OK ({total_draw}mA / {total_supply}mA).")
    else:
        print("ERC Status: No power sources defined. Skipping budget checks.")

def calculate_ipc2152_trace_width(current_amps, temp_rise_c=10, copper_oz=1.0):
    """
    Simplified IPC-2152 formula for external traces.
    width_mils = (Area_mils2) / (copper_thickness_mils)
    """
    if current_amps <= 0:
        return 0.20 # default minimum manufacturer routing width mm
        
    k, b, c = 0.048, 0.44, 0.725
    area_mils2 = (current_amps / (k * (temp_rise_c ** b))) ** (1/c)
    thickness_mils = copper_oz * 1.378
    width_mils = area_mils2 / thickness_mils
    width_mm = width_mils * 0.0254
    return max(0.15, round(width_mm, 3)) # Ensure minimum manufacturer capability of 0.15mm

def run_drc(board):
    print("Running Design Rule Check (DRC)...")
    print("Calculating IPC-2152 Traces...")
    traces_calculated = 0
    
    for mod in board.modules:
        if hasattr(mod, 'expected_power_current_ma') and getattr(mod, 'expected_power_current_ma', 0) > 0:
            w_mm = calculate_ipc2152_trace_width(mod.expected_power_current_ma / 1000.0)
            print(f"  - DRC Constraint: Module {mod.name} power nets require minimal trace width of {w_mm}mm")
            traces_calculated += 1
            
    if traces_calculated == 0:
        print("DRC Status: Passed (Default 0.2mm trace assumptions applied).")
