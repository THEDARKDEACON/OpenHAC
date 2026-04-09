import logging
import os
from pathlib import Path

from skidl import Net, Bus

from .base import Module, UnconnectedInterfaceError

logger = logging.getLogger("openhac.board")


def _artifact_path(project_name: str, suffix: str, output_dir: str | os.PathLike[str] | None) -> str:
    stem = f"{project_name}{suffix}"
    if output_dir is None:
        return stem
    p = Path(output_dir)
    p.mkdir(parents=True, exist_ok=True)
    return str(p / stem)


def _normalize_compile_goal(v: str | None) -> str:
    s = str(v or "").strip().lower()
    if not s:
        return "handoff"
    if s in ("handoff", "hand-off", "hand_off", "kicad", "review"):
        return "handoff"
    if s in ("fabrication", "fab", "push_button_fab", "push-button-fab", "pushbuttonfab"):
        return "fabrication"
    raise ValueError(f"compile_goal must be 'handoff' or 'fabrication', got {v!r}")


class Board:
    def __init__(
        self,
        size_mm: tuple,
        layers: int = 2,
        *,
        board_class: str | None = None,
        quality_gates: dict | None = None,
        strict: bool = False,
        strict_kicad: bool = False,
        fab_profile: str | None = None,
        require_passive_voltage_ratings: bool = False,
        require_passive_power_ratings: bool = False,
        strict_jit_lookups: bool = False,
        strict_passive_catalog_fields: bool = False,
        min_test_points: int | None = None,
        release_tag: str | None = None,
        build_profile: str | None = None,
        compile_goal: str | None = None,
        bom_profile: str | None = None,
        strict_footprint_pin_pad_match: bool = False,
        max_jlc_extended_parts: int | None = None,
        warn_jlc_extended_parts: bool = False,
        write_manifest_sha256_sidecar: bool = False,
        declared_supply_voltages_v: dict[str, float] | None = None,
        require_cap_voltage_derating_ratio: float | None = None,
        ambient_operating_temp_c: float | None = None,
        cap_voltage_rating_reference_temp_c: float = 85.0,
        cap_voltage_temp_derating_percent_per_c: float | None = None,
        require_inductor_voltage_ratings: bool = False,
        require_test_point_on_nets: tuple[str, ...] | list[str] | None = None,
        test_point_min_count_by_net: dict[str, int] | None = None,
        strict_passive_attributes_json: bool = False,
        require_resistor_voltage_ratings: bool = False,
        max_jlc_basic_parts: int | None = None,
        jlc_class_line_limits: dict[str, int] | None = None,
        power_net_prefixes: tuple[str, ...] | list[str] | None = None,
    ):
        if strict:
            strict_kicad = True
            strict_jit_lookups = True
        self.size_mm = size_mm
        self.layers = layers
        #: Target board class/profile (future: drives placement/routing policies and strict gates).
        #: Examples: ``digital_2layer``, ``power_motor``, ``highspeed``, ``rf``, ``mixedsignal``.
        self.board_class: str = str(board_class or "generic").strip() or "generic"
        #: Quality gate config (compiler loop scaffold). Keys are intentionally free-form in Phase 0.
        #: Later phases will standardize schema and surface it in CLI/manifest.
        self.quality_gates: dict = dict(quality_gates) if quality_gates else {}
        # Merge profile defaults (explicit gates override defaults).
        try:
            from openhac.compiler.board_profiles import resolve_board_profile

            prof = resolve_board_profile(self.board_class)
            merged = dict(prof.default_quality_gates or {})
            merged.update(self.quality_gates)
            self.quality_gates = merged
        except Exception:
            pass
        self.modules = []
        self.constraints = []
        #: When True, :attr:`strict_kicad` and :attr:`strict_jit_lookups` were both enabled (LIB-003 umbrella).
        self.strict: bool = bool(strict)
        #: Optional fab pack name (e.g. ``"jlc"``) merged into DRC geometry defaults (MFG-004).
        self.fab_profile = fab_profile
        #: When True, :func:`run_drc` requires DB ``voltage_rating`` for capacitor-class parts (REL-001).
        self.require_passive_voltage_ratings = require_passive_voltage_ratings
        #: Optional map **net name (case-insensitive)** → nominal DC volts for REL-001 derating (see :attr:`require_cap_voltage_derating_ratio`).
        self.declared_supply_voltages_v: dict[str, float] | None = (
            dict(declared_supply_voltages_v) if declared_supply_voltages_v else None
        )
        #: When set (>0), :func:`run_drc` requires cap ``voltage_rating`` ≥ ratio × nominal rail for caps on declared nets (REL-001).
        self.require_cap_voltage_derating_ratio: float | None = (
            float(require_cap_voltage_derating_ratio)
            if require_cap_voltage_derating_ratio is not None
            else None
        )
        #: Optional ambient for REL-001 cap derating (used only with :attr:`cap_voltage_temp_derating_percent_per_c`).
        self.ambient_operating_temp_c: float | None = (
            float(ambient_operating_temp_c) if ambient_operating_temp_c is not None else None
        )
        #: Catalog voltage-rating reference temperature (°C) for MLCC-style parts; default 85°C.
        self.cap_voltage_rating_reference_temp_c: float = float(cap_voltage_rating_reference_temp_c)
        #: Percent added to required derated voltage per °C above :attr:`cap_voltage_rating_reference_temp_c`
        #: when :attr:`ambient_operating_temp_c` is set (REL-001 temperature margin). ``None`` disables.
        self.cap_voltage_temp_derating_percent_per_c: float | None = (
            float(cap_voltage_temp_derating_percent_per_c)
            if cap_voltage_temp_derating_percent_per_c is not None
            else None
        )
        #: When True, :func:`run_drc` requires DB ``power_watts`` for resistor-class parts (REL-001).
        self.require_passive_power_ratings = require_passive_power_ratings
        #: When True, :func:`run_drc` requires positive DB ``voltage_rating`` for inductor-class parts (REL-001).
        self.require_inductor_voltage_ratings = bool(require_inductor_voltage_ratings)
        #: When True, medium-confidence JIT parts raise unless risky lookups are allowed (LIB-003).
        self.strict_jit_lookups = strict_jit_lookups
        #: When True, :func:`run_drc` requires DB ``tolerance`` for resistor-class parts (LIB-006).
        self.strict_passive_catalog_fields = strict_passive_catalog_fields
        #: When True, :func:`run_drc` requires parseable JSON in DB ``attributes_json`` for R/C/L-class parts (LIB-006).
        self.strict_passive_attributes_json = bool(strict_passive_attributes_json)
        #: When True, :func:`run_drc` requires positive DB ``voltage_rating`` for resistor-class parts (REL-001).
        self.require_resistor_voltage_ratings = bool(require_resistor_voltage_ratings)
        #: When set (>= 0), :func:`run_drc` requires at least this many test-point components (REL-003).
        self.min_test_points: int | None = min_test_points
        #: Optional release label for compile manifest (STR-002); env ``OPENHAC_RELEASE_TAG`` overrides if set in manifest writer.
        self.release_tag: str | None = release_tag
        #: Optional profile name for manifest (e.g. ``production``); env ``OPENHAC_BUILD_PROFILE`` also supported.
        self.build_profile: str | None = build_profile
        #: Compile gating policy: ``handoff`` (reviewable KiCad artifacts) vs ``fabrication`` (stricter pass/fail).
        #: Env ``OPENHAC_COMPILE_GOAL`` overrides when set for the run.
        _cg_env = os.environ.get("OPENHAC_COMPILE_GOAL", "").strip()
        self.compile_goal: str = _normalize_compile_goal(_cg_env or compile_goal)
        #: Optional BOM labeling profile: ``prod`` / ``production`` / ``cm`` strips internal & alternate columns from CSV (LIB-004).
        _bp = bom_profile
        if isinstance(_bp, str):
            _bp = _bp.strip() or None
        else:
            _bp = None
        self.bom_profile: str | None = _bp
        rtp = require_test_point_on_nets
        if not rtp:
            self.require_test_point_on_nets: tuple[str, ...] = ()
        else:
            self.require_test_point_on_nets = tuple(
                str(x).strip().lower() for x in rtp if str(x).strip()
            )
        tpm = test_point_min_count_by_net
        if tpm:
            self.test_point_min_count_by_net: dict[str, int] = {}
            for k, v in tpm.items():
                ks = str(k).strip().lower()
                if not ks:
                    continue
                try:
                    self.test_point_min_count_by_net[ks] = int(v)
                except (TypeError, ValueError) as e:
                    raise ValueError(
                        f"test_point_min_count_by_net[{k!r}] must be an integer, got {v!r}"
                    ) from e
            if not self.test_point_min_count_by_net:
                self.test_point_min_count_by_net = None
        else:
            self.test_point_min_count_by_net: dict[str, int] | None = None
        #: Copper pour intent for manifest / PCB handoff (PCB-009): ``net``, ``layer``, ``purpose``.
        self._copper_pour_intents: list[dict] = []
        #: Mounting hole intent (PCB-010): ``x_mm``, ``y_mm``, ``diameter_mm``, optional ``note``.
        self._mounting_hole_intents: list[dict] = []
        #: External DFM checklist paths (MFG-004): ``path``, ``role``, optional ``documentation_note``.
        self._dfm_references: list[dict] = []
        #: Optional net roles for documentation / manifest (SIG-006): list of ``{"net", "role"}``.
        self._net_roles: list[dict] = []
        #: Optional length-match groups for manifest (SIG-005): list of ``{"name", "nets"}``.
        self._length_match_groups: list[dict] = []
        #: Optional stackup / dielectric handoff paths for manifest (PCB-004 / SIG-001): ``{"path", "role"}``.
        self._stackup_references: list[dict] = []
        #: Optional analog/mixed-signal merge handoff for manifest (SIG-006): ``{"net_a", "net_b", "via"}``.
        self._net_merge_hints: list[dict] = []
        #: Keepout intent records (PCB keepout stretch): ``{"x_mm","y_mm","w_mm","h_mm","layers","purpose"}``.
        self._keepout_rect_intents: list[dict] = []
        #: Net-tie intents (SIG-006 / PCB): ``{"net_a","net_b","x_mm","y_mm","footprint","note"}``.
        self._net_tie_intents: list[dict] = []
        #: Net object identities (`id(net)`) that require PWR_FLAG in ERC (SCH-004).
        self._explicit_power_net_ids: set[int] = set()
        #: Optional power rail documentation records for manifest / handoff (SCH-004): ``{"rail_name", "net"}``.
        self._power_rail_intents: list[dict] = []
        #: Optional rail conversion intents for ERC power propagation (PWR-002).
        #: Records ``{"input_rail", "output_rail", "efficiency"}`` with rails as provided (case-sensitive).
        self._rail_conversions: list[dict] = []
        #: Callables ``fn(board) -> list[str]`` appended to ERC violations (SCH-005).
        self._erc_hooks: list = []
        #: Net names that must not be autorouted (PCB-007); when non-empty, :meth:`compile` skips FreeRouting.
        self._no_autoroute_net_names: list[str] = []
        #: If set, DRC IPC check uses this as the design minimum trace width (mm) instead of the global default.
        self.min_trace_width_mm: float | None = None
        #: If set, :func:`run_drc` fails when the BOM/SKiDL graph has more than this many **Extended** JLC
        #: assembly-class line items (``JLC_Class`` field, case-insensitive) — LIB-005 optional policy.
        self.max_jlc_extended_parts: int | None = max_jlc_extended_parts
        #: If set, DRC fails when BOM lines with **Basic** JLC class exceed this count (LIB-005).
        self.max_jlc_basic_parts: int | None = max_jlc_basic_parts
        #: Optional per-``JLC_Class`` line budgets (LIB-005): keys are normalized lowercase (``\"basic\"``,
        #: ``\"extended\"``, any other assembly label, or ``\"unset\"`` for empty field). Overrides
        #: :attr:`max_jlc_basic_parts` / :attr:`max_jlc_extended_parts` for keys present in this dict.
        _jcl = jlc_class_line_limits
        if _jcl:
            self.jlc_class_line_limits: dict[str, int] = {}
            for _k, _v in _jcl.items():
                _nk = str(_k).strip().lower() or "unset"
                self.jlc_class_line_limits[_nk] = int(_v)
        else:
            self.jlc_class_line_limits: dict[str, int] | None = None
        #: When True, :func:`generate_layout` raises if any SKiDL pin number is missing from the footprint
        #: ``.kicad_mod`` pad list (PCB-002 strict pin↔pad parity).
        self.strict_footprint_pin_pad_match = bool(strict_footprint_pin_pad_match)
        #: When True, :func:`run_drc` logs a warning if any BOM line has JLC_Class Extended (LIB-005).
        self.warn_jlc_extended_parts = bool(warn_jlc_extended_parts)
        #: When True (or env ``OPENHAC_MANIFEST_SHA256_SIDECAR``), emit ``*.openhac-manifest.json.sha256``.
        self.write_manifest_sha256_sidecar = bool(write_manifest_sha256_sidecar)
        #: When True, KiCad symbol load failures raise instead of synthetic parts (LIB-004). Does **not** mutate
        #: :class:`Component` class attributes; use :meth:`Module.add_part` or CLI/env so construction sees policy.
        self.strict_kicad = strict_kicad
        pnp = power_net_prefixes
        if pnp:
            self.power_net_prefixes: tuple[str, ...] = tuple(str(x).strip().lower() for x in pnp if str(x).strip())
        else:
            self.power_net_prefixes = ()

    def effective_compile_goal(self) -> str:
        """Return the compile goal, honoring env override."""
        env = os.environ.get("OPENHAC_COMPILE_GOAL", "").strip()
        return _normalize_compile_goal(env or getattr(self, "compile_goal", None))

    def _propagate_board_ref(self, module):
        """Stamp *module* and nested :class:`Module` children with ``_openhac_host_board`` (this board)."""
        from openhac.core.base import Module

        module._openhac_host_board = self
        for c in module:
            if isinstance(c, Module):
                self._propagate_board_ref(c)

    def connect(self, intf1, intf2):
        if hasattr(intf1, 'connect') and hasattr(intf2, 'connect'):
            intf1.connect(intf2)
        else:
            intf1 += intf2

    def add_module(self, module):
        self._propagate_board_ref(module)
        self.modules.append(module)

    def declare_power_rail(self, rail_name: str, net):
        """Mark *net* as a power rail for ERC (SCH-004). *rail_name* is for documentation only.

        Nets registered here are subject to the same PWR_FLAG requirement as prefix-named rails.
        """
        rn = str(rail_name or "").strip()
        nn = str(getattr(net, "name", net))
        self._power_rail_intents.append({"rail_name": rn or nn, "net": nn})
        self._explicit_power_net_ids.add(id(net))
        return net

    def declare_rail_conversion(
        self,
        input_rail: str,
        output_rail: str,
        *,
        efficiency: float = 0.9,
    ) -> dict:
        """Declare a rail conversion (e.g. buck) for ERC power budgeting (PWR-002).

        This is an **intent** hint: ERC will treat the output rail supply as being sourced from the input rail
        (subject to declared rail voltages and efficiency).
        """
        rec = {
            "input_rail": str(input_rail),
            "output_rail": str(output_rail),
            "efficiency": float(efficiency),
        }
        self._rail_conversions.append(rec)
        return rec

    def register_erc_hook(self, fn):
        """Register ``fn(board) -> list[str]``; returned messages become ERC failures (SCH-005)."""
        self._erc_hooks.append(fn)

    def apply_erc_plugin(self, name: str, *args, **kwargs):
        """Apply a named ERC pack or custom plugin from :mod:`openhac.stdlib.erc_plugin_registry` (SCH-005)."""
        from openhac.stdlib.erc_plugin_registry import apply_erc_plugin

        apply_erc_plugin(self, name, *args, **kwargs)

    def declare_net_role(self, net, role: str):
        """Record a semantic role for *net* (e.g. ``analog_ground``) for the compile manifest (SIG-006)."""
        self._net_roles.append({"net": str(getattr(net, "name", "?")), "role": str(role)})
        return net

    def declare_net_merge_hint(self, net_a, net_b, via: str):
        """Document intended star-point / ferrite merge between two nets (SIG-006).

        Stretch: if *via* indicates a net-tie, OpenHaC also records a ``declare_net_tie`` intent so the
        generated PCB can include a physical net-tie footprint when pcbnew is available.
        """
        rec = {
            "net_a": str(getattr(net_a, "name", net_a)),
            "net_b": str(getattr(net_b, "name", net_b)),
            "via": str(via),
        }
        self._net_merge_hints.append(rec)

        via_s = str(via or "").strip().lower()
        if "net_tie" in via_s or "nett ie" in via_s or "net-tie" in via_s:
            try:
                self.declare_net_tie(net_a, net_b, note=f"from declare_net_merge_hint(via={via!r})")
            except Exception:
                pass
        return (net_a, net_b)

    def register_length_match_group(self, name: str, nets: list):
        """Declare nets intended for length matching; emitted in manifest only (SIG-005)."""
        self._length_match_groups.append(
            {
                "name": str(name),
                "nets": [str(getattr(n, "name", "?")) for n in nets],
            }
        )

    def declare_stackup_reference(
        self,
        path: str | os.PathLike[str],
        *,
        role: str = "stackup_documentation",
        documentation_note: str | None = None,
    ):
        """Record a human-edited stackup or fab dielectric file for the compile manifest (PCB-004 / SIG-001)."""
        rec: dict = {"path": str(Path(path)), "role": str(role)}
        if documentation_note is not None and str(documentation_note).strip():
            rec["documentation_note"] = str(documentation_note).strip()
        self._stackup_references.append(rec)
        return path

    def declare_no_autoroute_net(self, net):
        """Mark *net* as off-limits to OpenHaC FreeRouting (PCB-007); compile skips autoroute if any are set."""
        self._no_autoroute_net_names.append(str(getattr(net, "name", net)))
        return net

    def declare_copper_pour_intent(self, net, *, layer: str = "F.Cu", purpose: str = "ground"):
        """Record GND/pour intent for KiCad zone authoring (PCB-009); documentation handoff only."""
        self._copper_pour_intents.append(
            {
                "net": str(getattr(net, "name", net)),
                "layer": str(layer),
                "purpose": str(purpose),
            }
        )
        return net

    def declare_mounting_hole(self, x_mm: float, y_mm: float, diameter_mm: float, *, note: str | None = None):
        """Record mechanical hole intent for fab drawing / KiCad (PCB-010); no geometry emitted yet."""
        rec: dict = {
            "x_mm": float(x_mm),
            "y_mm": float(y_mm),
            "diameter_mm": float(diameter_mm),
        }
        if note is not None and str(note).strip():
            rec["note"] = str(note).strip()
        self._mounting_hole_intents.append(rec)
        return rec

    def declare_keepout_rect(
        self,
        x_mm: float,
        y_mm: float,
        w_mm: float,
        h_mm: float,
        *,
        layers: tuple[str, ...] = ("F.Cu", "B.Cu"),
        purpose: str = "copper_tracks_vias",
        note: str | None = None,
    ) -> dict:
        """Record a rectangular keepout intent (stretch).

        This is used for pcbnew rule areas / keepout zones in the generated PCB when pcbnew is available.
        """
        rec: dict = {
            "x_mm": float(x_mm),
            "y_mm": float(y_mm),
            "w_mm": float(w_mm),
            "h_mm": float(h_mm),
            "layers": [str(x) for x in layers] if layers else ["F.Cu", "B.Cu"],
            "purpose": str(purpose),
        }
        if note is not None and str(note).strip():
            rec["note"] = str(note).strip()
        self._keepout_rect_intents.append(rec)
        return rec

    def declare_net_tie(
        self,
        net_a,
        net_b,
        *,
        x_mm: float | None = None,
        y_mm: float | None = None,
        footprint: str = "NetTie:NetTie-2_SMD_Pad2.0mm",
        note: str | None = None,
    ) -> dict:
        """Declare a net-tie footprint intent bridging *net_a* and *net_b* (stretch).

        This is primarily used for mixed-signal ground tying (SIG-006) and will be emitted to the PCB
        when pcbnew is available.
        """
        rec: dict = {
            "net_a": str(getattr(net_a, "name", net_a)),
            "net_b": str(getattr(net_b, "name", net_b)),
            "footprint": str(footprint),
        }
        if x_mm is not None and y_mm is not None:
            rec["x_mm"] = float(x_mm)
            rec["y_mm"] = float(y_mm)
        if note is not None and str(note).strip():
            rec["note"] = str(note).strip()
        self._net_tie_intents.append(rec)
        return rec

    def declare_dfm_reference(
        self,
        path: str | os.PathLike[str],
        *,
        role: str = "dfm_checklist",
        documentation_note: str | None = None,
    ):
        """Link an external DFM / fab checklist file (MFG-004); manifest handoff only."""
        rec: dict = {"path": str(Path(path)), "role": str(role)}
        if documentation_note is not None and str(documentation_note).strip():
            rec["documentation_note"] = str(documentation_note).strip()
        self._dfm_references.append(rec)
        return path

    def constrain_distance_min(self, item_a, item_b, min_distance_mm):
        self.constraints.append({'type': 'distance_min', 'args': (item_a, item_b, min_distance_mm)})

    def constrain_exact_center(self, item):
        self.constraints.append({'type': 'exact_center', 'args': (item,)})

    def route_differential_pair(self, p_net, n_net, target_impedance_ohms=90):
        self.constraints.append({
            'type': 'diff_pair', 
            'args': (p_net, n_net, target_impedance_ohms)
        })

    def constrain_distance_max(self, mod_a, mod_b, max_mm):
        self.constraints.append({'type': 'distance_max', 'args': (mod_a, mod_b, max_mm)})

    def constrain_edge(self, mod, edge):
        self.constraints.append({'type': 'edge', 'args': (mod, edge)})

    def _validate_interfaces(self):
        """Check that every net in every required interface has >= 2 pins attached."""
        for module in self.modules:
            for iface_name, interface in module.required_interfaces.items():
                for net in interface.signals:
                    try:
                        pins = list(net.get_pins()) if hasattr(net, "get_pins") else [net]
                    except Exception:
                        pins = []
                    if len(pins) < 2:
                        raise UnconnectedInterfaceError(
                            f"Module '{module.name}', interface '{iface_name}': "
                            f"net '{getattr(net, 'name', '?')}' has fewer than 2 pins attached."
                        )

    def _get_all_modules(self):
        """Recursively gather all unique Module instances in the design."""
        all_mods = []
        seen = set()

        def _walk(mod):
            if id(mod) in seen:
                return
            seen.add(id(mod))
            all_mods.append(mod)
            for child in mod:
                if isinstance(child, Module):
                    _walk(child)

        for m in self.modules:
            _walk(m)
        return all_mods

    def compile(
        self,
        project_name: str = "board",
        generate_bom: bool = True,
        auto_route: bool = True,
        export_schematic: bool = False,
        *,
        allow_risky_part_lookups: bool = False,
        kicad_sch_erc: bool = False,
        kicad_sch_erc_format: str = "report",
        source_script_path: str | os.PathLike[str] | None = None,
        output_dir: str | os.PathLike[str] | None = None,
        release_zip_path: str | os.PathLike[str] | None = None,
    ):
        if kicad_sch_erc and not export_schematic:
            raise ValueError("kicad_sch_erc=True requires export_schematic=True")
        self.all_modules = self._get_all_modules()

        from openhac.core.compile_context import OpenHaCCompileContext, compile_context_reset, compile_context_set
        from openhac.compiler.compile_pipeline import DEFAULT_COMPILE_PHASES, CompileState, run_compile_loop

        # Deterministic mode: seed Python RNG so any downstream library randomness
        # (e.g. SKiDL tags) is stable across runs with identical construction order.
        try:
            det = os.environ.get("OPENHAC_DETERMINISTIC", "").strip().lower() in ("1", "true", "yes", "on")
            if det:
                import hashlib
                import random

                seed = int(hashlib.sha256(str(project_name).encode("utf-8")).hexdigest()[:8], 16)
                random.seed(seed)
        except Exception:
            pass

        ctx = OpenHaCCompileContext(self, allow_risky_part_lookups=allow_risky_part_lookups)
        tok = compile_context_set(ctx)
        try:
            state = CompileState(
                board=self,
                project_name=project_name,
                generate_bom=generate_bom,
                auto_route=auto_route,
                export_schematic=export_schematic,
                allow_risky_part_lookups=allow_risky_part_lookups,
                kicad_sch_erc=kicad_sch_erc,
                kicad_sch_erc_format=kicad_sch_erc_format,
                source_script_path=source_script_path,
                output_dir=output_dir,
                release_zip_path=release_zip_path,
            )
            max_attempts = int(getattr(self, "quality_gates", {}).get("max_attempts", 1) or 1)
            run_compile_loop(state, generate_phases=DEFAULT_COMPILE_PHASES, max_attempts=max_attempts)
        except Exception as e:
            logger.error("COMPILER ABORTED DUE TO PHYSICS RULES OR PIPELINE ERROR: %s", e)
            raise
        finally:
            compile_context_reset(tok)

    def simulate(
        self,
        project_name: str = "simulation",
        *,
        allow_risky_part_lookups: bool = False,
        spice_analysis_lines: list[str] | None = None,
        spice_analysis_json_path: str | os.PathLike[str] | None = None,
        output_dir: str | os.PathLike[str] | None = None,
        run_ngspice: bool = False,
        ngspice_log_path: str | os.PathLike[str] | None = None,
        require_spice_models: bool = False,
    ):
        logger.info(f"Preparing to simulate analog hardware graph: {project_name}")

        from openhac.core.compile_context import OpenHaCCompileContext, compile_context_reset, compile_context_set

        ctx = OpenHaCCompileContext(self, allow_risky_part_lookups=allow_risky_part_lookups)
        tok = compile_context_set(ctx)
        try:
            from openhac.compiler.rule_check import run_erc

            run_erc(self)
            from openhac.compiler.spice_gen import generate_spice
            from openhac.circuit import get_default_circuit

            analysis_lines = spice_analysis_lines
            if analysis_lines is None and spice_analysis_json_path is not None:
                from openhac.compiler.spice_analysis_config import (
                    load_spice_analysis_raw,
                    resolve_spice_analysis_from_mapping,
                )

                raw = load_spice_analysis_raw(Path(spice_analysis_json_path))
                al2, preset_name = resolve_spice_analysis_from_mapping(raw)
                if al2 is not None:
                    analysis_lines = al2
                else:
                    from openhac.compiler.spice_presets import preset_analysis_lines

                    assert preset_name is not None
                    analysis_lines = preset_analysis_lines(preset_name)

            cir_path = _artifact_path(project_name, ".cir", output_dir)
            if require_spice_models:
                try:
                    from openhac.compiler.spice_gen import spice_model_coverage_summary

                    s = spice_model_coverage_summary(get_default_circuit())
                    need = int(s.get("parts_requiring_models", 0) or 0)
                    have = int(s.get("parts_with_models", 0) or 0)
                    if need > have:
                        raise ValueError(
                            f"SPICE model coverage gate failed: {have}/{need} model-required parts "
                            f"have Spice_Subckt annotations."
                        )
                except Exception as e:
                    raise
            generate_spice(cir_path, analysis_lines=analysis_lines)
            if run_ngspice:
                from openhac.compiler.ngspice_runner import run_ngspice_headless

                lp = ngspice_log_path
                if lp is None and output_dir is not None:
                    lp = _artifact_path(project_name, ".cir.ngspice.log", output_dir)
                run_ngspice_headless(cir_path, log_path=lp)
        except Exception as e:
            logger.error("SIMULATION ABORTED DUE TO PHYSICS RULES!")
            raise e
        finally:
            compile_context_reset(tok)
