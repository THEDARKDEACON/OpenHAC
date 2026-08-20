"""SPICE deck generation (SIM-001 / SIM-002 / SPS Kirchhoff + models)."""

from __future__ import annotations

import json
import logging
import re
import warnings

from openhac.compiler.spice_models import (
    is_primitive_ref,
    omit_reason_label,
    resolve_part_model,
    spice_omit_reason,
    SpiceModelRecord,
)
from openhac.compiler.spice_nodes import (
    assert_no_sanitization_collisions,
    ground_alias_set,
    merge_hint_ground_aliases,
    spice_token,
)
from openhac.compiler.spice_physics import TNOM_C
from openhac.core.base import OpenHaCError
from openhac.util.sort_keys import natural_key

logger = logging.getLogger("openhac.spice")


def get_default_circuit():
    """Indirection so tests can monkeypatch ``spice_gen.get_default_circuit``."""
    from openhac.circuit import get_default_circuit as _g

    return _g()


def _resolve_spice_id(part) -> str:
    """Resolve the SPICE reference designator for a part."""
    ref = str(getattr(part, "refdes", None) or getattr(part, "ref", "X"))
    m = re.match(r"^([A-Za-z]+)", ref)
    prefix = m.group(1) if m else "X"
    if not m:
        warnings.warn(
            f"Part {ref} has no ref_prefix, defaulting to 'X'",
            UserWarning,
        )
    if ref.upper().startswith(prefix.upper()):
        return ref
    return prefix + ref


def _iter_pins(part):
    pins = getattr(part, "pins", None)
    if pins is None:
        return
    if isinstance(pins, dict):
        seen = set()
        for p in pins.values():
            ident = id(p)
            if ident in seen:
                continue
            seen.add(ident)
            yield p
    elif isinstance(pins, (list, tuple)):
        yield from pins


def _pin_num(pin) -> str:
    return str(getattr(pin, "num", None) or getattr(pin, "number", None) or "")


def _pin_name(pin) -> str:
    return str(getattr(pin, "name", None) or "")


def _pin_net_name(pin) -> str | None:
    net = getattr(pin, "net", None)
    if net is None:
        return None
    return str(getattr(net, "name", net) or "") or None


def _diode_anode_cathode(part, nodes_with_num: list[tuple[str, str]]) -> tuple[str, str]:
    """SPICE diode order is anode, cathode. Device:LED is typically pin 1=K, pin 2=A."""
    by_num = {str(n): tok for n, tok in nodes_with_num}
    anode = cathode = None
    for p in _iter_pins(part):
        nm = _pin_name(p).upper()
        tok = by_num.get(_pin_num(p))
        if tok is None:
            continue
        if nm in ("A", "ANODE", "+", "P"):
            anode = tok
        elif nm in ("K", "CATHODE", "-", "N"):
            cathode = tok
    if anode and cathode:
        return anode, cathode
    if len(nodes_with_num) >= 2:
        return nodes_with_num[0][1], nodes_with_num[1][1]
    raise OpenHaCError("diode/LED needs two connected pins")


def _is_pwr_flag(part) -> bool:
    name = str(getattr(part, "name", "") or "")
    ref = str(getattr(part, "refdes", None) or getattr(part, "ref", "") or "")
    return "PWR_FLAG" in name.upper() or ref.upper().startswith("PWR")


_PKG_TOKENS = frozenset({"0201", "0402", "0603", "0805", "1206", "1210", "2010", "2512"})
_SKIP_VALUE_TOKENS = frozenset({"A", "B", "HI", "LO", "IN", "OUT", "LED", "PU", "SDA", "SCL"})


def extract_passive_spice_value(text: str, *, kind: str = "") -> str | None:
    """Turn a generic name / description into an ngspice R/C/L value (SPS-015).

    ``C_VBUS_10U`` → ``10u``, ``R_CC1_5K1`` → ``5.1k``, ``10uF`` → ``10u``.
    """
    if not text or not str(text).strip():
        return None
    kind_u = (kind or "").upper()[:1]
    last: str | None = None
    for tok in re.split(r"[^0-9A-Za-z.µμ]+", str(text).replace("µ", "u").replace("μ", "u")):
        if not tok:
            continue
        got = _token_to_spice_value(tok, kind=kind_u)
        if got:
            last = got
    return last


