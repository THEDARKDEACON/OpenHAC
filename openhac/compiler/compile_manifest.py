"""Write a JSON manifest after a successful ``Board.compile()`` (STR-002)."""

from __future__ import annotations

import csv
import hashlib
import json
import logging
import os
import re
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from openhac.compiler.compile_pipeline import COMPILE_PIPELINE_PHASE_NAMES
from openhac.compiler.netlist_gen import BOM_PROFILE_PROD_OMITTED_COLUMNS
from openhac.compiler.release_bundle import _RELEASE_SUFFIXES
from openhac.compiler.rule_check import jlc_class_line_counts_from_circuit
from openhac.version_info import get_version

logger = logging.getLogger("openhac.manifest")


def _logical_modules_manifest(board) -> list[dict]:
    """Top-level OpenHaC modules → SKiDL refs for SCH-002 hierarchy handoff."""
    from openhac.core.base import Module

    out: list[dict] = []
    for mod in getattr(board, "modules", None) or []:
        refs: set[str] = set()

        def walk(m):
            for c in getattr(m, "components", None) or []:
                if isinstance(c, Module):
                    walk(c)
                else:
                    p = getattr(c, "part", None)
                    if p is not None:
                        refs.add(str(getattr(p, "ref", "?")))

        walk(mod)
        out.append({"name": str(getattr(mod, "name", "?")), "references": sorted(refs)})
    return out


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def patch_manifest_release_zip_sha256(
    base: Path,
    project_name: str,
    zip_path: str | os.PathLike[str],
    *,
    write_sha256_sidecar: bool = False,
) -> None:
    """Record the SHA256 of the **first-pass** release zip in the manifest, then refresh the sidecar.

    A second ``zip_project_outputs`` pass should follow so the bundle on disk includes this manifest.
    The digest is intentionally **not** the hash of that final zip (manifest self-reference).
    """
    zp = Path(zip_path).resolve()
    if not zp.is_file():
        return
    digest = _sha256_file(zp)
    mf = base / f"{project_name}.openhac-manifest.json"
    if not mf.is_file():
        return
    try:
        data = json.loads(mf.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return
    data["release_zip_sha256"] = digest
    text = json.dumps(data, indent=2, sort_keys=True)
    mf.write_text(text, encoding="utf-8")
    if write_sha256_sidecar:
        hx = hashlib.sha256(text.encode("utf-8")).hexdigest()
        mf.with_name(mf.name + ".sha256").write_text(hx + "\n", encoding="utf-8")


def _try_git_head(cwd: Path) -> str | None:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=8,
            cwd=cwd,
        )
        if r.returncode == 0:
            return r.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def _try_git_branch(cwd: Path) -> str | None:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=8,
            cwd=cwd,
        )
        if r.returncode == 0:
            b = r.stdout.strip()
            return b if b and b != "HEAD" else None
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def _try_git_describe(cwd: Path) -> str | None:
    """Human-readable ref from ``git describe --always --dirty`` when cwd is a git worktree (STR-002)."""
    try:
        r = subprocess.run(
            ["git", "describe", "--always", "--dirty"],
            capture_output=True,
            text=True,
            timeout=8,
            cwd=cwd,
        )
        if r.returncode == 0:
            d = (r.stdout or "").strip()
            return d or None
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def _try_kicad_cli_version() -> str | None:
    """Best-effort ``kicad-cli`` version string for release manifests (STR-002)."""
    try:
        r = subprocess.run(
            ["kicad-cli", "--version"],
            capture_output=True,
            text=True,
            timeout=6,
        )
        if r.returncode == 0:
            out = ((r.stdout or "") + (r.stderr or "")).strip()
            return out or None
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def _truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


_DETERMINISTIC_UTC_ISO = "1980-01-01T00:00:00+00:00"


def _generated_utc_iso() -> str:
    """Generated timestamp for manifests; can be fixed for golden CI runs."""
    if _truthy_env("OPENHAC_DETERMINISTIC_MANIFEST") or _truthy_env("OPENHAC_DETERMINISTIC"):
        return _DETERMINISTIC_UTC_ISO
    return datetime.now(timezone.utc).isoformat()


def _deterministic_manifest_enabled() -> bool:
    return _truthy_env("OPENHAC_DETERMINISTIC_MANIFEST") or _truthy_env("OPENHAC_DETERMINISTIC")


def _compile_env_flags() -> dict[str, bool]:
    """Snapshot of common OPENHAC_* toggles for audit (LIB-003 / SW-006)."""
    return {
        "openhac_deterministic": _truthy_env("OPENHAC_DETERMINISTIC"),
        "openhac_skip_layout": _truthy_env("OPENHAC_SKIP_LAYOUT"),
        "openhac_strict_jit": _truthy_env("OPENHAC_STRICT_JIT"),
        "openhac_strict_kicad": _truthy_env("OPENHAC_STRICT_KICAD"),
        "openhac_allow_risky_parts": _truthy_env("OPENHAC_ALLOW_RISKY_PARTS"),
        "openhac_require_verified_parts": _truthy_env("OPENHAC_REQUIRE_VERIFIED_PARTS"),
        "openhac_schematic_stub_only": _truthy_env("OPENHAC_SCHEMATIC_STUB_ONLY"),
        "openhac_deterministic_uuids": _truthy_env("OPENHAC_DETERMINISTIC_UUIDS"),
        "openhac_deterministic_schematic": _truthy_env("OPENHAC_DETERMINISTIC_SCHEMATIC"),
        "openhac_deterministic_manifest": _truthy_env("OPENHAC_DETERMINISTIC_MANIFEST"),
    }


def _fab_profile_bundle_path(profile_name: str) -> str | None:
    """Resolved resource path for ``openhac.fab_profiles/<name>.json`` (MFG-004)."""
    try:
        from importlib.resources import files

        root = files("openhac.fab_profiles")
        p = root / f"{profile_name}.json"
        if p.is_file():
            return str(p)
    except Exception:
        pass
    return None


def _fab_profile_bundle_names() -> list[str]:
    """Bundled ``*.json`` fab profile stems under ``openhac.fab_profiles`` (MFG-004 catalog)."""
    try:
        from importlib.resources import files

        root = files("openhac.fab_profiles")
        out: list[str] = []
        for p in root.iterdir():
            try:
                name = str(getattr(p, "name", "") or "")
            except Exception:
                continue
            if name.endswith(".json") and p.is_file():
                out.append(name[:-5])
        return sorted(out)
    except Exception:
        return []


def _spice_annotation_summary() -> dict:
    """Count BOM-visible SPICE fields on SKiDL parts (SIM-001 visibility)."""
    try:
        from openhac.circuit import get_default_circuit

        circuit = get_default_circuit()
    except Exception:
        return {}

    def _nz(part, key: str) -> bool:
        try:
            v = part.fields.get(key, "") if hasattr(part, "fields") else ""
        except Exception:
            return False
        return bool(str(v or "").strip())

    inc = sub = 0
    for part in getattr(circuit, "parts", []) or []:
        if _nz(part, "Spice_Include"):
            inc += 1
        if _nz(part, "Spice_Subckt"):
            sub += 1
    return {"parts_with_spice_include": inc, "parts_with_spice_subckt": sub}


def _diff_pairs_from_board(board) -> list[dict]:
    out: list[dict] = []
    for c in getattr(board, "constraints", ()) or ():
        if c.get("type") != "diff_pair":
            continue
        args = c.get("args") or ()
        if len(args) < 2:
            continue
        p_net, n_net = args[0], args[1]
        z0 = float(args[2]) if len(args) > 2 else 90.0
        out.append(
            {
                "p_net": str(getattr(p_net, "name", p_net)),
                "n_net": str(getattr(n_net, "name", n_net)),
                "target_z0_ohms": z0,
            }
        )
    return out


def _sanitize_kicad_netclass_label(s: str) -> str:
    """ASCII-ish token for suggested KiCad netclass names (PCB-007 handoff)."""
    t = re.sub(r"[^0-9A-Za-z]+", "_", str(s).strip())
    t = re.sub(r"_+", "_", t).strip("_")
    return (t[:48] if t else "NET") or "NET"


