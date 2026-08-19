"""ABC-017/018: map jlcsearch packages to stock KiCad FPs and parse passive ratings."""

from __future__ import annotations

import json
import re
from typing import Any


_PASSIVE_FP = {
    "0201": ("Resistor_SMD:R_0201_0603Metric", "Capacitor_SMD:C_0201_0603Metric"),
    "0402": ("Resistor_SMD:R_0402_1005Metric", "Capacitor_SMD:C_0402_1005Metric"),
    "0603": ("Resistor_SMD:R_0603_1608Metric", "Capacitor_SMD:C_0603_1608Metric"),
    "0805": ("Resistor_SMD:R_0805_2012Metric", "Capacitor_SMD:C_0805_2012Metric"),
    "1206": ("Resistor_SMD:R_1206_3216Metric", "Capacitor_SMD:C_1206_3216Metric"),
}


def infer_passive_kind(description: str, category: str = "") -> str:
    blob = f"{category} {description}".lower()
    if "cap" in blob or "farad" in blob or "µf" in blob or "uf" in blob or "nf" in blob or "pf" in blob:
        return "capacitor"
    if "resistor" in blob or "ohm" in blob or "ω" in blob or "Ω" in description:
        return "resistor"
    if "led" in blob:
        return "led"
    return "unknown"


def stock_footprint_for_package(package: str, *, kind: str = "unknown", description: str = "") -> tuple[str, str]:
    """Return (footprint, footprint_source) preferring stock KiCad libs."""
    pkg = (package or "").strip().upper().replace(" ", "")
    k = kind if kind != "unknown" else infer_passive_kind(description)
    for key, (r_fp, c_fp) in _PASSIVE_FP.items():
        if key in pkg or pkg == key:
            if k == "capacitor":
                return c_fp, "stock_kicad"
            if k == "led":
                return f"LED_SMD:LED_{key}_{'1608' if key=='0603' else '2012' if key=='0805' else '1005'}Metric", "stock_kicad"
            return r_fp, "stock_kicad"
    if "SOT-223" in pkg or "SOT223" in pkg:
        return "Package_TO_SOT_SMD:SOT-223-3_TabPin2", "stock_kicad"
    if "SOT-23" in pkg or "SOT23" in pkg:
        return "Package_TO_SOT_SMD:SOT-23", "stock_kicad"
    return "", ""


def parse_voltage_rating_v(text: str) -> float | None:
    """Parse a voltage like '50V', '16V', '150V' from description/attrs."""
    if not text:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)\s*[Vv](?:\b|/)", text)
    if m:
        try:
            return float(m.group(1))
        except Exception:
            return None
    m = re.search(r"(\d+(?:\.\d+)?)\s*V\b", text)
    if m:
        try:
            return float(m.group(1))
        except Exception:
            return None
    return None


def parse_power_watts(text: str) -> float | None:
    if not text:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)\s*[mM][Ww]\b", text)
    if m:
        try:
            return float(m.group(1)) / 1000.0
        except Exception:
            return None
    m = re.search(r"(\d+(?:\.\d+)?)\s*[Ww]\b", text)
    if m:
        try:
            return float(m.group(1))
        except Exception:
            return None
    return None


def enrich_comp_data_from_jlc_item(comp_data: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    """Mutate/return comp_data with FP preference + ratings (ABC-017/018/019)."""
    package = str(item.get("package") or "")
    description = str(item.get("description") or comp_data.get("description") or "")
    category = str(item.get("category") or comp_data.get("category") or "")
    kind = infer_passive_kind(description, category)
    fp, src = stock_footprint_for_package(package, kind=kind, description=description)
    if fp:
        comp_data["kicad_footprint"] = fp
        if kind == "capacitor":
            comp_data["kicad_symbol"] = "Device:C"
            comp_data["category"] = "Capacitor"
        elif kind == "resistor":
            comp_data["kicad_symbol"] = "Device:R"
            comp_data["category"] = "Resistor"
        elif kind == "led":
            comp_data["kicad_symbol"] = "Device:LED"
            comp_data["category"] = "LED"
    else:
        src = src or "heuristic"

    vr = parse_voltage_rating_v(description)
    if vr is not None:
        comp_data["voltage_rating"] = vr
    pw = parse_power_watts(description)
    if pw is not None:
        comp_data["power_watts"] = pw

    # Persist footprint_source inside attributes_json (not a SQLite column).
    try:
        attrs = comp_data.get("attributes_json")
        if isinstance(attrs, str):
            attrs_obj = json.loads(attrs) if attrs else {}
        elif isinstance(attrs, dict):
            attrs_obj = dict(attrs)
        else:
            attrs_obj = {}
        if isinstance(attrs_obj, dict):
            if src:
                attrs_obj["footprint_source"] = src
            blob = json.dumps(attrs_obj)
            if "voltage_rating" not in comp_data:
                vr2 = parse_voltage_rating_v(blob)
                if vr2 is not None:
                    comp_data["voltage_rating"] = vr2
            if "power_watts" not in comp_data:
                pw2 = parse_power_watts(blob)
                if pw2 is not None:
                    comp_data["power_watts"] = pw2
            comp_data["attributes_json"] = blob
    except Exception:
        pass
    comp_data.pop("footprint_source", None)
    return comp_data