def _token_to_spice_value(tok: str, *, kind: str = "") -> str | None:
    t = tok.strip()
    if not t or t.upper() in _PKG_TOKENS or t.upper() in _SKIP_VALUE_TOKENS:
        return None
    if re.fullmatch(r"\d+V\d*", t, re.I):
        return None
    # EIA 5K1 / 4R7
    m = re.fullmatch(r"(\d+)([RKMNUP])(\d+)", t, re.I)
    if m:
        a, u, b = m.group(1), m.group(2).lower(), m.group(3)
        u = {"r": "", "k": "k", "m": "meg", "n": "n", "u": "u", "p": "p"}.get(u, u)
        return f"{a}.{b}{u}"
    m = re.fullmatch(r"(\d+(?:\.\d+)?)(pf|nf|uf|uh|mh|p|n|u|k|meg|m|f|h|r)?", t, re.I)
    if not m:
        return None
    num, suf = m.group(1), (m.group(2) or "").lower()
    if not suf:
        if kind == "R" and re.fullmatch(r"\d+(?:\.\d+)?", num):
            return num
        return None
    if suf in ("pf",):
        return f"{num}p"
    if suf in ("nf",):
        return f"{num}n"
    if suf in ("uf", "f") and kind != "L":
        return f"{num}u" if suf == "uf" else f"{num}"
    if suf in ("uh", "h") and kind != "C":
        return f"{num}u" if suf == "uh" else f"{num}"
    if suf == "mh":
        return f"{num}m"
    if suf == "r":
        return num
    if suf in ("p", "n", "u", "k", "meg", "m"):
        return f"{num}{suf}"
    return None


def _part_text_blobs(part) -> list[str]:
    fields = getattr(part, "fields", None) or {}
    out: list[str] = []
    for x in (
        getattr(part, "value", None),
        fields.get("Value"),
        fields.get("Description") or fields.get("description"),
        fields.get("generic_name"),
        getattr(part, "name", None),
    ):
        s = str(x or "").strip()
        if s:
            out.append(s)
    return out


def _passive_value_for_part(part, spice_id: str, *, signoff: bool) -> str | None:
    from openhac.compiler.spice_models import ref_prefix

    orig = ref_prefix(spice_id)
    kind = "R" if orig == "F" else orig
    last = None
    for blob in _part_text_blobs(part):
        got = extract_passive_spice_value(blob, kind=kind)
        if got:
            last = got
    if last:
        return last
    if orig == "F":
        return "10m"
    if signoff:
        raise OpenHaCError(
            f"SPS-015: {spice_id} has no numeric SPICE value (got {getattr(part, 'value', None)!r})."
        )
    return None


def _handoff_spice_id(part, spice_id: str) -> str:
    """SPICE letter F is a CCCS; fuses are emitted as RF* resistors."""
    from openhac.compiler.spice_models import ref_prefix

    if ref_prefix(spice_id) == "F":
        rest = re.sub(r"^[A-Za-z]+", "", spice_id) or "1"
        return "RF" + rest
    return spice_id


def _circuit_and_parts():
    circuit = get_default_circuit()
    parts = list(getattr(circuit, "parts", []) or [])
    if parts:
        return circuit, parts
    try:
        import builtins

        sk = getattr(builtins, "default_circuit", None)
        if sk is not None:
            sk_parts = list(getattr(sk, "parts", []) or [])
            if sk_parts:
                return sk, sk_parts
    except Exception:
        pass
    return circuit, parts


def spice_circuit_parts():
    """Parts used by :func:`generate_spice` (native circuit, with SKiDL fallback)."""
    return _circuit_and_parts()


def _collect_net_names(parts) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for part in parts:
        for pin in _iter_pins(part):
            n = _pin_net_name(pin)
            if n and n not in seen:
                seen.add(n)
                names.append(n)
    return names


def _find_pin(part, entry) -> object | None:
    for pin in _iter_pins(part):
        if entry.num and _pin_num(pin) == entry.num:
            return pin
        if entry.name and _pin_name(pin).upper() == entry.name.upper():
            return pin
    return None