def _netclass_suggestions(board, diff_pairs: list[dict]) -> list[dict]:
    """Derive suggested KiCad netclass groupings from routing / SI intent (PCB-007)."""
    out: list[dict] = []
    for dp in diff_pairs:
        p = str(dp.get("p_net", "?"))
        n = str(dp.get("n_net", "?"))
        z0 = dp.get("target_z0_ohms", "")
        name = (
            f"OHAC_DP_{_sanitize_kicad_netclass_label(p)}_{_sanitize_kicad_netclass_label(n)}"
        )
        out.append(
            {
                "suggested_netclass": name,
                "nets": [p, n],
                "source": "diff_pair",
                "note": f"target Z0 ≈ {z0} Ω (intent only)",
            }
        )
    for g in getattr(board, "_length_match_groups", None) or []:
        gn = str(g.get("name", "group"))
        nets = list(g.get("nets") or [])
        name = f"OHAC_LM_{_sanitize_kicad_netclass_label(gn)}"
        out.append(
            {
                "suggested_netclass": name,
                "nets": nets,
                "source": "length_match",
                "note": None,
            }
        )
    for nn in getattr(board, "_no_autoroute_net_names", None) or []:
        ns = str(nn)
        name = f"OHAC_MANUAL_{_sanitize_kicad_netclass_label(ns)}"
        out.append(
            {
                "suggested_netclass": name,
                "nets": [ns],
                "source": "no_autoroute",
                "note": "manual route / skip autorouter",
            }
        )
    by_role: dict[str, list[str]] = {}
    for r in getattr(board, "_net_roles", None) or []:
        role = str(r.get("role", "")).strip()
        net = str(r.get("net", "")).strip()
        if not role or not net:
            continue
        by_role.setdefault(role, []).append(net)
    for role, nets in sorted(by_role.items()):
        name = f"OHAC_ROLE_{_sanitize_kicad_netclass_label(role)}"
        out.append(
            {
                "suggested_netclass": name,
                "nets": sorted(dict.fromkeys(nets)),
                "source": "net_role",
                "note": f"role={role!r}",
            }
        )
    return out


def _write_netclass_hint_md(base: Path, project_name: str, suggestions: list[dict]) -> None:
    """PCB-007: human-readable suggested KiCad netclass names (no .kicad_pro emission)."""
    if not suggestions:
        return
    out = base / f"{project_name}.openhac-netclass-hint.md"
    lines = [
        "# KiCad netclass handoff (PCB-007)",
        "",
        "OpenHaC does **not** write KiCad board or project files. Create netclasses in **Board Setup → "
        "Board Editor → Design Rules → Net classes**, then assign member nets.",
        "",
        "Suggested names below are derived from differential pairs, length-match groups, no-autoroute nets, "
        "and net roles recorded in this compile.",
        "",
    ]
    by_source: dict[str, list[dict]] = {}
    for s in suggestions:
        src = str(s.get("source") or "?")
        by_source.setdefault(src, []).append(s)
    order = ("diff_pair", "length_match", "no_autoroute", "net_role")
    titles = {
        "diff_pair": "Differential pairs (SIG-002)",
        "length_match": "Length-match groups (SIG-005)",
        "no_autoroute": "No-autoroute nets (PCB-007)",
        "net_role": "Net roles (SIG-006)",
    }
    for src in order:
        rows = by_source.pop(src, None)
        if not rows:
            continue
        lines.append(f"## {titles.get(src, src)}")
        lines.append("")
        for row in rows:
            sn = row.get("suggested_netclass", "?")
            nets = row.get("nets") or []
            note = row.get("note")
            nl = ", ".join(f"`{n}`" for n in nets)
            if note:
                lines.append(f"- **`{sn}`** — {nl} — _{note}_")
            else:
                lines.append(f"- **`{sn}`** — {nl}")
        lines.append("")
    for src, rows in sorted(by_source.items()):
        lines.append(f"## {src}")
        lines.append("")
        for row in rows:
            sn = row.get("suggested_netclass", "?")
            nets = row.get("nets") or []
            lines.append(f"- **`{sn}`** — {', '.join(f'`{n}`' for n in nets)}")
        lines.append("")
    out.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Wrote %s", out)


def _jlc_class_line_summary_from_circuit() -> dict:
    """Count BOM line items by JLC assembly class (LIB-005 manifest visibility)."""
    counts = jlc_class_line_counts_from_circuit()
    total = sum(counts.values())
    ext = counts.get("extended", 0)
    basic = counts.get("basic", 0)
    unset = counts.get("unset", 0)
    other = total - ext - basic - unset
    return {
        "extended_line_items": ext,
        "basic_line_items": basic,
        "unset_line_items": unset,
        "other_class_line_items": other,
        "total_line_items": total,
        "by_class": dict(sorted(counts.items())),
    }


def _write_mixed_signal_hint_md(base: Path, project_name: str, board) -> None:
    """SIG-006: human-readable net roles / merge hints for mixed-signal handoff."""
    roles = getattr(board, "_net_roles", None) or []
    merges = getattr(board, "_net_merge_hints", None) or []
    if not roles and not merges:
        return
    out = base / f"{project_name}.openhac-mixed-signal-hint.md"
    lines = [
        "# Mixed-signal / grounding handoff (SIG-006)",
        "",
        "OpenHaC records design intent only — implement star points, splits, and ferrite bridges in KiCad.",
        "",
    ]
    if roles:
        lines.append("## Net roles")
        lines.append("")
        for r in roles:
            lines.append(f"- **{r.get('net', '?')}** → `{r.get('role', '?')}`")
        lines.append("")
    if merges:
        lines.append("## Merge hints (star-point / ferrite)")
        lines.append("")
        for m in merges:
            lines.append(
                f"- `{m.get('net_a', '?')}` ↔ `{m.get('net_b', '?')}` via {m.get('via', '?')}"
            )
        lines.append("")
    out.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Wrote %s", out)


def _write_mixed_signal_constraints_json(base: Path, project_name: str, board) -> None:
    """SIG-006: standalone JSON for net roles / merge hints (CM or SI tooling)."""
    roles = list(getattr(board, "_net_roles", None) or [])
    merges = list(getattr(board, "_net_merge_hints", None) or [])
    if not roles and not merges:
        return
    payload = {
        "schema": "openhac.mixed_signal_handoff.v1",
        "net_roles": roles,
        "net_merge_hints": merges,
    }
    out = base / f"{project_name}.openhac-mixed-signal-constraints.json"
    out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    logger.info("Wrote %s", out)


def _write_bom_alternates_json(base: Path, project_name: str, board) -> None:
    """LIB-002: machine-readable alternate rows from DB per BOM generic (Value)."""
    from openhac.core.base import Component

    try:
        from openhac.circuit import get_default_circuit

        circuit = get_default_circuit()
    except Exception:
        return

    by_generic: dict[str, list[dict]] = {}
    seen: set[str] = set()
    for part in getattr(circuit, "parts", []) or []:
        try:
            fv = part.fields.get("Value", "") if hasattr(part, "fields") else ""
        except Exception:
            fv = ""
        g = str(fv or getattr(part, "value", "") or "").strip()
        if not g or g in seen:
            continue
        seen.add(g)
        rows = Component.db.list_part_alternates(g)
        if not rows:
            continue
        by_generic[g] = [
            {
                "rank": int(r.get("rank") or 0),
                "alternate_mpn": r.get("alternate_mpn"),
                "alternate_supplier_sku": r.get("alternate_supplier_sku"),
                "note": r.get("note"),
                "alternate_group_id": r.get("alternate_group_id"),
            }
            for r in rows
        ]

    if not by_generic:
        return
    payload = {"schema": "openhac.bom_alternates.v1", "by_generic": by_generic}
    out = base / f"{project_name}.openhac-bom-alternates.json"
    out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    logger.info("Wrote %s", out)


def _write_si_stackup_reminder_md(base: Path, project_name: str, board, diff_pairs: list[dict]) -> None:
    """SIG-001 / PCB-003: short checklist when stackup or SI-relevant metadata exists."""
    reasons: list[str] = []
    if int(getattr(board, "layers", 2) or 2) > 2:
        reasons.append(f"**PCB-003:** {int(board.layers)} copper layers — complete stackup in KiCad; see `docs/stackup_template.yaml`.")
    if getattr(board, "_stackup_references", None):
        reasons.append("**SIG-001 / PCB-004:** stackup reference paths are recorded — correlate Dk/Df with impedance targets.")
    if diff_pairs:
        reasons.append("**SIG-002:** differential pairs declared — set controlled impedance / spacing in KiCad netclasses.")
        for dp in diff_pairs:
            reasons.append(
                f"  - Pair `{dp.get('p_net', '?')}` / `{dp.get('n_net', '?')}` → target **Z0 ≈ {dp.get('target_z0_ohms', '?')} Ω** (intent only)."
            )
    if getattr(board, "_copper_pour_intents", None):
        reasons.append("**PCB-009:** copper pour intent recorded — add zones and return paths in the layout tool.")
    if not reasons:
        return
    out = base / f"{project_name}.openhac-si-stackup-reminder.md"
    lines = [
        "# Stackup & SI reminder (SIG-001 / PCB-003)",
        "",
        "OpenHaC records design intent only; verify against your fab and SI tools.",
        "",
    ]
    for r in reasons:
        lines.append(f"- {r}")
        lines.append("")
    out.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Wrote %s", out)


