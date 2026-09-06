"""JLCPCB-shaped BOM + CPL (MFG-010). Does not invent LCSC SKUs."""

from __future__ import annotations

import csv
import logging
import re
from pathlib import Path

from openhac.core.exceptions import JlcExportError

logger = logging.getLogger("openhac.export_jlc")

_LCSC_RE = re.compile(r"^C\d+$", re.IGNORECASE)

JLC_BOM_FIELDS = ("Comment", "Designator", "Footprint", "LCSC Part #")
JLC_CPL_FIELDS = ("Designator", "Mid X", "Mid Y", "Layer", "Rotation")


def is_lcsc_sku(sku: str | None) -> bool:
    s = str(sku or "").strip()
    return bool(_LCSC_RE.match(s))


def _read_csv_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fields = list(reader.fieldnames or [])
        rows = [{k: (v or "") for k, v in (row or {}).items()} for row in reader]
    return fields, rows


def _lcsc_from_row(row: dict[str, str]) -> str:
    for key in (
        "LCSC Part #",
        "LCSC",
        "Supplier_SKU",
        "supplier_sku",
        "LCSC Part",
        "lcsc",
    ):
        v = str(row.get(key) or "").strip()
        if is_lcsc_sku(v):
            return v
    return ""


def jlc_bom_rows_from_openhac(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for row in rows:
        dnp = str(row.get("DNP") or "").strip().lower()
        comment = str(row.get("Comment") or row.get("Value") or "").strip()
        des = str(row.get("Designator") or row.get("Reference") or "").strip()
        if not des:
            continue
        fp = str(row.get("Footprint") or "").strip()
        lcsc = _lcsc_from_row(row)
        rec = {
            "Comment": comment,
            "Designator": des,
            "Footprint": fp,
            "LCSC Part #": lcsc,
            "DNP": str(row.get("DNP") or ""),
        }
        if dnp in ("yes", "true", "1"):
            rec["_dnp"] = "Yes"
        out.append(rec)
    return out


def write_jlc_bom(rows: list[dict[str, str]], dest: Path, *, strict: bool = False) -> Path:
    missing = [r["Designator"] for r in rows if not is_lcsc_sku(r.get("LCSC Part #")) and str(r.get("_dnp") or "").lower() != "yes"]
    if strict and missing:
        raise JlcExportError(
            "MFG-010: refusing JLC BOM with missing LCSC SKU (will not invent C-codes): "
            + ", ".join(missing)
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(JLC_BOM_FIELDS), lineterminator="\n", extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in JLC_BOM_FIELDS})
    logger.info("Wrote JLC BOM %s (%s lines)", dest, len(rows))
    return dest


def _pos_layer(side: str) -> str:
    s = str(side or "").strip().lower()
    if s in ("bottom", "b", "back"):
        return "bottom"
    return "top"


def cpl_rows_from_kicad_pos(path: Path, *, default_side: str = "top") -> list[dict[str, str]]:
    _fields, rows = _read_csv_rows(path)
    out: list[dict[str, str]] = []
    for row in rows:
        des = str(row.get("Designator") or row.get("Ref") or row.get("Reference") or "").strip()
        if not des:
            continue
        x = str(row.get("Mid X") or row.get("PosX") or row.get("X") or "").strip()
        y = str(row.get("Mid Y") or row.get("PosY") or row.get("Y") or "").strip()
        rot = str(row.get("Rotation") or row.get("Rot") or "0").strip() or "0"
        side = str(row.get("Layer") or row.get("Side") or default_side)
        out.append(
            {
                "Designator": des,
                "Mid X": x,
                "Mid Y": y,
                "Layer": _pos_layer(side),
                "Rotation": rot,
            }
        )
    return out


def write_jlc_cpl(rows: list[dict[str, str]], dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(JLC_CPL_FIELDS), lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in JLC_CPL_FIELDS})
    logger.info("Wrote JLC CPL %s (%s lines)", dest, len(rows))
    return dest


def export_jlc_pack(
    source: str | Path,
    output_dir: str | Path,
    *,
    strict: bool = True,
    bom_csv: str | Path | None = None,
) -> dict[str, Path]:
    """Write JLC BOM (+ CPL when pos/PCB siblings exist) into *output_dir*."""
    src = Path(source)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}

    bom_path = Path(bom_csv) if bom_csv else None
    pcb = src if src.suffix.lower() == ".kicad_pcb" else None
    if bom_path is None:
        if src.suffix.lower() == ".csv":
            bom_path = src
        elif pcb is not None:
            sib = pcb.with_suffix(".csv")
            if sib.is_file():
                bom_path = sib
    if bom_path is None or not bom_path.is_file():
        raise JlcExportError(f"MFG-010: no OpenHaC BOM CSV next to {src} (will not invent SKUs)")

    _fields, rows = _read_csv_rows(bom_path)
    jlc_rows = jlc_bom_rows_from_openhac(rows)
    bom_out = out / f"{bom_path.stem}_jlc_bom.csv"
    write_jlc_bom(jlc_rows, bom_out, strict=strict)
    written["bom"] = bom_out

    cpl_rows: list[dict[str, str]] = []
    search_dir = pcb.parent if pcb is not None else bom_path.parent
    stem = pcb.stem if pcb is not None else bom_path.stem
    for cand in (
        search_dir / f"{stem}-pos_front.csv",
        search_dir / f"{stem}-pos_back.csv",
        search_dir / f"{stem}_pos_front.csv",
        out / f"{stem}-pos_front.csv",
        out / f"{stem}-pos_back.csv",
    ):
        if cand.is_file():
            side = "bottom" if "back" in cand.name.lower() else "top"
            cpl_rows.extend(cpl_rows_from_kicad_pos(cand, default_side=side))
    if cpl_rows:
        cpl_out = out / f"{stem}_jlc_cpl.csv"
        write_jlc_cpl(cpl_rows, cpl_out)
        written["cpl"] = cpl_out
    return written