def _analysis_refs_ok(analysis_lines: list[str], emitted: str, *, signoff: bool) -> None:
    if not signoff:
        return
    blob = "\n".join(analysis_lines)
    if re.search(r"\bV1\b", blob) and not re.search(r"(?m)^V1[\s=]", emitted):
        raise OpenHaCError(
            "SPS-021: analysis references V1 but no source named V1 was emitted. "
            "Declare rails or use --spice-preset op."
        )
    if re.search(r"V\(\s*out\s*\)", blob, re.IGNORECASE):
        if not re.search(r"\bout\b", emitted, re.IGNORECASE):
            raise OpenHaCError(
                "SPS-021: analysis references V(out) but no node named out exists."
            )


def graph_deck_pin_parity(instance_line: str, expected_nodes: list[str]) -> None:
    """SPS-006: instance node tokens must match expected (already sanitized) order."""
    toks = instance_line.strip().split()
    if len(toks) < 2:
        raise OpenHaCError(f"SPS-006: empty instance line: {instance_line!r}")
    # ref nodes... model
    body = toks[1:-1] if len(toks) >= 3 else toks[1:]
    if body != expected_nodes:
        raise OpenHaCError(
            f"SPS-006: instance nodes {body} != expected {expected_nodes} ({instance_line!r})."
        )