def _write_bom_expand_hint_md(base: Path, project_name: str, board) -> None:
    """LIB-002: human note for CM BOM expand / collapse using alternates JSON."""
    altp = base / f"{project_name}.openhac-bom-alternates.json"
    if not altp.is_file():
        return
    out = base / f"{project_name}.openhac-bom-expand-hint.md"
    lines = [
        "# BOM alternates — CM handoff (LIB-002)",
        "",
        f"Machine list: `{project_name}.openhac-bom-alternates.json` (schema `openhac.bom_alternates.v1`).",
        "",
        "## Suggested CM workflows",
        "",
        "1. **Single approved build** — keep one `generic_name` per BOM line; use alternates JSON only as reference for procurement substitutions.",
        "2. **Expanded pick list** — generate one row per ranked alternate with `alternate_group_id` / rank for the CM’s MRP system.",
        "3. **Avl-only** — filter JSON rows against your approved vendor list before merging into the master BOM.",
        "",
        "OpenHaC does not emit CM-specific CSV templates; map JSON fields to your house format.",
        "",
    ]
    out.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Wrote %s", out)


def _write_spice_model_hint_md(base: Path, project_name: str, board) -> None:
    """SIM-001: short SPICE / vendor model checklist when design uses SPICE fields."""
    s = _spice_annotation_summary()
    if not s or not (
        s.get("parts_with_spice_include", 0) or s.get("parts_with_spice_subckt", 0)
    ):
        return
    out = base / f"{project_name}.openhac-spice-model-hint.md"
    n_inc = int(s.get("parts_with_spice_include", 0) or 0)
    n_sub = int(s.get("parts_with_spice_subckt", 0) or 0)
    lines = [
        "# SPICE model handoff (SIM-001)",
        "",
        f"- Parts with **Spice_Include**: {n_inc}",
        f"- Parts with **Spice_Subckt**: {n_sub}",
        "",
        "Place vendor `.lib` / `.subckt` files on disk paths referenced by BOM fields; verify ngspice/Xyce compatibility.",
        "",
        "## Checklist",
        "",
        "- [ ] `.include` paths resolve from the directory you run the simulator in.",
        "- [ ] Subcircuit pin order matches the instantiated element line in the generated `.cir`.",
        "- [ ] Temperature / corner models aligned with REL-001 passive ratings if you rely on `.cir` sign-off.",
        "",
    ]
    out.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Wrote %s", out)


def _write_autoroute_policy_md(
    base: Path,
    project_name: str,
    board,
    diff_pairs: list[dict],
    *,
    auto_route: bool,
    skip_layout: bool,
) -> None:
    """PCB-007: document FreeRouting vs manual policy for this compile."""
    nar = list(getattr(board, "_no_autoroute_net_names", None) or [])
    # Skip file only for the vanilla case: layout ran, autoroute enabled, no special nets/pairs.
    if not skip_layout and not nar and not diff_pairs and auto_route:
        return
    out = base / f"{project_name}.openhac-autoroute-policy.md"
    lines = [
        "# Autoroute policy (PCB-007)",
        "",
        "OpenHaC FreeRouting is **routing assistance**, not high-speed or RF sign-off.",
        "",
    ]
    if skip_layout:
        lines.append("**Layout:** skipped (`OPENHAC_SKIP_LAYOUT` or headless build) — no placement/autoroute ran.")
        lines.append("")
    if nar:
        lines.append(f"**No-autoroute nets (manual in KiCad):** {', '.join(f'`{n}`' for n in nar)}")
        lines.append("")
    if diff_pairs:
        lines.append("**Differential pairs** are recorded for handoff — complete impedance-controlled routing in KiCad.")
        lines.append("")
    if not auto_route and not skip_layout:
        lines.append("**Auto-route:** disabled for this compile (`auto_route=False`).")
        lines.append("")
    elif not nar and auto_route and not skip_layout:
        lines.append("This build allowed auto-route on remaining nets (if layout ran).")
        lines.append("")
    out.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Wrote %s", out)


def _openhac_env_keys_present() -> list[str]:
    """STR-002: which OPENHAC_* environment keys are set (names only)."""
    return sorted(k for k in os.environ if k.startswith("OPENHAC_"))


def _jit_confidence_histogram_from_circuit() -> dict[str, int]:
    """LIB-003: count BOM lines by OpenHaC JIT confidence label."""
    try:
        from openhac.circuit import get_default_circuit

        circuit = get_default_circuit()
    except Exception:
        return {}
    hist: dict[str, int] = {}
    for part in getattr(circuit, "parts", []) or []:
        try:
            raw = part.fields.get("OpenHaC_JIT_Confidence", "") if hasattr(part, "fields") else ""
        except Exception:
            raw = ""
        lab = str(raw or "").strip().lower() or "unset"
        hist[lab] = hist.get(lab, 0) + 1
    return dict(sorted(hist.items()))


def _stackup_json_summaries(board) -> list[dict]:
    """PCB-004: lightweight parse of referenced ``*.json`` stackup files."""
    out: list[dict] = []
    for ref in getattr(board, "_stackup_references", None) or []:
        p = Path(str(ref.get("path", "")))
        if p.suffix.lower() != ".json" or not p.is_file():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            continue
        layers = data.get("layers")
        out.append(
            {
                "path": str(p.resolve()),
                "role": ref.get("role"),
                "vendor_profile": data.get("vendor_profile"),
                "total_thickness_mm": data.get("total_thickness_mm"),
                "layer_count": len(layers) if isinstance(layers, list) else None,
            }
        )
    out.sort(key=lambda d: str(d.get("path", "")))
    return out


def _unverified_parts_from_circuit() -> list[dict]:
    """LIB-003 stretch: emit a machine-readable list of unverified/JIT parts.

    A part is considered "unverified" if it has an OpenHaC JIT confidence label
    of medium or low on the generated BOM line.
    """
    from openhac.circuit import get_default_circuit

    circuit = get_default_circuit()
    out: list[dict] = []
    for part in getattr(circuit, "parts", []) or []:
        fields = getattr(part, "fields", None)
        if not isinstance(fields, dict):
            continue
        conf = str(fields.get("OpenHaC_JIT_Confidence", "") or "").strip().lower()
        if conf not in ("medium", "low"):
            continue
        out.append(
            {
                "ref": getattr(part, "ref", None),
                "value": getattr(part, "value", None),
                "footprint": getattr(part, "footprint", None),
                "kicad_symbol": getattr(part, "name", None),
                "jit_confidence": conf,
                "jit_score": fields.get("OpenHaC_JIT_Score"),
            }
        )
    out.sort(key=lambda d: (str(d.get("jit_confidence", "")), str(d.get("ref", ""))))
    return out


def _write_unverified_parts_handoff(path: str) -> bool:
    parts = _unverified_parts_from_circuit()
    if not parts:
        return False
    payload = {
        "schema_ref": "openhac.unverified_parts.v1",
        "unverified_parts": parts,
    }
    Path(path).write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return True


def _write_stackup_handoff_json(base: Path, project_name: str, board) -> None:
    """PCB-004 / SIG-001: standalone JSON handoff for stackup references + parsed summaries."""
    stack = list(getattr(board, "_stackup_references", None) or [])
    if not stack:
        return
    payload = {
        "schema": "openhac.stackup_handoff.v1",
        "stackup_references": stack,
        "stackup_json_summaries": _stackup_json_summaries(board),
    }
    out = base / f"{project_name}.openhac-stackup-handoff.json"
    out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    logger.info("Wrote %s", out)


def _kicad_symbol_dirs_configured() -> bool:
    """SCH-001: True if typical KiCad symbol dir env hints are present."""
    for k in os.environ:
        if "SYMBOL" in k.upper() and "KICAD" in k.upper():
            v = os.environ.get(k, "").strip()
            if v:
                return True
    v = os.environ.get("OPENHAC_KICAD_SYMBOL_DIRS", "").strip()
    return bool(v)


def _kicad_symbol_search_paths() -> list[str]:
    """SCH-001: resolved symbol library search directories (for audit / debugging)."""
    try:
        from openhac.compiler.kicad_sym_pinpos import symbol_library_search_paths

        return [str(p) for p in symbol_library_search_paths()]
    except Exception:
        return []


def _kicad_footprint_search_paths() -> list[str]:
    """PCB-001: resolved footprint root directories (contain `*.pretty`)."""
    try:
        from openhac.compiler.pcb_placement import footprint_search_roots

        return list(footprint_search_roots())
    except Exception:
        return []


