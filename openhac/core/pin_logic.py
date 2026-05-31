"""
pin_logic.py — Semantic pin name resolution for data-driven hardware design.

This module provides "Fuzzy" mapping between logical intents (like 'VCC', 'SDA')
and the actual strings found in vendor-provided pinout_json data.
"""
import re
import json
import logging

logger = logging.getLogger("openhac.pin_logic")

# --- Universal Pin Aliases ---
# These maps logical "intents" to lists of regex/strings found in datasheets.
SEMANTIC_MAP = {
    "VCC": [r"^VDD$", r"^VCC$", r"^V_IN$", r"^VIN$", r"^3V3$", r"^5V$", r"^VBAT$", r"^POWER$"],
    "GND": [r"^VSS$", r"^GND$", r"^V- $", r"^GROUND$", r"^EP$"],
    "SDA": [r"SDA", r"DATA"],
    "SCL": [r"SCL", r"CLK", r"CLOCK"],
    "TX": [r"TXD?", r"UART_TX"],
    "RX": [r"RXD?", r"UART_RX"],
    "EN": [r"^EN$", r"^ENABLE$", r"^RESET$", r"^NRST$", r"^RUN$"],
    "MISO": [r"MISO", r"SDO", r"DO"],
    "MOSI": [r"MOSI", r"SDI", r"DI"],
    "SCK": [r"SCK", r"SCLK", r"CLK"],
    "CS": [r"^CS$", r"^SS$", r"^CHIP_SELECT$", r"^nCS$"],
}

def resolve_semantic_pin_aliases(key: str, pinout_json: str | None) -> list[str]:
    """Find actual pin numbers/names from a logical key using data-driven fuzzy matching."""
    if not pinout_json:
        return []
        
    try:
        pins = json.loads(pinout_json)
    except Exception:
        return []

    ks = str(key).upper().strip()
    
    # 1. Exact match in the pinout (already handled by Component.__getitem__, but safe to check)
    # 2. Check if the key is a semantic intent (e.g. "VCC")
    patterns = SEMANTIC_MAP.get(ks, [])
    
    # 3. If not a known intent, just use the key itself as a regex pattern
    if not patterns:
        patterns = [f".*{re.escape(ks)}.*"]

    matches = []
    for p in pins:
        p_name = str(p.get("name", "")).upper()
        p_num = str(p.get("num", ""))
        
        for pat in patterns:
            if re.search(pat, p_name, re.IGNORECASE) or re.search(pat, p_num, re.IGNORECASE):
                # Return the pin number as it's the most stable identifier for Part[]
                matches.append(p_num)
                break # Move to next pin
                
    return matches