def generate_spice(
    output_cir_path: str,
    *,
    analysis_lines: list[str] | None = None,
    signoff: bool = False,
    ground_net_names: list[str] | None = None,
    merge_hints: list[dict] | None = None,
    rails: dict[str, float] | None = None,
    probes: list[dict] | None = None,
    allow_behavioral: bool = False,
    tnom_c: float = TNOM_C,
    require_rail_sources: bool = False,
    island_names: frozenset[str] | None = None,
):
    """Write a SPICE deck to *output_cir_path* (SIM-001 / SIM-002 / SPS).

    ``analysis_lines`` defaults to ``.tran`` (handoff) or ``.op`` (sign-off).
    Ground nets map to node ``0``. Leading-digit nets get an ``N_`` prefix.
    ``island_names`` (SPS-043) omits parts whose ``OpenHaC_Module`` is not in the set.
    """
    if analysis_lines is None:
        analysis_lines = [".op"] if signoff else [".tran 1m 100m"]

    logger.info("Bypassing Physical Geometry.")
    logger.info("Generating Computational SPICE Simulation Netlist → %s", output_cir_path)

    circuit, parts = _circuit_and_parts()
    parts = sorted(parts, key=lambda p: natural_key(str(getattr(p, "ref", "") or getattr(p, "refdes", ""))))

    gnames = ground_alias_set(ground_net_names)
    gnames |= merge_hint_ground_aliases(merge_hints)

    net_names = list(_collect_net_names(parts))
    if rails:
        for n in rails:
            if n not in net_names:
                net_names.append(n)
    name_map = assert_no_sanitization_collisions(net_names, ground_names=gnames)

    resolved: dict[int, SpiceModelRecord | None] = {}
    for part in parts:
        rec = resolve_part_model(part, signoff=signoff)
        resolved[id(part)] = rec
        if signoff and rec is not None and rec.kind == "behavioral" and not allow_behavioral:
            raise OpenHaCError(
                "SPS-017: behavioral SPICE models are not allowed under spice_signoff "
                "without allow_behavioral_spice_models."
            )

    if signoff and rails:
        missing_power = []
        for n in net_names:
            tok = name_map.get(n) or spice_token(n, ground_names=gnames)
            if tok == "0":
                continue
            # Heuristic: names that look like rails must have a source if require_rail_sources
            if require_rail_sources and n not in (rails or {}) and tok != "0":
                nu = n.upper()
                if any(k in nu for k in ("VCC", "VDD", "3V3", "5V", "VBAT", "VIN", "VBUS")):
                    missing_power.append(n)
        if missing_power:
            raise OpenHaCError(
                f"SPS-020: power nets {missing_power} have no declare_spice_rail / "
                "declared_supply_voltages_v source."
            )

    try:
        emitted_refs: set[str] = set()
        instance_parity: list[tuple[str, list[str]]] = []
        with open(output_cir_path, "w", encoding="utf-8") as f:
            f.write("* OpenHaC SPICE export\n")
            f.write(f"* SPS TNOM={tnom_c} C\n")
            if analysis_lines:
                f.write("* SIM-002 analysis directives:\n")
                for line in analysis_lines:
                    f.write(f"*   {line}\n")

            f.write(f".options TEMP={tnom_c} TNOM={tnom_c}\n")

            includes_ordered: list[str] = []
            seen_inc: set[str] = set()
            wrote_ddefault = False
            for part in parts:
                raw = ""
                try:
                    raw = (part.fields.get("Spice_Include") or "").strip()
                except Exception:
                    raw = ""
                if raw and raw not in seen_inc:
                    seen_inc.add(raw)
                    includes_ordered.append(raw)
            for inc in includes_ordered:
                f.write(f".include {inc}\n")

            for line in analysis_lines:
                f.write(f"{line}\n")

            for rname, volts in sorted((rails or {}).items(), key=lambda kv: natural_key(kv[0])):
                node = name_map.get(rname) or spice_token(rname, ground_names=gnames)
                if node == "0":
                    continue
                vref = "V" + re.sub(r"[^A-Za-z0-9_]", "_", node)
                if not vref[0].isalpha():
                    vref = "V_" + vref
                f.write(f"{vref} {node} 0 DC {float(volts)}\n")

            for part in parts:
                spice_id = _resolve_spice_id(part)
                if spice_id in emitted_refs:
                    continue
                if _is_pwr_flag(part):
                    continue

                rec = resolved.get(id(part))
                fields = getattr(part, "fields", None) or {}
                subckt = (fields.get("Spice_Subckt") or "").strip()
                if rec and rec.subckt:
                    subckt = rec.subckt
                pin_map = list(rec.pin_map) if rec is not None else []
                if not pin_map:
                    raw_map = fields.get("Spice_Pin_Map") or ""
                    if raw_map:
                        from openhac.compiler.spice_models import _parse_pin_map

                        pin_map = _parse_pin_map(json.loads(raw_map) if isinstance(raw_map, str) else raw_map)

                if pin_map and (signoff or subckt):
                    nodes_list: list[str] = []
                    for entry in pin_map:
                        pin = _find_pin(part, entry)
                        nname = _pin_net_name(pin) if pin is not None else None
                        if nname:
                            nodes_list.append(name_map.get(nname) or spice_token(nname, ground_names=gnames))
                        else:
                            # Unconnected terminal
                            if signoff:
                                raise OpenHaCError(
                                    f"SPS-002: {spice_id} pin_map terminal {entry.subckt_index} "
                                    f"({entry.name or entry.num}) is unconnected; refusing to drop it."
                                )
                            nodes_list.append("0")
                    nodes = " ".join(nodes_list)
                    sid = spice_id if spice_id.upper().startswith("X") else f"X{spice_id}"
                    line = f"{sid} {nodes} {subckt}"
                    f.write(line + "\n")
                    emitted_refs.add(spice_id)
                    instance_parity.append((line, nodes_list))
                    continue

                nodes_with_num: list[tuple[str, str]] = []
                for p in _iter_pins(part):
                    nname = _pin_net_name(p)
                    if nname is not None:
                        tok = name_map.get(nname) or spice_token(nname, ground_names=gnames)
                        nodes_with_num.append((_pin_num(p), tok))
                nodes_with_num.sort(key=lambda t: natural_key(t[0]))
                nodes_list = [n for _, n in nodes_with_num]
                nodes = " ".join(nodes_list)

                from openhac.compiler.spice_models import ref_prefix as _ref_prefix

                pfx = _ref_prefix(spice_id)
                emit_id = _handoff_spice_id(part, spice_id)
                val = part.value if getattr(part, "value", None) else getattr(part, "name", "")
                if pfx in ("R", "C", "L", "V", "I", "F") or emit_id.upper().startswith("RF"):
                    parsed = _passive_value_for_part(part, spice_id, signoff=signoff)
                    if parsed:
                        val = parsed
                    elif not subckt and pfx in ("R", "C", "L", "F"):
                        f.write(f"* skipped {spice_id}: no numeric SPICE value (SPS-015)\n")
                        continue
                if subckt and nodes_list:
                    sid = spice_id if spice_id.upper().startswith("X") else f"X{spice_id}"
                    line = f"{sid} {nodes} {subckt}"
                    f.write(line + "\n")
                    emitted_refs.add(spice_id)
                    instance_parity.append((line, nodes_list))
                elif (
                    str(spice_id[:1]).upper() == "D"
                    and len(nodes_with_num) >= 2
                    and not subckt
                ):
                    if not wrote_ddefault:
                        f.write(".model DDEFAULT D\n")
                        wrote_ddefault = True
                    anode, cathode = _diode_anode_cathode(part, nodes_with_num)
                    line = f"{spice_id} {anode} {cathode} DDEFAULT"
                    f.write(line + "\n")
                    emitted_refs.add(spice_id)
                    instance_parity.append((line, [anode, cathode]))
                elif is_primitive_ref(emit_id) or emit_id.upper().startswith("RF"):
                    if len(nodes_list) < 2:
                        continue
                    line = f"{emit_id} {nodes} {val}"
                    f.write(line + "\n")
                    emitted_refs.add(spice_id)
                    instance_parity.append((line, nodes_list))
                elif (omit := spice_omit_reason(part, spice_id, island_names=island_names)):
                    f.write(
                        f"* skipped {spice_id}: {omit_reason_label(omit, island_names=island_names)}\n"
                    )
                elif signoff and not is_primitive_ref(spice_id) and not _is_pwr_flag(part):
                    raise OpenHaCError(
                        f"SPS-005: {spice_id} is not a primitive and has no vendor/physics SPICE model."
                    )
                elif len(nodes_list) >= 2:
                    # Handoff: do not emit U/Q/X as SPICE devices — those letters
                    # are BJTs, subcircuits, etc. Comment them out until a model exists.
                    f.write(
                        f"* skipped {spice_id}: no SPICE model for {val!s} "
                        f"(use --spice-signoff + vendor .lib)\n"
                    )

            probe_prints: list[str] = []
            for pr in probes or ():
                net = str(pr.get("net") or "")
                tok = name_map.get(net) or spice_token(net, ground_names=gnames)
                probe_prints.append(tok)
            analysis_blob = "\n".join(analysis_lines).lower()
            has_batch_output = any(
                tok in analysis_blob for tok in (".print", ".plot", ".fourier", ".control")
            )
            if signoff:
                f.write(".control\n")
                f.write("op\n")
                for tok in probe_prints:
                    f.write(f"print v({tok})\n")
                f.write("quit\n")
                f.write(".endc\n")
            elif not has_batch_output:
                # ngspice -b exits 1 if there is no .print/.plot/.control (no data to write).
                f.write(".control\nrun\n")
                printed = False
                for rname in sorted((rails or {}).keys(), key=natural_key):
                    tok = name_map.get(rname) or spice_token(rname, ground_names=gnames)
                    if tok == "0":
                        continue
                    f.write(f"print v({tok})\n")
                    printed = True
                for tok in probe_prints:
                    f.write(f"print v({tok})\n")
                    printed = True
                if not printed:
                    f.write("print all\n")
                f.write("quit\n.endc\n")

            f.write(".end\n")

        text = open(output_cir_path, encoding="utf-8").read()
        _analysis_refs_ok(analysis_lines, text, signoff=signoff)
        if signoff:
            for line, expected in instance_parity:
                graph_deck_pin_parity(line, expected)
        logger.info("Computational SPICE Engine (OpenHaC Native) completed successfully.")
    except Exception as e:
        logger.error("Native SPICE generation failed: %s", e)
        raise e


def spice_model_coverage_summary(
    circuit,
    *,
    island_names: frozenset[str] | None = None,
) -> dict[str, int]:
    """Best-effort summary of which in-scope parts have SPICE model annotations."""
    from openhac.compiler.spice_models import collect_spice_coverage

    rows = collect_spice_coverage(
        list(getattr(circuit, "parts", []) or []),
        island_names=island_names,
    )
    need = sum(1 for r in rows if r["status"] in ("modeled", "unmodeled"))
    have = sum(1 for r in rows if r["status"] == "modeled")
    return {"parts_requiring_models": int(need), "parts_with_models": int(have)}