def _kicad_footprint_dirs_configured() -> bool:
    """PCB-001: True if typical KiCad footprint dir env hints are present."""
    for k in ("KICAD9_FOOTPRINT_DIR", "KICAD8_FOOTPRINT_DIR", "KICAD_FOOTPRINT_DIR"):
        v = (os.environ.get(k) or "").strip()
        if v:
            return True
    return False


def _write_length_match_hint_md(base: Path, project_name: str, board) -> None:
    """SIG-005: human-readable length-match list for KiCad / external router."""
    lmg = getattr(board, "_length_match_groups", None) or []
    if not lmg:
        return
    out = base / f"{project_name}.openhac-length-match-hint.md"
    lines = [
        "# Length-match handoff (SIG-005)",
        "",
        "Declare these groups as matched-length in KiCad or your router; OpenHaC records intent only.",
        "",
    ]
    for g in lmg:
        name = g.get("name", "?")
        nets = g.get("nets") or []
        lines.append(f"## {name}")
        lines.append("")
        for n in nets:
            lines.append(f"- `{n}`")
        lines.append("")
    out.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Wrote %s", out)


def _write_length_match_constraints_json(base: Path, project_name: str, board) -> None:
    """SIG-005: standalone JSON for length-match groups (external routers / CM tooling)."""
    lmg = getattr(board, "_length_match_groups", None) or []
    if not lmg:
        return
    groups: list[dict] = []
    for g in lmg:
        if not isinstance(g, dict):
            continue
        name = str(g.get("name", "") or "").strip()
        nets = g.get("nets")
        if not isinstance(nets, list):
            nets = []
        groups.append(
            {
                "name": name or "?",
                "nets": [str(x) for x in nets],
            }
        )
    payload = {"schema": "openhac.length_match_constraints.v1", "groups": groups}
    out = base / f"{project_name}.openhac-length-match-constraints.json"
    out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    logger.info("Wrote %s", out)


def _write_diff_pair_constraints_json(
    base: Path, project_name: str, diff_pairs: list[dict]
) -> None:
    """SIG-002: standalone JSON for differential-pair intent (SI / external routers)."""
    if not diff_pairs:
        return
    payload = {
        "schema": "openhac.diff_pair_handoff.v1",
        "pairs": list(diff_pairs),
    }
    out = base / f"{project_name}.openhac-diff-pair-constraints.json"
    out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    logger.info("Wrote %s", out)


def _write_no_autoroute_constraints_json(base: Path, project_name: str, board) -> None:
    """PCB-007: standalone JSON for nets excluded from OpenHaC autoroute (router / CM tooling)."""
    nar = list(getattr(board, "_no_autoroute_net_names", None) or [])
    if not nar:
        return
    nets = sorted(dict.fromkeys(str(x) for x in nar))
    payload = {"schema": "openhac.no_autoroute_handoff.v1", "nets": nets}
    out = base / f"{project_name}.openhac-no-autoroute-constraints.json"
    out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    logger.info("Wrote %s", out)


def _write_pcb_auxiliary_constraints_json(base: Path, project_name: str, board) -> None:
    """PCB-009 / PCB-010: standalone JSON for copper pour + mounting hole intent (CM / layout tooling)."""
    pours = list(getattr(board, "_copper_pour_intents", None) or [])
    mounts = list(getattr(board, "_mounting_hole_intents", None) or [])
    if not pours and not mounts:
        return
    payload = {
        "schema": "openhac.pcb_auxiliary_handoff.v1",
        "copper_pour_intents": pours,
        "mounting_hole_intents": mounts,
    }
    out = base / f"{project_name}.openhac-pcb-auxiliary-constraints.json"
    out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    logger.info("Wrote %s", out)


def _write_power_rail_handoff_json(base: Path, project_name: str, board) -> None:
    """SCH-004: standalone JSON for declared power rails (documentation / CM checklist tooling)."""
    rails = list(getattr(board, "_power_rail_intents", None) or [])
    if not rails:
        return
    payload = {"schema": "openhac.power_rail_handoff.v1", "power_rails": rails}
    out = base / f"{project_name}.openhac-power-rails.json"
    out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    logger.info("Wrote %s", out)


def _write_rail_conversion_handoff_json(base: Path, project_name: str, board) -> None:
    """PWR-002: standalone JSON for rail conversion intents + declared rail voltages (ERC handoff)."""
    convs = list(getattr(board, "_rail_conversions", None) or [])
    dsv = getattr(board, "declared_supply_voltages_v", None) or {}
    if not convs:
        return
    payload = {
        "schema": "openhac.rail_conversions_handoff.v1",
        "rail_conversions": convs,
        "declared_supply_voltages_v": dict(dsv) if dsv else {},
    }
    out = base / f"{project_name}.openhac-rail-conversions.json"
    out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    logger.info("Wrote %s", out)


def _write_pcb_routing_handoff_json(
    base: Path,
    project_name: str,
    board,
    diff_pairs: list[dict],
    netclass_suggestions: list[dict],
) -> None:
    """PCB-007 / SIG-002 / SIG-006: routing + diff + length + mixed-signal intent."""
    nar = list(getattr(board, "_no_autoroute_net_names", None) or [])
    lmg = list(getattr(board, "_length_match_groups", None) or [])
    nroles = list(getattr(board, "_net_roles", None) or [])
    nmh = list(getattr(board, "_net_merge_hints", None) or [])
    pours = list(getattr(board, "_copper_pour_intents", None) or [])
    mounts = list(getattr(board, "_mounting_hole_intents", None) or [])
    if not nar and not diff_pairs and not lmg and not nroles and not nmh and not pours and not mounts:
        return
    payload = {
        "schema": "openhac.pcb_routing_handoff.v1",
        "no_autoroute_nets": nar,
        "diff_pair_intent": list(diff_pairs),
        "length_match_groups": lmg,
        "net_roles": nroles,
        "net_merge_hints": nmh,
        "copper_pour_intents": pours,
        "mounting_hole_intents": mounts,
    }
    if netclass_suggestions:
        payload["netclass_suggestions"] = list(netclass_suggestions)
    out = base / f"{project_name}.openhac-pcb-routing-handoff.json"
    out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    logger.info("Wrote %s", out)


def _try_git_worktree_dirty(cwd: Path) -> bool | None:
    """Return True/False if *cwd* is a git checkout with a clean/dirty worktree; None if unknown."""
    try:
        r = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=8,
            cwd=cwd,
        )
        if r.returncode != 0:
            return None
        return bool(r.stdout.strip())
    except (OSError, subprocess.TimeoutExpired):
        return None


def _source_input_record(path: str | os.PathLike[str] | None) -> dict | None:
    """Return path + hash for the compiled hardware description script, if present."""
    if path is None:
        return None
    p = Path(path).resolve()
    if not p.is_file():
        logger.warning("source_script_path is not a readable file: %s", p)
        return None
    line_count = 0
    try:
        with p.open(encoding="utf-8", errors="replace") as sf:
            line_count = sum(1 for _ in sf)
    except OSError:
        pass
    return {
        "path": str(p),
        "bytes": p.stat().st_size,
        "sha256": _sha256_file(p),
        "line_count": line_count,
    }


def _fab_profile_json_keys(profile_name: str) -> list[str] | None:
    """Top-level keys from ``openhac.fab_profiles/<name>.json`` for manifest traceability (MFG-004)."""
    try:
        from importlib.resources import files

        root = files("openhac.fab_profiles")
        path = root / f"{profile_name}.json"
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        return sorted(str(k) for k in data.keys())
    except Exception:
        return None


def _write_fab_stackup_handoff_md(base: Path, project_name: str, board) -> None:
    """Human-editable fab stackup stub when ``declare_stackup_reference`` was used (MFG-003)."""
    stack = getattr(board, "_stackup_references", None) or []
    if not stack:
        return
    out = base / f"{project_name}.openhac-fab-handoff.md"
    lines = [
        "# Fabrication stackup handoff (MFG-003)",
        "",
        "OpenHaC recorded these stackup / dielectric documentation paths at compile time.",
        "Complete a stackup table for your CM; see `examples/fab_stackup_table.md`.",
        "",
    ]
    for ref in stack:
        lines.append(f"- **{ref.get('role', '?')}**: `{ref.get('path', '?')}`")
        note = ref.get("documentation_note")
        if note:
            lines.append(f"  - Note: {note}")
        lines.append("")
    out.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Wrote %s", out)


