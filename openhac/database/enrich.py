"""Online enrichment helpers (multi-vendor) with DB persistence.

This module is the single entrypoint for "missing data -> online lookup -> cache in SQLite".
It is used both by the compile pipeline and (optionally) by Component construction.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("openhac.enrich")

_VENDOR_API_WARNED = False

# Universal 3D Asset Overrides for standard modules
# These map LCSC SKUs OR Generic Names to high-fidelity community-verified STEP files and footprints
PHYSICAL_ASSET_OVERRIDES = {
    "C2114620": { # Raspberry Pi 5 8GB (LCSC)
        "footprint": "Connector_PinHeader_2.54mm:PinHeader_2x20_P2.54mm_Vertical",
    },
    "C2344710": { # Teensy 4.1 (LCSC)
        "footprint": "Connector_PinHeader_2.54mm:PinHeader_2x24_P2.54mm_Vertical",
    },
    "C2991758": { # XT90-S
        "footprint": "Connector_AMASS:AMASS_XT90-S_1x02_P15.50mm_Vertical",
    },
    "Raspberry_Pi_5_8GB": {
        "sku": "C2114620",
        "footprint": "Connector_PinHeader_2.54mm:PinHeader_2x20_P2.54mm_Vertical",
    },
    "Teensy_4.1": {
        "sku": "C2344710",
        "footprint": "Connector_PinHeader_2.54mm:PinHeader_2x24_P2.54mm_Vertical",
    },
    "Turnigy_Graphene_4S": {
        "sku": "C2991758",
        "footprint": "Connector_AMASS:AMASS_XT90-S_1x02_P15.50mm_Vertical",
    }
}

# Semantic Pinout Library for High-Fidelity Modules
SEMANTIC_PINOUTS = {
    "Raspberry_Pi_5": [
        {"num": "1", "name": "3.3V", "type": "power_in"}, {"num": "2", "name": "5V", "type": "power_in"},
        {"num": "3", "name": "SDA1", "type": "bidirectional"}, {"num": "4", "name": "5V", "type": "power_in"},
        {"num": "5", "name": "SCL1", "type": "bidirectional"}, {"num": "6", "name": "GND", "type": "power_in"},
        {"num": "7", "name": "GPIO4", "type": "bidirectional"}, {"num": "8", "name": "UART_TX0", "type": "output"},
        {"num": "9", "name": "GND", "type": "power_in"}, {"num": "10", "name": "UART_RX0", "type": "input"},
        {"num": "11", "name": "GPIO17", "type": "bidirectional"}, {"num": "12", "name": "PWM18", "type": "bidirectional"},
        {"num": "13", "name": "GPIO27", "type": "bidirectional"}, {"num": "14", "name": "GND", "type": "power_in"},
        {"num": "15", "name": "GPIO22", "type": "bidirectional"}, {"num": "16", "name": "GPIO23", "type": "bidirectional"},
        {"num": "17", "name": "3.3V", "type": "power_in"}, {"num": "18", "name": "GPIO24", "type": "bidirectional"},
        {"num": "19", "name": "MOSI0", "type": "bidirectional"}, {"num": "20", "name": "GND", "type": "power_in"},
        {"num": "21", "name": "MISO0", "type": "bidirectional"}, {"num": "22", "name": "GPIO25", "type": "bidirectional"},
        {"num": "23", "name": "SCLK0", "type": "bidirectional"}, {"num": "24", "name": "CE0", "type": "bidirectional"},
        {"num": "25", "name": "GND", "type": "power_in"}, {"num": "26", "name": "CE1", "type": "bidirectional"},
        {"num": "27", "name": "ID_SD", "type": "bidirectional"}, {"num": "28", "name": "ID_SC", "type": "bidirectional"},
        {"num": "29", "name": "GPIO5", "type": "bidirectional"}, {"num": "30", "name": "GND", "type": "power_in"},
        {"num": "31", "name": "GPIO6", "type": "bidirectional"}, {"num": "32", "name": "PWM12", "type": "bidirectional"},
        {"num": "33", "name": "PWM13", "type": "bidirectional"}, {"num": "34", "name": "GND", "type": "power_in"},
        {"num": "35", "name": "MISO1", "type": "bidirectional"}, {"num": "36", "name": "CE2", "type": "bidirectional"},
        {"num": "37", "name": "GPIO26", "type": "bidirectional"}, {"num": "38", "name": "MOSI1", "type": "bidirectional"},
        {"num": "39", "name": "GND", "type": "power_in"}, {"num": "40", "name": "SCLK1", "type": "bidirectional"}
    ],
    "Teensy_4.1": [
        {"num": "1", "name": "GND", "type": "power_in"}, {"num": "2", "name": "0_RX1", "type": "bidirectional"},
        {"num": "3", "name": "1_TX1", "type": "bidirectional"}, {"num": "4", "name": "2_OUT2", "type": "bidirectional"},
        {"num": "5", "name": "3_CAN_TX", "type": "bidirectional"}, {"num": "6", "name": "4_CAN_RX", "type": "bidirectional"},
        {"num": "7", "name": "5_OUT1", "type": "bidirectional"}, {"num": "8", "name": "6_OUT1B", "type": "bidirectional"},
        {"num": "9", "name": "7_RX2", "type": "bidirectional"}, {"num": "10", "name": "8_TX2", "type": "bidirectional"},
        {"num": "11", "name": "9_OUT1C", "type": "bidirectional"}, {"num": "12", "name": "10_CS", "type": "bidirectional"},
        {"num": "13", "name": "11_MOSI", "type": "bidirectional"}, {"num": "14", "name": "12_MISO", "type": "bidirectional"},
        {"num": "15", "name": "VUSB", "type": "power_in"}, {"num": "16", "name": "VBAT", "type": "power_in"},
        {"num": "17", "name": "3.3V", "type": "power_in"}, {"num": "18", "name": "GND", "type": "power_in"},
        {"num": "19", "name": "PROGRAM", "type": "input"}, {"num": "20", "name": "ON_OFF", "type": "input"},
        {"num": "21", "name": "13_SCK", "type": "bidirectional"}, {"num": "22", "name": "14_A0", "type": "bidirectional"},
        {"num": "23", "name": "15_A1", "type": "bidirectional"}, {"num": "24", "name": "16_A2", "type": "bidirectional"},
        {"num": "25", "name": "17_A3", "type": "bidirectional"}, {"num": "26", "name": "18_SDA", "type": "bidirectional"},
        {"num": "27", "name": "19_SCL", "type": "bidirectional"}, {"num": "28", "name": "20_A6", "type": "bidirectional"},
        {"num": "29", "name": "21_A7", "type": "bidirectional"}, {"num": "30", "name": "22_A8", "type": "bidirectional"},
        {"num": "31", "name": "23_A9", "type": "bidirectional"}, {"num": "32", "name": "3.3V", "type": "power_in"},
        {"num": "33", "name": "GND", "type": "power_in"}, {"num": "34", "name": "VIN", "type": "power_in"},
        {"num": "35", "name": "24_A10", "type": "bidirectional"}, {"num": "36", "name": "25_A11", "type": "bidirectional"},
        {"num": "37", "name": "26_A12", "type": "bidirectional"}, {"num": "38", "name": "27_A13", "type": "bidirectional"},
        {"num": "39", "name": "28_RX7", "type": "bidirectional"}, {"num": "40", "name": "29_TX7", "type": "bidirectional"},
        {"num": "41", "name": "30_RX8", "type": "bidirectional"}, {"num": "42", "name": "31_TX8", "type": "bidirectional"},
        {"num": "43", "name": "32_OUT1D", "type": "bidirectional"}, {"num": "44", "name": "33_MISO2", "type": "bidirectional"},
        {"num": "45", "name": "34_DAT1", "type": "bidirectional"}, {"num": "46", "name": "35_DAT0", "type": "bidirectional"},
        {"num": "47", "name": "36_CLK", "type": "bidirectional"}, {"num": "48", "name": "37_CMD", "type": "bidirectional"}
    ]
}

def _get_override_asset(key: str) -> dict[str, str] | None:
    val = PHYSICAL_ASSET_OVERRIDES.get(key)
    if isinstance(val, str):
        return PHYSICAL_ASSET_OVERRIDES.get(val)
    return val


def _guess_mpn_tail_from_generic_name(gn: str) -> str | None:
    """Best-effort MPN from ``PREFIX_MPN`` style generic names (e.g. ``BUCK_TPS63001DRCR`` → ``TPS63001DRCR``)."""
    s = str(gn or "").strip()
    if "_" not in s:
        return None
    tail = s.split("_")[-1].strip()
    if len(tail) < 5:
        return None
    if not any(c.isdigit() for c in tail):
        return None
    return tail


def _search_strings_for_enrich(gn: str, mpn_eff: str | None) -> list[str]:
    """Ordered distinct query strings to try with :func:`lookup_part_live`."""
    seen: set[str] = set()
    out: list[str] = []
    for s in (mpn_eff, _guess_mpn_tail_from_generic_name(gn), gn):
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


@dataclass(frozen=True)
class EnrichResult:
    attempted: bool
    updated: bool
    vendor: str | None = None
    reason: str | None = None


def _truthy(v: str | None) -> bool:
    return str(v or "").strip().lower() in ("1", "true", "yes", "on")


def network_allowed() -> bool:
    """Policy gate for network access.

    Defaults to allowed in handoff/dev. Denied when:
    - ``OPENHAC_NO_NETWORK`` is set, or
    - deterministic mode without ``OPENHAC_ALLOW_NETWORK``, or
    - fabrication compile goal without ``OPENHAC_ALLOW_NETWORK`` (FAB-010).
    """
    if _truthy(os.environ.get("OPENHAC_NO_NETWORK")):
        return False
    allow_break_glass = _truthy(os.environ.get("OPENHAC_ALLOW_NETWORK"))
    if _truthy(os.environ.get("OPENHAC_DETERMINISTIC")) and not allow_break_glass:
        return False
    goal = (os.environ.get("OPENHAC_COMPILE_GOAL") or "").strip().lower()
    if goal in ("fabrication", "fab", "push_button_fab", "push-button-fab", "pushbuttonfab"):
        if not allow_break_glass:
            return False
    return True


def enrich_strict_pinout_pads() -> bool:
    """When true, pad mismatches during enrich raise instead of only logging."""
    return _truthy(os.environ.get("OPENHAC_ENRICH_STRICT_PINOUT_PADS"))


def _warn_if_pinout_mismatches_footprint_pads(db, gn: str) -> None:
    """After a successful DB update, log if stored pinout keys do not appear on the KiCad footprint."""
    try:
        row = db.get_component(gn)
    except Exception:
        return
    if not row:
        return
    fp = str(row.get("kicad_footprint") or "").strip()
    raw = row.get("pinout_json")
    if not fp or not raw:
        return
    if isinstance(raw, str):
        try:
            pinout = json.loads(raw)
        except Exception:
            return
    else:
        pinout = raw
    if not isinstance(pinout, list) or not pinout:
        return
    from openhac.compiler.pcb_placement import (
        footprint_pad_numbers_from_library,
        parse_footprint_id,
        _pin_covers_footprint_pad,
    )

    fpid = parse_footprint_id(fp)
    if fpid is None:
        return
    pads = footprint_pad_numbers_from_library(fpid[0], fpid[1])
    if not pads:
        return
    bad: list[str] = []
    for p in pinout:
        if not isinstance(p, dict):
            continue
        num = str(p.get("num") or "")
        name = str(p.get("name") or "")
        if not num and not name:
            continue
        if not _pin_covers_footprint_pad(num, name, pads):
            bad.append(f"{num or '?'}/{name or '?'}")
    if bad:
        msg = (
            f"Enriched pinout for {gn} may not match footprint {fp} pads (examples: "
            f"{', '.join(bad[:12])}). Align pin num/name with the `.kicad_mod` pad list."
        )
        if enrich_strict_pinout_pads():
            raise RuntimeError(msg)
        logger.warning(msg)


def _pinout_legacy_name_diversity(pinout: Any) -> bool:
    """True when some pin has a human-readable name that differs from its number (datasheet-style)."""
    if not isinstance(pinout, list) or not pinout:
        return False
    for p in pinout:
        if not isinstance(p, dict):
            continue
        num = str(p.get("num") or "").strip()
        name = str(p.get("name") or "").strip()
        if not num:
            continue
        if name and name != num:
            return True
    return False


def _pinout_numeric_fallback(pinout: Any) -> bool:
    """Conservative OK when footprint pads are unknown: distinct non-empty numeric-ish nums only."""
    if not isinstance(pinout, list) or not pinout:
        return False
    nums: list[str] = []
    for p in pinout:
        if not isinstance(p, dict):
            continue
        num = str(p.get("num") or "").strip()
        if not num:
            return False
        nums.append(num)
    if len(nums) != len(set(nums)):
        return False
    if not (1 <= len(nums) <= 256):
        return False
    return True


def _pinout_footprint_aligned(pinout: Any, row: dict[str, Any]) -> bool:
    """True if every pinout entry with num/name resolves to a pad on ``row['kicad_footprint']``."""
    if not isinstance(pinout, list) or not pinout or not row:
        return False
    pads = _footprint_pad_set_for_row(row)
    if not pads:
        return False
    from openhac.compiler.pcb_placement import _pin_covers_footprint_pad

    for p in pinout:
        if not isinstance(p, dict):
            continue
        num = str(p.get("num") or "")
        name = str(p.get("name") or "")
        if not num and not name:
            continue
        if not _pin_covers_footprint_pad(num, name, pads):
            return False
    return True


def _pinout_is_sufficient(pinout: Any, catalog_row: dict[str, Any] | None = None) -> bool:
    """Pinout is complete enough to skip re-enrichment: legacy diversity, footprint parity, or numeric fallback."""
    if not isinstance(pinout, list) or not pinout:
        return False
    if _pinout_legacy_name_diversity(pinout):
        return True
    if catalog_row is not None and _pinout_footprint_aligned(pinout, catalog_row):
        return True
    if catalog_row is None or not _footprint_pad_set_for_row(catalog_row):
        return _pinout_numeric_fallback(pinout)
    return False


def _pinout_is_meaningful(pinout: Any) -> bool:
    """Backward-compatible alias: legacy name/num diversity only (vendor placeholder heuristic)."""
    return _pinout_legacy_name_diversity(pinout)


def _pinout_list_from_raw(raw: Any) -> list | None:
    if raw is None:
        return None
    if isinstance(raw, list):
        return raw if raw else None
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return None
        try:
            data = json.loads(s)
        except Exception:
            return None
        return data if isinstance(data, list) else None
    return None


def needs_pinout_database_enrich(
    pinout_json_raw: Any,
    *,
    catalog_row: dict[str, Any] | None = None,
) -> bool:
    """True when the catalog row should still receive pinout enrichment (missing or not pad-safe)."""
    po = _pinout_list_from_raw(pinout_json_raw)
    if po is None:
        return True
    return not _pinout_is_sufficient(po, catalog_row)


def _footprint_pad_set_for_row(row: dict[str, Any]) -> set[str] | None:
    fp = str(row.get("kicad_footprint") or "").strip()
    if not fp:
        return None
    from openhac.compiler.pcb_placement import footprint_pad_numbers_from_library, parse_footprint_id

    fpid = parse_footprint_id(fp)
    if fpid is None:
        return None
    pads = footprint_pad_numbers_from_library(fpid[0], fpid[1])
    return pads if pads else None


def _filter_pinout_to_footprint_pads(pinout: list[dict], pads: set[str] | None) -> list[dict]:
    if not pads:
        return pinout
    from openhac.compiler.pcb_placement import _pin_covers_footprint_pad

    out: list[dict] = []
    for p in pinout:
        num = str(p.get("num") or "")
        name = str(p.get("name") or "")
        if _pin_covers_footprint_pad(num, name, pads):
            out.append(p)
    return out if out else pinout


def _local_pinout_for_row(row: dict[str, Any]) -> list[dict] | None:
    ks = str(row.get("kicad_symbol") or "").strip()
    if not ks:
        return None
    from openhac.database.pin_policy import kicad_symbol_is_pin_name_oracle

    if not kicad_symbol_is_pin_name_oracle(ks):
        return None
    from openhac.compiler.kicad_sym_pinpos import pinout_from_kicad_symbol_id

    raw = pinout_from_kicad_symbol_id(ks)
    if not raw:
        return None
    pads = _footprint_pad_set_for_row(row)
    return _filter_pinout_to_footprint_pads(raw, pads)


def _best_enrich_pin_name(num: str, loc_name: str, ven_name: str) -> str:
    if ven_name and ven_name not in (num, "~") and ven_name != str(num):
        return ven_name
    if loc_name and loc_name not in ("", "~"):
        return loc_name
    return ven_name or loc_name or num


def _merge_pinouts_local_vendor_by_local_nums(
    local: list[dict],
    vendor: list[dict] | None,
    *,
    local_nums_only: bool = False,
) -> list[dict]:
    """Build merged pinout: pad numbers from *local* KiCad symbol order; names/types filled from vendor.

    When *local_nums_only* is True (pad-aligned KiCad local pinout), do not append extra vendor-only
    ``num`` keys (e.g. signal names that are not footprint pads).
    """
    v_by_num: dict[str, dict] = {}
    for p in vendor or []:
        if isinstance(p, dict) and str(p.get("num") or "").strip():
            v_by_num[str(p["num"]).strip()] = p
    order: list[str] = []
    seen: set[str] = set()
    for p in local or []:
        if not isinstance(p, dict):
            continue
        n = str(p.get("num") or "").strip()
        if not n or n in seen:
            continue
        seen.add(n)
        order.append(n)
    if not local_nums_only:
        for p in vendor or []:
            if not isinstance(p, dict):
                continue
            n = str(p.get("num") or "").strip()
            if n and n not in seen:
                seen.add(n)
                order.append(n)

    merged: list[dict] = []
    for n in order:
        loc = next(
            (x for x in (local or []) if isinstance(x, dict) and str(x.get("num") or "").strip() == n),
            None,
        )
        ven = v_by_num.get(n)
        loc_name = str((loc or {}).get("name") or "").strip() if loc else ""
        ven_name = str((ven or {}).get("name") or "").strip() if ven else ""
        name = _best_enrich_pin_name(n, loc_name, ven_name)
        typ = (loc or {}).get("type") if loc else None
        if typ is None and ven:
            typ = ven.get("type")
        if typ is None:
            typ = "bidirectional"
        merged.append({"num": n, "name": name, "type": typ})
    return merged


def _merge_kicad_and_vendor_pinouts(
    local: list[dict] | None,
    vendor: list[dict] | None,
    *,
    preference: str = "auto",
    row: dict[str, Any] | None = None,
) -> list[dict] | None:
    pref = (preference or "auto").strip().lower()
    pads = _footprint_pad_set_for_row(row) if row else None
    pads_known = bool(pads)
    loc_aligned = bool(local) and row is not None and _pinout_footprint_aligned(local, row)
    ven_aligned = bool(vendor) and row is not None and _pinout_footprint_aligned(vendor, row)

    def _lm_eff() -> bool:
        if not local:
            return False
        return bool(
            loc_aligned
            or _pinout_legacy_name_diversity(local)
            or (not pads_known and _pinout_numeric_fallback(local))
        )

    def _vm_eff() -> bool:
        if not vendor:
            return False
        if pads_known:
            return ven_aligned
        return _pinout_legacy_name_diversity(vendor) or _pinout_numeric_fallback(vendor)

    if pref == "vendor":
        if vendor and _vm_eff():
            return list(vendor)
        return list(local) if local else None
    if pref == "kicad_symbol":
        if local and _lm_eff():
            return list(local)
        return list(vendor) if vendor else None

    if not local and not vendor:
        return None

    if local and vendor and loc_aligned and pref == "auto":
        return _merge_pinouts_local_vendor_by_local_nums(local, vendor, local_nums_only=True)

    le, ve = _lm_eff(), _vm_eff()

    if not vendor:
        return list(local) if le else None

    if not local:
        if ve:
            return list(vendor)
        if vendor and pads_known and not ven_aligned:
            if enrich_strict_pinout_pads():
                return None
            return list(vendor)
        if vendor:
            return list(vendor)
        return None

    if not ve and le:
        return list(local)
    if not le and ve:
        return list(vendor)
    if not le and not ve:
        cand = vendor or local
        if cand and pads_known and not _pinout_footprint_aligned(cand, row):
            if enrich_strict_pinout_pads():
                return None
        return list(cand) if cand else None

    return _merge_pinouts_local_vendor_by_local_nums(local, vendor, local_nums_only=False)


def _persist_pinout_only(
    db,
    generic_name: str,
    pinout: list[dict],
    *,
    pinout_source: str,
) -> bool:
    try:
        return bool(
            db.update_component_fields(
                generic_name,
                {
                    "pinout_json": json.dumps(pinout),
                    "pinout_source": pinout_source,
                    "catalog_tier": "verified",
                    "enriched_at_utc": datetime.now(timezone.utc).isoformat(),
                },
            )
        )
    except Exception:
        return False


def enrich_component_in_db(
    *,
    db,
    generic_name: str,
    mpn: str | None = None,
    jlcpcb_sku: str | None = None,
    preferred_vendor: str = "auto",
    allow_network: bool | None = None,
) -> EnrichResult:
    """Enrich a DB row using vendor APIs and/or the catalogued ``kicad_symbol`` library pinout.

    KiCad symbol pinouts are merged with vendor pinouts (see ``OPENHAC_ENRICH_PINOUT_PREFERENCE``)
    and can be persisted offline when the footprint/symbol resolve on disk.
    """
    if allow_network is None:
        allow_network = network_allowed()

    gn = str(generic_name or "").strip()
    if not gn:
        return EnrichResult(attempted=False, updated=False, vendor=None, reason="missing_generic_name")

    try:
        row = db.get_component(gn)
    except Exception:
        row = None
    if not row:
        return EnrichResult(attempted=False, updated=False, vendor=None, reason="not_in_db")

    # [Professional Grade] Force-Apply Asset Overrides (Always runs to fix stale/bad DB data)
    mpn_eff = str(mpn or (row.get("mpn") if row else "") or "").strip() or None
    sku_eff = str(jlcpcb_sku or (row.get("supplier_sku") if row else "") or "").strip() or None
    sku_to_gen = (sku_eff if (sku_eff and sku_eff.upper().startswith("C") and sku_eff[1:].isdigit()) else None) or sku_eff or mpn_eff
    
    override = _get_override_asset(sku_to_gen) or _get_override_asset(gn)
    if override and override.get("sku"):
        sku_to_gen = override["sku"]
        
    has_override = bool(override)
    if override:
        logger.info("Force-applying high-fidelity override for %s", gn)
        row_update = {}
        if override.get("footprint"):
            row_update["kicad_footprint"] = override["footprint"]
            row_update["footprint_resolved"] = 1
        
        # [Professional Grade] Inject Semantic Pinouts for Compute Modules
        if "Raspberry_Pi_5" in gn:
            po = SEMANTIC_PINOUTS.get("Raspberry_Pi_5")
            if po:
                row_update["pinout_json"] = json.dumps(po)
                row_update["pinout_source"] = "Professional_Library"
        elif "Teensy_4.1" in gn:
            po = SEMANTIC_PINOUTS.get("Teensy_4.1")
            if po:
                row_update["pinout_json"] = json.dumps(po)
                row_update["pinout_source"] = "Professional_Library"

        m3d_url = override.get("model_3d")
        if m3d_url:
            try:
                import urllib.request
                dest_dir = Path(os.path.expanduser("~/.kiro/openhac/overrides.3dshapes"))
                dest_dir.mkdir(parents=True, exist_ok=True)
                # Use SKU or Generic Name to ensure a stable file path for the high-fidelity model
                safe_name = "".join(c if c.isalnum() else "_" for c in (sku_to_gen or gn))
                dest_path = dest_dir / f"{safe_name}_{Path(m3d_url).name}"
                logger.info("Override: Downloading 3D model for %s from %s -> %s", gn, m3d_url, dest_path)
                if not dest_path.exists():
                    urllib.request.urlretrieve(m3d_url, str(dest_path))
                row_update["model_3d_local"] = str(dest_path)
            except Exception as e:
                logger.error("Override: Failed to download 3D model for %s: %s", gn, e)
        if row_update:
            logger.info("Override Shield: Updating DB integrity fields for %s: %s", gn, list(row_update.keys()))
            db.update_component_fields(gn, row_update)
            row = db.get_component(gn) # Refresh local row state

    existing_po = _pinout_list_from_raw(row.get("pinout_json"))
    row_d = dict(row)

    if not allow_network:
        pref = (os.environ.get("OPENHAC_ENRICH_PINOUT_PREFERENCE") or "auto").strip().lower()
        local_po_offline = _local_pinout_for_row(row_d)
        if (
            local_po_offline
            and pref != "vendor"
            and _pinout_is_sufficient(local_po_offline, row_d)
            and _persist_pinout_only(db, gn, local_po_offline, pinout_source="kicad_symbol")
        ):
            return EnrichResult(attempted=False, updated=True, vendor=None, reason="kicad_symbol")
        if _pinout_is_sufficient(existing_po, row_d):
            return EnrichResult(attempted=False, updated=False, vendor=None, reason="already_has_pinout")
        return EnrichResult(attempted=False, updated=False, vendor=None, reason="network_disallowed")

    # Step: EasyEDA Footprint & 3D Model Generation (PCB-008)
    # Moved before pinout check to ensure 3D models are generated even if pinout is sufficient.
    try:
        from openhac.database.sync_jlc import _verify_and_resolve_kicad_footprint
        chosen = str(row.get("kicad_footprint") or "").strip()
        resolved = row.get("footprint_resolved")
        current_m3d = row.get("model_3d_local")
        m3d_exists = current_m3d and (
            os.path.isfile(current_m3d) or str(current_m3d).startswith("${KICAD")
        )

        from openhac.database.kicad_3d import library_3d_fields_for_row, should_skip_easyeda_3d

        if should_skip_easyeda_3d(row):
            lib3d = library_3d_fields_for_row(row)
            if lib3d and not (row.get("model_3d_source") == "kicad_lib"):
                try:
                    db.update_component_fields(gn, lib3d)
                    row = db.get_component(gn) or row
                except Exception:
                    pass
            m3d_exists = True

        # [Professional Grade] Always attempt to fetch 3D model from API if missing, even if we have a footprint override
        if not m3d_exists or not resolved or "easyeda_generated" not in str(chosen):
            mpn_eff = str(mpn or row.get("mpn") or "").strip() or None
            sku_eff = str(jlcpcb_sku or row.get("supplier_sku") or "").strip() or None
            jlc_eff = sku_eff if (sku_eff and sku_eff.upper().startswith("C") and sku_eff[1:].isdigit()) else None
            sku_to_gen = jlc_eff or sku_eff or mpn_eff
            
            # Use the SKU from the override if it was mapped
            if override and override.get("sku"):
                sku_to_gen = override["sku"]

            if sku_to_gen and str(sku_to_gen).startswith("C") and not m3d_exists:
                from openhac.database.easyeda_integration import generate_footprint_from_lcsc
                new_fp, model_path = generate_footprint_from_lcsc(sku_to_gen)
                if new_fp:
                    logger.info("Generated EasyEDA assets for %s: %s (3D: %s)", gn, new_fp, model_path or "no")
                    row_update_jlc = {}
                    # Only override the footprint if we don't have a manual override
                    if not has_override:
                        row_update_jlc["kicad_footprint"] = new_fp
                        row_update_jlc["footprint_resolved"] = 1
                    
                    if model_path:
                        row_update_jlc["model_3d_local"] = str(model_path)
                        try:
                            from openhac.database.catalog_coverage import sha256_file

                            if os.path.isfile(str(model_path)):
                                row_update_jlc["model_3d_sha256"] = sha256_file(model_path)
                                row_update_jlc["model_3d_source"] = "easyeda"
                                row_update_jlc["model_3d_license"] = "EasyEDA"
                        except Exception:
                            row_update_jlc["model_3d_source"] = "easyeda"
                    
                    if row_update_jlc:
                        db.update_component_fields(gn, row_update_jlc)
                        row = db.get_component(gn) # Refresh local row state
            
            # Refresh row_d so pinout check uses updated data if needed
            row_d = dict(db.get_component(gn))
    except Exception as e:
        logger.debug("EasyEDA pre-enrichment skipped for %s: %s", gn, e)

    # JLC2KiCAD Symbol Generation (Professional Symbol Assets)
    # Moved outside footprint block to ensure all LCSC parts get symbols
    try:
        mpn_eff = str(mpn or row_d.get("mpn") or "").strip() or None
        sku_eff = str(jlcpcb_sku or row_d.get("supplier_sku") or "").strip() or None
        jlc_eff = sku_eff if (sku_eff and sku_eff.upper().startswith("C") and sku_eff[1:].isdigit()) else None
        sku_to_gen = jlc_eff or sku_eff or mpn_eff
        
        if sku_to_gen and sku_to_gen.startswith("C"):
            has_sym = row_d.get("kicad_symbol")
            if not has_sym or "jlc2kicad" not in str(has_sym):
                from openhac.database.jlc2kicad_integration import generate_symbol_from_lcsc
                new_sym, new_m3d = generate_symbol_from_lcsc(sku_to_gen)
                if new_sym:
                    logger.info("Generated JLC2KiCAD symbol for %s: %s", gn, new_sym)
                    db.update_component_fields(gn, {"kicad_symbol": new_sym})
                    if new_m3d and os.path.isfile(new_m3d):
                        db.update_component_fields(gn, {"model_3d_local": new_m3d})
                        logger.info("Updated 3D model path (JLC2KiCAD) for %s: %s", gn, new_m3d)
                    # Refresh row_d for final pinout checks
                    row_d = dict(db.get_component(gn))
    except Exception as sym_e:
        logger.info("JLC2KiCAD symbol generation failed for %s: %s", gn, sym_e)

    # Note: Symbol and Footprint/3D generation (lines 457-510) already ran above.
    # We only skip the expensive vendor API lookups if pinout is already sufficient.
    if _pinout_is_sufficient(existing_po, row_d) and row_d.get("model_3d_local"):
        return EnrichResult(attempted=False, updated=False, vendor=None, reason="already_has_pinout_and_3d")

    pref = (os.environ.get("OPENHAC_ENRICH_PINOUT_PREFERENCE") or "auto").strip().lower()
    local_po = _local_pinout_for_row(row_d)

    def _persist_kicad_symbol_pinout(*, attempted: bool) -> EnrichResult | None:
        if not local_po or pref == "vendor":
            return None
        if not _pinout_is_sufficient(local_po, row_d):
            return None
        if not _persist_pinout_only(db, gn, local_po, pinout_source="kicad_symbol"):
            return None
        try:
            _warn_if_pinout_mismatches_footprint_pads(db, gn)
        except Exception:
            pass
        return EnrichResult(attempted=attempted, updated=True, vendor=None, reason="kicad_symbol")

    mpn_eff = str(mpn or row.get("mpn") or "").strip() or None
    sku_eff = str(jlcpcb_sku or row.get("supplier_sku") or "").strip() or None
    jlc_eff = sku_eff if (sku_eff and sku_eff.upper().startswith("C") and sku_eff[1:].isdigit()) else None

    if not mpn_eff and not jlc_eff:
        r = _persist_kicad_symbol_pinout(attempted=False)
        if r is not None:
            return r
        return EnrichResult(attempted=False, updated=False, vendor=None, reason="no_mpn_or_sku")

    if not allow_network:
        r = _persist_kicad_symbol_pinout(attempted=False)
        if r is not None:
            return r
        return EnrichResult(attempted=False, updated=False, vendor=None, reason="network_disallowed")

    global _VENDOR_API_WARNED
    try:
        from openhac.database.vendor_apis import lookup_part_live, vendor_apis_configured
    except Exception:
        lookup_part_live = None  # type: ignore[assignment]
        vendor_apis_configured = lambda: False  # type: ignore[misc, assignment]

    if not vendor_apis_configured():
        if not _VENDOR_API_WARNED:
            logger.warning(
                "Part enrichment needs vendor API credentials (e.g. DIGIKEY_CLIENT_ID + DIGIKEY_CLIENT_SECRET, "
                "MOUSER_API_KEY, TME_API_TOKEN + TME_API_SECRET, or JLCPCB_API_KEY). "
                "Without them, only KiCad symbol pinout enrichment runs when ``kicad_symbol`` resolves."
            )
            _VENDOR_API_WARNED = True
        r = _persist_kicad_symbol_pinout(attempted=False)
        if r is not None:
            return r
        return EnrichResult(attempted=False, updated=False, vendor=None, reason="no_vendor_api_keys")

    part = None
    for q in _search_strings_for_enrich(gn, mpn_eff):
        try:
            part = lookup_part_live(
                q,
                preferred_vendor=str(preferred_vendor or "auto"),
                jlcpcb_sku=jlc_eff,
            )
        except Exception as e:
            r = _persist_kicad_symbol_pinout(attempted=True)
            if r is not None:
                return r
            return EnrichResult(attempted=True, updated=False, vendor=None, reason=f"lookup_failed:{e}")
        if part is not None:
            break

    if part is None:
        r = _persist_kicad_symbol_pinout(attempted=True)
        if r is not None:
            return r
        return EnrichResult(attempted=True, updated=False, vendor=None, reason="not_found")

    vendor_po_raw = getattr(part, "pinout", None)
    had_usable_vendor_pinout = _pinout_is_sufficient(vendor_po_raw, row_d)
    pinout = getattr(part, "pinout", None)
    if pinout and not _pinout_is_sufficient(pinout, row_d):
        try:
            logger.info("Ignoring unusable pinout for %s from %s.", gn, getattr(part, "source_vendor", None))
        except Exception:
            pass
        try:
            part.pinout = None  # type: ignore[attr-defined]
        except Exception:
            pass

    vendor_po = getattr(part, "pinout", None)
    merged = _merge_kicad_and_vendor_pinouts(local_po, vendor_po, preference=pref, row=row_d)
    if merged:
        part.pinout = merged  # type: ignore[attr-defined]
    elif local_po and _pinout_footprint_aligned(local_po, row_d):
        part.pinout = list(local_po)  # type: ignore[attr-defined]
    else:
        try:
            part.pinout = None  # type: ignore[attr-defined]
        except Exception:
            pass

    if part.pinout:
        ven_tag = str(getattr(part, "source_vendor", None) or "").strip()
        if local_po and _pinout_is_sufficient(local_po, row_d):
            if had_usable_vendor_pinout and ven_tag:
                try:
                    setattr(part, "source_vendor", f"kicad_symbol+{ven_tag}")  # type: ignore[misc]
                except Exception:
                    pass
            elif not had_usable_vendor_pinout:
                try:
                    setattr(part, "source_vendor", "kicad_symbol")  # type: ignore[misc]
                except Exception:
                    pass

    # Best-effort: verify/resolve footprint if present and unresolved.
    try:
        from openhac.database.sync_jlc import _verify_and_resolve_kicad_footprint  # type: ignore

        raw_fp = str(row.get("kicad_footprint") or "").strip()
        if raw_fp:
            chosen, verified, resolved, notes = _verify_and_resolve_kicad_footprint(raw_fp)
            # Persist resolver outputs regardless of pinout.
            try:
                db.update_component_fields(
                    gn,
                    {
                        "kicad_footprint": chosen,
                        "footprint_verified": int(bool(verified)) if verified is not None else None,
                        "footprint_resolved": resolved,
                        "footprint_notes": notes,
                    },
                )
            except Exception:
                pass
    except Exception:
        pass

    # Ensure provenance fields are populated even if vendor APIs don't provide them.
    try:
        if getattr(part, "last_updated", None) is None:
            part.last_updated = datetime.now(timezone.utc)  # type: ignore[attr-defined]
    except Exception:
        pass

    try:
        updated = bool(db.update_component_from_vendor(gn, part))
    except Exception as e:
        return EnrichResult(attempted=True, updated=False, vendor=getattr(part, "source_vendor", None), reason=f"db_update_failed:{e}")

    if updated:
        try:
            _warn_if_pinout_mismatches_footprint_pads(db, gn)
        except Exception:
            pass

    return EnrichResult(
        attempted=True,
        updated=updated,
        vendor=getattr(part, "source_vendor", None),
        reason="ok" if updated else "no_change",
    )


def list_missing_named_pinout_rows(db, *, limit: int = 0) -> list[dict[str, Any]]:
    """CAT-005: catalog rows lacking a named pin table (warehouse IC holes)."""
    from openhac.database.catalog_coverage import iter_component_rows
    from openhac.database.pin_policy import pinout_is_named

    out: list[dict[str, Any]] = []
    for row in iter_component_rows(db):
        if pinout_is_named(
            row.get("pinout_json"),
            category=row.get("category"),
            generic_name=row.get("generic_name"),
        ):
            continue
        rec = {"generic_name": row.get("generic_name")}
        if row.get("mpn"):
            rec["mpn"] = row["mpn"]
        if row.get("supplier_sku"):
            rec["supplier_sku"] = row["supplier_sku"]
        out.append(rec)
        if limit and len(out) >= int(limit):
            break
    return out


def enrich_missing_pinouts_from_db(
    db,
    *,
    vendor: str = "auto",
    limit: int = 0,
    quiet: bool = False,
) -> tuple[int, int]:
    """Walk warehouse pinout holes via existing vendor APIs. Honors ``network_allowed()``."""
    if not network_allowed():
        logger.error("CAT-005: network denied; refusing --missing-pinouts")
        return 0, 0
    targets = list_missing_named_pinout_rows(db, limit=limit)
    return batch_enrich_targets(targets, db=db, vendor=vendor, limit=limit, quiet=quiet)


def prefetch_3d_for_skus(
    skus: list[str],
    *,
    db=None,
) -> tuple[int, int]:
    """Download EasyEDA 3D into ``~/.kiro/openhac/`` (3D-003). Requires network."""
    if not network_allowed():
        raise RuntimeError("3D-003: prefetch-3d requires network (OPENHAC_NO_NETWORK / fabrication denied)")
    from openhac.database.easyeda_integration import generate_footprint_from_lcsc
    from openhac.database.catalog_coverage import sha256_file
    from openhac.database.kicad_3d import should_skip_easyeda_3d

    attempted = 0
    updated = 0
    for sku in skus:
        s = str(sku or "").strip()
        if not s.startswith("C"):
            continue
        attempted += 1
        row = None
        if db is not None:
            try:
                row = db.get_component_by_supplier_sku(s)
            except Exception:
                row = None
        if row and should_skip_easyeda_3d(row):
            continue
        fp, model_path = generate_footprint_from_lcsc(s)
        if not model_path:
            continue
        updated += 1
        if db is not None and row:
            fields = {
                "model_3d_local": str(model_path),
                "model_3d_source": "easyeda",
                "model_3d_license": "EasyEDA",
            }
            if os.path.isfile(str(model_path)):
                fields["model_3d_sha256"] = sha256_file(model_path)
            if fp:
                fields.setdefault("kicad_footprint", fp)
            try:
                db.update_component_fields(row["generic_name"], fields)
            except Exception:
                pass
    return attempted, updated


def prefetch_3d_from_board(board, *, db=None) -> tuple[int, int]:
    skus: list[str] = []
    seen: set[str] = set()
    try:
        modules = board._get_all_modules()
    except Exception:
        modules = getattr(board, "modules", []) or []
    for mod in modules:
        for comp in getattr(mod, "components", []) or []:
            sku = str(getattr(comp, "supplier_sku", "") or "")
            cd = getattr(comp, "_comp_data", None) or {}
            sku = sku or str(cd.get("supplier_sku") or "")
            if sku and sku not in seen:
                seen.add(sku)
                skus.append(sku)
    return prefetch_3d_for_skus(skus, db=db)


def fill_pin_names_from_kicad_symbol(row: dict[str, Any]) -> list[dict] | None:
    """CAT-013: fill pin names from a real KiCad lib id. No HTTP."""
    return _local_pinout_for_row(row)


def discover_enrich_targets_from_board(board: Any) -> list[dict[str, Any]]:
    """Build enrich targets from a loaded :class:`~openhac.core.board.Board` plus the SQLite catalog.

    Walks every component instance (unique ``generic_name``). For each part whose cached/DB row
    still needs a *meaningful* ``pinout_json`` (see :func:`needs_pinout_database_enrich`), returns
    a dict suitable for :func:`batch_enrich_targets`.

    Parts with no DB row still get ``{"generic_name": ...}`` so :func:`enrich_component_in_db` can
    report ``not_in_db`` (use ``--sync-jlc-before`` or a seed file to populate the catalog first).
    """
    try:
        modules = board._get_all_modules()
    except Exception:
        modules = getattr(board, "modules", []) or []
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for mod in modules:
        for comp in getattr(mod, "components", []) or []:
            gn = str(getattr(comp, "generic_name", "") or "").strip()
            if not gn or gn in seen:
                continue
            seen.add(gn)
            try:
                cd = getattr(comp, "_comp_data", {}) or {}
            except Exception:
                cd = {}
            row = None
            try:
                row = comp.db.get_component(gn)  # type: ignore[attr-defined]
            except Exception:
                row = None
            row_d = dict(row) if row else None
            instance_po = cd.get("pinout_json")
            if instance_po is None and row_d is not None:
                instance_po = row_d.get("pinout_json")
            needs_pinout = needs_pinout_database_enrich(instance_po, catalog_row=row_d)
            needs_3d = False
            if row_d:
                sku = str(row_d.get("supplier_sku") or "").strip()
                has_lcsc = sku.upper().startswith("C") and sku[1:].isdigit()
                has_3d = bool(
                    row_d.get("model_3d_local")
                    and os.path.isfile(str(row_d.get("model_3d_local")))
                )
                needs_3d = has_lcsc and not has_3d

            if not needs_pinout and not needs_3d:
                continue
                
            rec: dict[str, Any] = {"generic_name": gn}
            if row_d:
                mpn = row_d.get("mpn")
                if mpn:
                    rec["mpn"] = mpn
                sku = row_d.get("supplier_sku")
                if sku:
                    rec["supplier_sku"] = sku
            out.append(rec)
    return out


def parse_enrich_targets_from_json(raw: Any) -> list[dict[str, Any]]:
    """Parse the JSON shape accepted by ``openhac database enrich --skus-file``."""
    targets: list[dict[str, Any]] = []
    if isinstance(raw, list):
        for rec in raw:
            if isinstance(rec, dict):
                targets.append(rec)
            elif isinstance(rec, (list, tuple)) and len(rec) >= 1:
                targets.append({"generic_name": str(rec[0])})
    elif isinstance(raw, dict):
        items = raw.get("parts") if isinstance(raw.get("parts"), list) else []
        for rec in items:
            if isinstance(rec, dict):
                targets.append(rec)
    return targets


def batch_enrich_targets(
    targets: list[dict[str, Any]],
    *,
    db,
    vendor: str = "auto",
    limit: int = 0,
    quiet: bool = False,
) -> tuple[int, int]:
    """Run :func:`enrich_component_in_db` for each record. Returns (attempted, updated)."""
    attempted = 0
    updated = 0
    for rec in targets:
        if limit and attempted >= limit:
            break
        gn = str(rec.get("generic_name") or rec.get("name") or rec.get("lcsc") or "").strip()
        if not gn:
            continue
        mpn = rec.get("mpn")
        sku = rec.get("supplier_sku") or rec.get("sku") or rec.get("lcsc")
        res = enrich_component_in_db(db=db, generic_name=gn, mpn=mpn, jlcpcb_sku=sku, preferred_vendor=vendor)
        if res.attempted:
            attempted += 1
        if res.updated:
            updated += 1
        if not quiet:
            logger.info(
                "Enrich %s: attempted=%s updated=%s vendor=%s reason=%s",
                gn,
                res.attempted,
                res.updated,
                res.vendor,
                res.reason,
            )
    return attempted, updated


def batch_enrich_from_json_file(
    path: str | os.PathLike[str],
    *,
    db,
    vendor: str = "auto",
    limit: int = 0,
    quiet: bool = False,
) -> tuple[int, int]:
    """Parse JSON and run :func:`batch_enrich_targets`."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    targets = parse_enrich_targets_from_json(raw)
    return batch_enrich_targets(targets, db=db, vendor=vendor, limit=limit, quiet=quiet)