def write_compile_manifest(
    project_name: str,
    board,
    *,
    generate_bom: bool,
    export_schematic: bool,
    extra_outputs: list[str] | None = None,
    source_script_path: str | os.PathLike[str] | None = None,
    output_dir: str | os.PathLike[str] | None = None,
    write_sha256_sidecar: bool = False,
    auto_route: bool = True,
    skip_layout: bool = False,
    release_zip_path: str | os.PathLike[str] | None = None,
) -> None:
    """Emit ``{project_name}.openhac-manifest.json`` listing outputs that exist on disk."""
    cwd = Path.cwd()
    base = Path(output_dir).resolve() if output_dir is not None else cwd
    outputs: list[dict] = []
    _write_fab_stackup_handoff_md(base, project_name, board)
    _write_stackup_handoff_json(base, project_name, board)
    diff_pairs_early = _diff_pairs_from_board(board)
    netclass_suggestions = _netclass_suggestions(board, diff_pairs_early)
    pcb007_netclass_suggestion_count = len(netclass_suggestions)
    _write_netclass_hint_md(base, project_name, netclass_suggestions)
    _write_length_match_hint_md(base, project_name, board)
    _write_length_match_constraints_json(base, project_name, board)
    _write_mixed_signal_hint_md(base, project_name, board)
    _write_mixed_signal_constraints_json(base, project_name, board)
    _write_si_stackup_reminder_md(base, project_name, board, diff_pairs_early)
    _write_diff_pair_constraints_json(base, project_name, diff_pairs_early)
    _write_no_autoroute_constraints_json(base, project_name, board)
    _write_pcb_auxiliary_constraints_json(base, project_name, board)
    _write_power_rail_handoff_json(base, project_name, board)
    _write_rail_conversion_handoff_json(base, project_name, board)
    _write_pcb_routing_handoff_json(
        base, project_name, board, diff_pairs_early, netclass_suggestions
    )
    if generate_bom:
        _write_bom_alternates_json(base, project_name, board)
    _write_bom_expand_hint_md(base, project_name, board)
    _write_spice_model_hint_md(base, project_name, board)
    _write_autoroute_policy_md(
        base, project_name, board, diff_pairs_early, auto_route=auto_route, skip_layout=skip_layout
    )

    def add_if_exists(rel_name: str) -> None:
        p = (base / rel_name).resolve()
        if not p.is_file():
            return
        try:
            display = str(p.relative_to(cwd))
        except ValueError:
            display = str(p)
        outputs.append(
            {
                "path": display,
                "bytes": p.stat().st_size,
                "sha256": _sha256_file(p),
            }
        )

    add_if_exists(f"{project_name}.openhac-fab-handoff.md")
    add_if_exists(f"{project_name}.openhac-stackup-handoff.json")
    add_if_exists(f"{project_name}.openhac-netclass-hint.md")
    add_if_exists(f"{project_name}.openhac-diff-pair-constraints.json")
    add_if_exists(f"{project_name}.openhac-no-autoroute-constraints.json")
    add_if_exists(f"{project_name}.openhac-pcb-auxiliary-constraints.json")
    add_if_exists(f"{project_name}.openhac-power-rails.json")
    add_if_exists(f"{project_name}.openhac-rail-conversions.json")
    add_if_exists(f"{project_name}.openhac-unverified-parts.json")
    add_if_exists(f"{project_name}.openhac-sch-pinpos-report.json")
    add_if_exists(f"{project_name}.openhac-length-match-hint.md")
    add_if_exists(f"{project_name}.openhac-length-match-constraints.json")
    add_if_exists(f"{project_name}.openhac-mixed-signal-hint.md")
    add_if_exists(f"{project_name}.openhac-mixed-signal-constraints.json")
    add_if_exists(f"{project_name}.openhac-pcb-routing-handoff.json")
    add_if_exists(f"{project_name}.openhac-bom-alternates.json")
    add_if_exists(f"{project_name}.openhac-si-stackup-reminder.md")
    add_if_exists(f"{project_name}.openhac-bom-expand-hint.md")
    add_if_exists(f"{project_name}.openhac-spice-model-hint.md")
    add_if_exists(f"{project_name}.openhac-autoroute-policy.md")
    add_if_exists(f"{project_name}.net")
    add_if_exists(f"{project_name}.kicad_pcb")
    if generate_bom:
        add_if_exists(f"{project_name}.csv")
    if export_schematic:
        add_if_exists(f"{project_name}.kicad_sch")
        add_if_exists(f"{project_name}.kicad_pro")

    for rel in extra_outputs or []:
        add_if_exists(rel)

    gh = _try_git_head(cwd)
    gbr = _try_git_branch(cwd)
    gdesc = _try_git_describe(cwd)
    dirty = _try_git_worktree_dirty(cwd)
    manifest: dict = {
        "manifest_schema_version": "1.0",
        "openhac_version": get_version(),
        "project_name": project_name,
        "generated_utc": _generated_utc_iso(),
        "board_size_mm": [float(board.size_mm[0]), float(board.size_mm[1])],
        "layers": int(board.layers),
        "git_commit": gh,
        "outputs": sorted(outputs, key=lambda x: x["path"]),
        "sch_pin_sort_mode": "alphanumeric_natural",
    }
    _hooks = getattr(board, "_erc_hooks", None) or []
    manifest["erc_plugin_hook_count"] = len(_hooks)
    manifest["mfg001_fab_export_cli"] = "kicad-cli pcb export gerbers"
    manifest["mfg002_assembly_export_cli"] = "kicad-cli pcb export pos"
    manifest["sim002_spice_cli_flags"] = {
        "spice_line": "--spice-line",
        "spice_preset": "--spice-preset",
        "spice_analysis_json": "--spice-analysis-json",
    }
    if gbr:
        manifest["git_branch"] = gbr
    if gdesc:
        manifest["git_describe"] = gdesc
    if int(board.layers) > 2:
        manifest["pcb_stackup_layer_note"] = (
            f"PCB-003: {int(board.layers)} copper layers declared; OpenHaC does not emit KiCad stackup metadata. "
            "Use Board.declare_stackup_reference() and docs/stackup_template.yaml for fab / SI handoff."
        )
    nar = getattr(board, "_no_autoroute_net_names", None) or []
    if nar:
        manifest["no_autoroute_nets"] = list(nar)
        manifest["no_autoroute_net_count"] = len(nar)
    rails = getattr(board, "_power_rail_intents", None) or []
    if rails:
        manifest["power_rails"] = list(rails)
        manifest["power_rail_count"] = len(rails)
    _nar_cjson = base / f"{project_name}.openhac-no-autoroute-constraints.json"
    if _nar_cjson.is_file():
        manifest["pcb007_no_autoroute_constraints_schema"] = "openhac.no_autoroute_handoff.v1"
        manifest["pcb007_no_autoroute_constraints_suffix"] = ".openhac-no-autoroute-constraints.json"
        manifest["pcb007_no_autoroute_constraints_note"] = (
            "openhac-no-autoroute-constraints.json lists nets excluded from OpenHaC FreeRouting; "
            "bind to KiCad netclasses / external routers manually (PCB-007)."
        )
    _pr_json = base / f"{project_name}.openhac-power-rails.json"
    if _pr_json.is_file():
        manifest["sch004_power_rail_handoff_schema"] = "openhac.power_rail_handoff.v1"
        manifest["sch004_power_rail_handoff_suffix"] = ".openhac-power-rails.json"
        manifest["sch004_power_rail_handoff_note"] = (
            "openhac-power-rails.json lists nets explicitly declared as power rails (SCH-004) for documentation "
            "and CM checklists; KiCad functional pin types remain manual."
        )
    _rc_json = base / f"{project_name}.openhac-rail-conversions.json"
    if _rc_json.is_file():
        manifest["pwr002_rail_conversions_handoff_schema"] = "openhac.rail_conversions_handoff.v1"
        manifest["pwr002_rail_conversions_handoff_suffix"] = ".openhac-rail-conversions.json"
        manifest["pwr002_rail_conversions_handoff_note"] = (
            "openhac-rail-conversions.json records declared rail conversions (input/output/efficiency) and rail "
            "voltages for ERC propagation (PWR-002)."
        )
    _uvp_json = base / f"{project_name}.openhac-unverified-parts.json"
    if _write_unverified_parts_handoff(str(_uvp_json)):
        manifest["lib003_unverified_parts_schema"] = "openhac.unverified_parts.v1"
        manifest["lib003_unverified_parts_suffix"] = ".openhac-unverified-parts.json"
        manifest["lib003_unverified_parts_writer"] = "openhac.compiler.compile_manifest._write_unverified_parts_handoff"
    if dirty is not None:
        manifest["git_worktree_dirty"] = dirty
    net_roles = getattr(board, "_net_roles", None) or []
    if net_roles:
        manifest["net_roles"] = list(net_roles)
        manifest["net_role_count"] = len(net_roles)
    lmg = getattr(board, "_length_match_groups", None) or []
    if lmg:
        manifest["length_match_groups"] = list(lmg)
        manifest["length_match_group_count"] = len(lmg)
        _lm_names = [
            str(g.get("name"))
            for g in lmg
            if isinstance(g, dict) and g.get("name")
        ]
        if _lm_names:
            manifest["length_match_group_names"] = _lm_names
    _lmc_json = base / f"{project_name}.openhac-length-match-constraints.json"
    if _lmc_json.is_file():
        manifest["sig005_length_match_constraints_schema"] = "openhac.length_match_constraints.v1"
        manifest["sig005_length_match_constraints_suffix"] = ".openhac-length-match-constraints.json"
        manifest["sig005_length_match_constraints_note"] = (
            "openhac-length-match-constraints.json lists length-match net groups for external tools; "
            "KiCad native constraint import / tune-length automation is still manual (SIG-005)."
        )
    diff_pairs = diff_pairs_early
    if diff_pairs:
        manifest["diff_pair_intent"] = diff_pairs
        manifest["diff_pair_intent_count"] = len(diff_pairs)
    _dpc_json = base / f"{project_name}.openhac-diff-pair-constraints.json"
    if _dpc_json.is_file():
        manifest["sig002_diff_pair_constraints_schema"] = "openhac.diff_pair_handoff.v1"
        manifest["sig002_diff_pair_constraints_suffix"] = ".openhac-diff-pair-constraints.json"
        manifest["sig002_diff_pair_constraints_note"] = (
            "openhac-diff-pair-constraints.json lists differential-pair intent for external SI tools; "
            "full netclass automation in KiCad is still manual (SIG-002)."
        )
    stack = getattr(board, "_stackup_references", None) or []
    if stack:
        manifest["stackup_references"] = list(stack)
        manifest["stackup_reference_count"] = len(stack)
    sj = _stackup_json_summaries(board)
    if sj:
        manifest["stackup_json_summaries"] = sj
        manifest["stackup_json_summaries_count"] = len(sj)
    _stack_handoff = base / f"{project_name}.openhac-stackup-handoff.json"
    if _stack_handoff.is_file():
        manifest["pcb004_stackup_handoff_schema"] = "openhac.stackup_handoff.v1"
        manifest["pcb004_stackup_handoff_suffix"] = ".openhac-stackup-handoff.json"
        manifest["pcb004_stackup_handoff_note"] = (
            "openhac-stackup-handoff.json records stackup reference paths plus JSON summaries when available; "
            "pcbnew stackup metadata emission remains manual (PCB-004 / SIG-001)."
        )
    dfm = getattr(board, "_dfm_references", None) or []
    if dfm:
        manifest["dfm_references"] = list(dfm)
        manifest["dfm_reference_count"] = len(dfm)
    pours_m = getattr(board, "_copper_pour_intents", None) or []
    if pours_m:
        manifest["copper_pour_intents"] = list(pours_m)
        manifest["copper_pour_intent_count"] = len(pours_m)
    mounts_m = getattr(board, "_mounting_hole_intents", None) or []
    if mounts_m:
        manifest["mounting_hole_intents"] = list(mounts_m)
        manifest["mounting_hole_intent_count"] = len(mounts_m)
    _pcb_aux_json = base / f"{project_name}.openhac-pcb-auxiliary-constraints.json"
    if _pcb_aux_json.is_file():
        manifest["pcb_auxiliary_handoff_schema"] = "openhac.pcb_auxiliary_handoff.v1"
        manifest["pcb_auxiliary_handoff_suffix"] = ".openhac-pcb-auxiliary-constraints.json"
        manifest["pcb_auxiliary_handoff_note"] = (
            "openhac-pcb-auxiliary-constraints.json records copper pour and mounting hole intent for CM / layout; "
            "pcbnew copper zones and NPTH drill geometry are not emitted by OpenHaC (PCB-009 / PCB-010)."
        )
    lmods = _logical_modules_manifest(board)
    if lmods:
        manifest["logical_modules"] = lmods
        _lmn = [str(x.get("name", "")) for x in lmods if x.get("name")]
        if _lmn:
            manifest["logical_module_names"] = _lmn
        manifest["schematic_hierarchy_handoff"] = {
            "logical_module_count": len(lmods),
            "note": (
                "OpenHaC emits a flat .kicad_sch; use logical_modules[].name and references[] "
                "to partition symbols across KiCad hierarchical sheets (SCH-002)."
            ),
        }
        manifest["logical_module_reference_total"] = sum(
            len(x.get("references") or []) for x in lmods if isinstance(x, dict)
        )
    if output_dir is not None:
        manifest["output_directory"] = str(base)
    src = _source_input_record(source_script_path)
    if src is not None:
        manifest["source_input"] = src

    tag = (getattr(board, "release_tag", None) or "").strip() or (
        os.environ.get("OPENHAC_RELEASE_TAG") or ""
    ).strip()
    if tag:
        manifest["release_tag"] = tag
    profile = (getattr(board, "build_profile", None) or "").strip() or (
        os.environ.get("OPENHAC_BUILD_PROFILE") or ""
    ).strip()
    if profile:
        manifest["build_profile"] = profile
    bom_prof = (getattr(board, "bom_profile", None) or "").strip()
    if bom_prof:
        manifest["bom_profile"] = bom_prof
        if bom_prof.lower() in ("prod", "production", "cm"):
            manifest["bom_prod_omitted_columns"] = sorted(BOM_PROFILE_PROD_OMITTED_COLUMNS)
            manifest["lib004_prod_bom_profile_active"] = True

    if _deterministic_manifest_enabled():
        # Golden/CI runs want byte-stable manifests; platform/executable paths differ across machines.
        manifest["build_environment"] = {"deterministic": True}
    else:
        manifest["build_environment"] = {
            "platform": platform.platform(),
            "python_version": sys.version.split()[0],
            "python_executable": sys.executable,
        }
    manifest["compile_env_flags"] = _compile_env_flags()
    _kcv = _try_kicad_cli_version()
    if _kcv:
        manifest["kicad_cli_version"] = _kcv
    manifest["openhac_env_keys_present"] = _openhac_env_keys_present()
    manifest["sch_kicad_symbol_dirs_configured"] = _kicad_symbol_dirs_configured()
    manifest["sch_kicad_symbol_search_paths"] = _kicad_symbol_search_paths()
    manifest["pcb_kicad_footprint_dirs_configured"] = _kicad_footprint_dirs_configured()
    manifest["pcb_kicad_footprint_search_paths"] = _kicad_footprint_search_paths()
    manifest["pcb_pipeline_handoff"] = {
        "schema_ref": "openhac.pcb_pipeline_handoff.v1",
        "placement": "PCB-001: footprints placed via generate_layout (pcbnew); coords from solver + module grid.",
        "netlist_to_pcb": "PCB-002: pad nets from SKiDL; use strict_footprint_pin_pad_match for pad-name parity.",
    }
    manifest["pcb_pipeline_handoff_key_count"] = len(manifest["pcb_pipeline_handoff"])
    fp = getattr(board, "fab_profile", None)
    if fp:
        manifest["fab_profile"] = str(fp)
    jith = _jit_confidence_histogram_from_circuit()
    if jith:
        manifest["jit_confidence_histogram"] = jith
    manifest["compile_options"] = {
        "auto_route": bool(auto_route),
        "skip_layout": bool(skip_layout),
        "release_zip_requested": bool(release_zip_path),
    }
    if release_zip_path:
        manifest["release_zip_path"] = str(Path(release_zip_path).resolve())
    manifest["compile_strictness"] = {
        "board_strict_umbrella": bool(getattr(board, "strict", False)),
        "strict_kicad": bool(getattr(board, "strict_kicad", False)),
        "strict_jit_lookups": bool(getattr(board, "strict_jit_lookups", False)),
    }
    rp: dict = {}
    if getattr(board, "require_passive_voltage_ratings", False):
        rp["require_passive_voltage_ratings"] = True
    if getattr(board, "require_resistor_voltage_ratings", False):
        rp["require_resistor_voltage_ratings"] = True
    if getattr(board, "require_passive_power_ratings", False):
        rp["require_passive_power_ratings"] = True
    if getattr(board, "require_inductor_voltage_ratings", False):
        rp["require_inductor_voltage_ratings"] = True
    _rcd = getattr(board, "require_cap_voltage_derating_ratio", None)
    if _rcd is not None:
        rp["require_cap_voltage_derating_ratio"] = float(_rcd)
    _ta = getattr(board, "ambient_operating_temp_c", None)
    if _ta is not None:
        rp["ambient_operating_temp_c"] = float(_ta)
    _tcp = getattr(board, "cap_voltage_temp_derating_percent_per_c", None)
    if _tcp is not None:
        rp["cap_voltage_temp_derating_percent_per_c"] = float(_tcp)
    if _rcd is not None or (_ta is not None and _tcp is not None):
        rp["cap_voltage_rating_reference_temp_c"] = float(getattr(board, "cap_voltage_rating_reference_temp_c", 85.0))
    _dsv = getattr(board, "declared_supply_voltages_v", None)
    if _dsv:
        rp["declared_supply_rail_count"] = len(_dsv)
    _mtp = getattr(board, "min_test_points", None)
    if _mtp is not None:
        rp["min_test_points"] = int(_mtp)
    _rtp = getattr(board, "require_test_point_on_nets", ()) or ()
    if _rtp:
        rp["require_test_point_on_nets_count"] = len(_rtp)
        manifest["rel003_test_point_net_names"] = list(_rtp)
    _tpm = getattr(board, "test_point_min_count_by_net", None)
    if _tpm:
        _tpm_sorted = dict(sorted(_tpm.items()))
        rp["test_point_min_count_by_net"] = _tpm_sorted
        manifest["rel003_test_point_min_count_by_net"] = _tpm_sorted
    if rp:
        manifest["reliability_policy"] = rp
    jlc_pol: dict = {}
    _mje = getattr(board, "max_jlc_extended_parts", None)
    if _mje is not None:
        jlc_pol["max_jlc_extended_parts"] = int(_mje)
    if getattr(board, "warn_jlc_extended_parts", False):
        jlc_pol["warn_jlc_extended_parts"] = True
    _mjb = getattr(board, "max_jlc_basic_parts", None)
    if _mjb is not None:
        jlc_pol["max_jlc_basic_parts"] = int(_mjb)
    _jcl = getattr(board, "jlc_class_line_limits", None)
    if _jcl:
        jlc_pol["jlc_class_line_limits"] = dict(_jcl)
    if jlc_pol:
        manifest["jlc_line_policy"] = jlc_pol
    lib6: dict = {}
    if getattr(board, "strict_passive_catalog_fields", False):
        lib6["strict_passive_catalog_fields"] = True
    if getattr(board, "strict_passive_attributes_json", False):
        lib6["strict_passive_attributes_json"] = True
    if lib6:
        manifest["lib006_passive_catalog_policy"] = lib6
    jlc_sum = _jlc_class_line_summary_from_circuit()
    if jlc_sum and int(jlc_sum.get("total_line_items") or 0) > 0:
        manifest["jlc_assembly_line_summary"] = jlc_sum
    nmh = getattr(board, "_net_merge_hints", None) or []
    if nmh:
        manifest["net_merge_hints"] = list(nmh)
        manifest["net_merge_hint_count"] = len(nmh)
    _msc_json = base / f"{project_name}.openhac-mixed-signal-constraints.json"
    if _msc_json.is_file():
        manifest["sig006_mixed_signal_handoff_schema"] = "openhac.mixed_signal_handoff.v1"
        manifest["sig006_mixed_signal_handoff_suffix"] = ".openhac-mixed-signal-constraints.json"
        manifest["sig006_mixed_signal_handoff_note"] = (
            "openhac-mixed-signal-constraints.json records net roles and merge hints for external tools; "
            "automated star-point / AGND enforcement in pcbnew is still future (SIG-006)."
        )

    spice_sum = _spice_annotation_summary()
    if spice_sum and (
        spice_sum.get("parts_with_spice_include", 0) or spice_sum.get("parts_with_spice_subckt", 0)
    ):
        manifest["spice_annotation_summary"] = spice_sum

    manifest["compile_pipeline_phases"] = list(COMPILE_PIPELINE_PHASE_NAMES)
    manifest["compile_pipeline_phase_count"] = len(COMPILE_PIPELINE_PHASE_NAMES)
    manifest["pcb_routing_handoff_schema"] = "openhac.pcb_routing_handoff.v1"
    _rh_json = base / f"{project_name}.openhac-pcb-routing-handoff.json"
    if _rh_json.is_file():
        manifest["pcb_routing_handoff_json_present"] = True
        manifest["pcb_routing_handoff_json_sha256"] = _sha256_file(_rh_json)
    if pcb007_netclass_suggestion_count:
        manifest["pcb007_netclass_suggestion_count"] = pcb007_netclass_suggestion_count
        manifest["pcb007_netclass_hint_markdown_suffix"] = ".openhac-netclass-hint.md"
        manifest["pcb007_netclass_hint_writer"] = "openhac.compiler.compile_manifest._write_netclass_hint_md"
        manifest["pcb007_netclass_hint_note"] = (
            "openhac-netclass-hint.md suggests KiCad netclass names from routing intent; "
            "OpenHaC does not emit .kicad_pro (PCB-007)."
        )

    alt_json = base / f"{project_name}.openhac-bom-alternates.json"
    if alt_json.is_file():
        manifest["bom_alternates_schema"] = "openhac.bom_alternates.v1"
        manifest["bom_alternates_handoff"] = {
            "alternates_json": f"{project_name}.openhac-bom-alternates.json",
            "expand_hint_markdown": f"{project_name}.openhac-bom-expand-hint.md",
        }
        try:
            raw_alt = json.loads(alt_json.read_text(encoding="utf-8"))
            bg = raw_alt.get("by_generic") if isinstance(raw_alt, dict) else None
            if isinstance(bg, dict):
                manifest["bom_alternates_generic_count"] = len(bg)
                manifest["bom_alternates_total_rows"] = sum(
                    len(v) for v in bg.values() if isinstance(v, list)
                )
        except (OSError, json.JSONDecodeError, TypeError):
            pass

    fp_name = getattr(board, "fab_profile", None)
    if fp_name:
        gkeys = _fab_profile_json_keys(str(fp_name))
        if gkeys is not None:
            manifest["fab_profile_geometry_keys"] = gkeys
        _fbp = _fab_profile_bundle_path(str(fp_name))
        if _fbp:
            manifest["fab_profile_json_path"] = _fbp

    manifest["release_bundle_suffixes"] = list(_RELEASE_SUFFIXES)
    manifest["release_bundle_suffix_count"] = len(_RELEASE_SUFFIXES)

    manifest["outputs_artifact_count"] = len(outputs)
    manifest["outputs_total_bytes"] = sum(int(o.get("bytes") or 0) for o in outputs)

    from openhac.compiler.spice_presets import PRESETS

    manifest["spice_presets_catalog"] = sorted(PRESETS.keys())

    _netp = base / f"{project_name}.net"
    if _netp.is_file():
        try:
            with _netp.open(encoding="utf-8", errors="replace") as nf:
                manifest["netlist_line_count"] = sum(1 for _ in nf)
        except OSError:
            pass
        manifest["netlist_suffix"] = ".net"

    _csv = base / f"{project_name}.csv"
    if generate_bom and _csv.is_file():
        try:
            with _csv.open(newline="", encoding="utf-8") as cf:
                hdr = next(csv.reader(cf), None)
            if hdr:
                manifest["bom_csv_column_names"] = hdr
            with _csv.open(encoding="utf-8") as cf:
                clines = sum(1 for _ in cf)
            manifest["bom_csv_line_count"] = clines
            if clines >= 1:
                manifest["bom_csv_data_row_count"] = clines - 1
        except OSError:
            pass

    manifest["pwr002_stdlib_helpers_catalog"] = ["buck_input_current_ma"]

    manifest["fab_profiles_catalog"] = _fab_profile_bundle_names()
    manifest["sim001_spice_database_fields"] = ["spice_include", "spice_subckt"]
    manifest["sch003_schematic_erc_cli"] = "kicad-cli sch erc"
    manifest["sig001_stackup_template_reference"] = "docs/stackup_template.yaml"
    manifest["lib003_jit_bom_columns"] = ["OpenHaC_JIT_Confidence", "OpenHaC_JIT_Score"]

    manifest["compile_manifest_emitter"] = "openhac.compiler.compile_manifest.write_compile_manifest"
    manifest["compile_pipeline_module"] = "openhac.compiler.compile_pipeline"
    manifest["str002_cli_module"] = "openhac.cli"
    manifest["sch005_erc_rules_module"] = "openhac.stdlib.erc_rules"
    manifest["sch005_erc_rule_packs_module"] = "openhac.stdlib.erc_rule_packs"
    manifest["sw006_skip_layout_env_key"] = "OPENHAC_SKIP_LAYOUT"
    manifest["lib001_bom_offer_column_names"] = [
        "Ranked_Offers",
        "Primary_Offer",
        "Secondary_Offer",
        "Offer_Count",
    ]
    manifest["lib004_bom_prod_omitted_column_count"] = len(BOM_PROFILE_PROD_OMITTED_COLUMNS)
    manifest["pcb_routing_handoff_writer"] = (
        "openhac.compiler.compile_manifest._write_pcb_routing_handoff_json"
    )
    manifest["mfg003_fab_handoff_markdown_suffix"] = ".openhac-fab-handoff.md"
    manifest["sig002_diff_pair_intent_disclaimer"] = (
        "diff_pair_intent records target Z0 and net names only; set controlled impedance in KiCad netclasses (SIG-002)."
    )
    manifest["sig002_diff_pair_constraints_writer"] = (
        "openhac.compiler.compile_manifest._write_diff_pair_constraints_json"
    )
    manifest["sig005_length_match_constraints_writer"] = (
        "openhac.compiler.compile_manifest._write_length_match_constraints_json"
    )
    manifest["sig006_mixed_signal_handoff_writer"] = (
        "openhac.compiler.compile_manifest._write_mixed_signal_constraints_json"
    )
    manifest["pcb007_no_autoroute_constraints_writer"] = (
        "openhac.compiler.compile_manifest._write_no_autoroute_constraints_json"
    )
    manifest["pcb_auxiliary_handoff_writer"] = (
        "openhac.compiler.compile_manifest._write_pcb_auxiliary_constraints_json"
    )
    manifest["sch004_power_rail_handoff_writer"] = (
        "openhac.compiler.compile_manifest._write_power_rail_handoff_json"
    )
    manifest["pwr002_rail_conversions_handoff_writer"] = (
        "openhac.compiler.compile_manifest._write_rail_conversion_handoff_json"
    )
    manifest["pcb004_stackup_handoff_writer"] = (
        "openhac.compiler.compile_manifest._write_stackup_handoff_json"
    )
    manifest["pcb009_copper_pour_handoff_note"] = (
        "declare_copper_pour_intent is documentation + manifest; pcbnew copper zones are not emitted by OpenHaC (PCB-009)."
    )
    manifest["pcb010_mounting_hole_handoff_note"] = (
        "declare_mounting_hole is documentation + manifest; NPTH drill geometry is not emitted by OpenHaC (PCB-010)."
    )
    manifest["rel001_reliability_policy_key_catalog"] = [
        "ambient_operating_temp_c",
        "cap_voltage_rating_reference_temp_c",
        "cap_voltage_temp_derating_percent_per_c",
        "declared_supply_rail_count",
        "min_test_points",
        "require_cap_voltage_derating_ratio",
        "require_inductor_voltage_ratings",
        "require_passive_power_ratings",
        "require_passive_voltage_ratings",
        "require_resistor_voltage_ratings",
        "require_test_point_on_nets_count",
        "test_point_min_count_by_net",
    ]
    manifest["sim002_spice_config_file_suffixes"] = [".json", ".yaml", ".yml"]
    manifest["sim002_default_analysis_note"] = (
        "CLI simulate applies a default transient (.tran) analysis when no --spice-line, --spice-preset, or "
        "--spice-analysis-json is provided (SIM-002). Analysis files may be JSON or YAML with "
        "analysis_lines: [str, ...] or preset: <name>."
    )
    manifest["sim002_spice_analysis_config_module"] = "openhac.compiler.spice_analysis_config"
    manifest["str002_compile_pipeline_entry"] = "openhac.compiler.compile_pipeline.run_compile_phases"
    manifest["str002_openhac_distribution_package"] = "openhac"
    manifest["sch003_kicad_erc_report_suffixes"] = [".kicad_sch.erc.txt", ".kicad_sch.erc.json"]
    manifest["mfg005_release_zip_sha256_note"] = (
        "After the first release zip is written, release_zip_sha256 records SHA256 of that zip; the manifest is "
        "patched and the zip is rebuilt so the bundle includes the digest (MFG-005). The digest is not the hash of "
        "the final zip bytes (self-reference)."
    )
    manifest["str002_manifest_json_sort_keys"] = True
    manifest["str002_patch_manifest_release_zip_function"] = (
        "openhac.compiler.compile_manifest.patch_manifest_release_zip_sha256"
    )
    manifest["mfg005_zip_project_outputs_function"] = "openhac.compiler.release_bundle.zip_project_outputs"
    manifest["sim002_spice_analysis_loader_function"] = "openhac.compiler.spice_analysis_config.load_spice_analysis_raw"
    manifest["sw003_netlist_gen_module"] = "openhac.compiler.netlist_gen"
    manifest["spice_presets_module"] = "openhac.compiler.spice_presets"
    manifest["pcb001_kicad_pcb_suffix"] = ".kicad_pcb"
    manifest["sch001_kicad_sch_suffix"] = ".kicad_sch"
    manifest["sch001_kicad_pro_suffix"] = ".kicad_pro"
    manifest["lib002_bom_csv_suffix"] = ".csv"
    manifest["str002_rule_check_module"] = "openhac.compiler.rule_check"
    manifest["str002_layout_gen_module"] = "openhac.compiler.layout_gen"
    manifest["str002_autoroute_module"] = "openhac.compiler.autoroute_cli"
    manifest["str002_kicad_sch_erc_module"] = "openhac.compiler.kicad_sch_erc"
    manifest["str002_schematic_gen_module"] = "openhac.compiler.schematic_gen"
    manifest["str002_spice_gen_module"] = "openhac.compiler.spice_gen"
    manifest["str002_project_gen_module"] = "openhac.compiler.project_gen"
    manifest["str002_compile_state_dataclass"] = "openhac.compiler.compile_pipeline.CompileState"
    manifest["str002_manifest_json_suffix"] = ".openhac-manifest.json"
    manifest["str002_manifest_sha256_sidecar_suffix"] = ".openhac-manifest.json.sha256"
    manifest["sim002_spice_netlist_suffix"] = ".cir"
    manifest["str002_kicad_erc_report_module"] = "openhac.compiler.kicad_erc_report"
    manifest["str002_layout_constraints_module"] = "openhac.compiler.layout_constraints"
    manifest["str002_pcb_placement_module"] = "openhac.compiler.pcb_placement"
    manifest["mfg001_export_fab_module"] = "openhac.compiler.export_fab"
    manifest["str002_compile_manifest_module"] = "openhac.compiler.compile_manifest"
    manifest["str002_version_info_module"] = "openhac.version_info"
    manifest["sw005_circuit_public_module"] = "openhac.circuit"
    manifest["sim002_resolve_spice_analysis_function"] = (
        "openhac.compiler.spice_analysis_config.resolve_spice_analysis_from_mapping"
    )
    manifest["sch001_kicad_sym_pinpos_module"] = "openhac.compiler.kicad_sym_pinpos"
    manifest["sch001_pinpos_report_schema"] = "openhac.sch_pinpos_report.v1"
    manifest["sch001_pinpos_report_suffix"] = ".openhac-sch-pinpos-report.json"
    manifest["sch001_pinpos_report_writer"] = "openhac.compiler.schematic_gen.generate_schematic"
    manifest["str002_core_board_module"] = "openhac.core.board"
    manifest["str002_core_base_module"] = "openhac.core.base"
    manifest["str002_core_compile_context_module"] = "openhac.core.compile_context"
    manifest["pwr002_stdlib_power_module"] = "openhac.stdlib.power"
    manifest["lib003_database_api_fallback_module"] = "openhac.database.api_fallback"
    manifest["str002_compile_pipeline_default_phases_symbol"] = (
        "openhac.compiler.compile_pipeline.DEFAULT_COMPILE_PHASES"
    )
    manifest["str002_openhac_version_info_function"] = "openhac.version_info.get_version"
    manifest["str002_openhac_user_agent_function"] = "openhac.version_info.user_agent"
    manifest["str002_stdlib_erc_rules_module"] = "openhac.stdlib.erc_rules"
    manifest["str002_release_bundle_module"] = "openhac.compiler.release_bundle"
    manifest["str002_stdlib_passives_module"] = "openhac.stdlib.passives"
    manifest["lib003_db_manager_module"] = "openhac.database.db_manager"
    manifest["lib003_sync_jlc_module"] = "openhac.database.sync_jlc"
    manifest["str002_netlist_gen_generate_function"] = "openhac.compiler.netlist_gen.generate_logic_and_bom"
    manifest["str002_rule_check_run_erc_function"] = "openhac.compiler.rule_check.run_erc"
    manifest["str002_rule_check_run_drc_function"] = "openhac.compiler.rule_check.run_drc"
    manifest["sim002_spice_presets_preset_analysis_lines_function"] = (
        "openhac.compiler.spice_presets.preset_analysis_lines"
    )

    out_path = base / f"{project_name}.openhac-manifest.json"
    text = json.dumps(manifest, indent=2, sort_keys=True)
    out_path.write_text(text, encoding="utf-8")
    logger.info("Wrote %s", out_path)
    if write_sha256_sidecar:
        hx = hashlib.sha256(text.encode("utf-8")).hexdigest()
        side = out_path.with_name(out_path.name + ".sha256")
        side.write_text(hx + "\n", encoding="utf-8")
        logger.info("Wrote %s", side)
