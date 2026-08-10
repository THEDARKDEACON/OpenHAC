# OpenHaC software architecture (maintainer notes)

This document captures **cross-cutting software design** that complements numbered items in [PRODUCTION_READINESS_SPEC.md](./PRODUCTION_READINESS_SPEC.md) (Phase-1) and [FABRICATION_READINESS_SPEC.md](./FABRICATION_READINESS_SPEC.md) (Phase-2).

## Compile context (no global `Component` stomp)

- **`Board.__init__` does not set** `Component.require_kicad_symbols` or `Component.strict_jit_lookups`. Sequential `Board(...)` constructions in one process no longer flip class-wide behavior.
- **`openhac.core.compile_context`**: `Board.compile` / `Board.simulate` install an `OpenHaCCompileContext` (contextvars) for **allow-risky** resolution during those calls.
- **Host board on modules**: `Board.add_module` stamps `_openhac_host_board` on the module subtree. **`Module.add_part("Generic")`** constructs a `Component` with `parent_module=self` so **`board.strict_kicad` / `strict_jit_lookups`** apply **during** `Component.__init__`. Plain `module.add(Component(...))` still runs `Component.__init__` before the module link exists; for strict-at-construction behavior, prefer **`add_part`** or pass **`parent_module=`** (keyword-only).
- **CLI** still may set **`Component` class attributes** before executing the user script (legacy path); it also copies **`--strict-kicad` / `--production` / `--strict-jit`** onto the **`board` instance** before `board.compile(...)`.

## Hardware tree iteration

- **`Module.__iter__`** yields direct children. **ERC/DRC** walks use `for child in module:` instead of hard-coding only the attribute name `components` on internal walks (subclasses can override `__iter__` for alternate storage).

## Compile pipeline

- **`openhac.compiler.compile_pipeline`**: ordered phases (`CompileState`, `DEFAULT_COMPILE_PHASES`) invoked from `Board.compile`. Easier to test and to swap phases later.

## Schematic pin order

- **`schematic_gen`**: non-numeric pin numbers use an **alphanumeric natural key** (e.g. **A2** before **A10**) to reduce crossing-wire risk from arbitrary ordering.
- Debug toggle: set **`OPENHAC_SCHEMATIC_STUB_ONLY=1`** to force stub-only pin offsets (ignore `.kicad_sym` pin `(at)` positions) for deterministic baselines / bisecting endpoint movement.

## JIT / API matching

- **`api_fallback._query_matches_item`**: optional **category slug** alignment when the API returns category metadata; **word-boundary** matching on description tokens (length ≥ 3) to reduce false positives from unrelated phrases.

## Power net naming (SCH-004)

- **`Board(power_net_prefixes=(...))`** extends default prefix heuristics alongside **`declare_power_rail`**.
- **`{project}.openhac-power-rails.json`** records explicitly declared rails (documentation/CM handoff only; no KiCad pin-type inference).

## Mixed-signal ground intent (SIG-006)

- **`Board.declare_net_role(net, "analog_ground"|"digital_ground"|...)`** and **`declare_net_merge_hint(net_a, net_b, via=...)`** are emitted for layout/SI handoff.
- **DRC** warns when both **analog_ground** and **digital_ground** are declared but no merge hint bridges them; in **`Board(strict=True)`** this becomes a DRC failure. (This is documentation/enforcement only; pcbnew net-tie/zone automation remains future.)

## JLC assembly class policy (LIB-005)

- **`Board(max_jlc_extended_parts=…)`**, **`max_jlc_basic_parts`**, and optional **`jlc_class_line_limits`** (map of normalized class → max line count, plus **`"unset"`** for empty **`JLC_Class`**) feed **`run_drc`**. Per-class dict entries override the scalar caps for the same class when both are set.

## Reliability policy (REL-001)

- Capacitor voltage derating uses **`require_cap_voltage_derating_ratio`** × nominal rail from **`declared_supply_voltages_v`**. Optional **temperature margin**: set **`ambient_operating_temp_c`** and **`cap_voltage_temp_derating_percent_per_c`** together; required voltage is multiplied by `1 + (pct/100) × max(0, Ta − Tref)` with **`cap_voltage_rating_reference_temp_c`** (default 85°C) as catalog-rating reference.

## Compile manifest (STR-002 handoff)

The JSON manifest written after a successful compile is the primary **audit trail**: `openhac_version`, optional `git_*`, `compile_pipeline_phases` + `compile_pipeline_phase_count`, `sch_pin_sort_mode` (**SCH-001**), `erc_plugin_hook_count`, `compile_manifest_emitter` / `compile_pipeline_module` / `str002_cli_module` (**STR-002**), `str002_compile_pipeline_entry`, `str002_openhac_distribution_package`, `str002_manifest_json_sort_keys`, `str002_patch_manifest_release_zip_function`, `mfg005_zip_project_outputs_function`, `str002_rule_check_module`, `str002_layout_gen_module`, `str002_autoroute_module`, `str002_kicad_sch_erc_module`, `str002_kicad_erc_report_module`, `str002_schematic_gen_module`, `str002_spice_gen_module`, `str002_project_gen_module`, `str002_compile_state_dataclass`, `str002_manifest_json_suffix`, `str002_manifest_sha256_sidecar_suffix`, `str002_layout_constraints_module`, `str002_pcb_placement_module`, `str002_compile_manifest_module`, `str002_version_info_module`, `str002_core_board_module` / `str002_core_base_module` / `str002_core_compile_context_module`, `str002_compile_pipeline_default_phases_symbol`, `str002_openhac_version_info_function` / `str002_openhac_user_agent_function` (**SW-004** audit strings), `str002_stdlib_erc_rules_module` (**SCH-005** hook library path), `mfg001_export_fab_module` (**MFG-001**), `sw003_netlist_gen_module` (**SW-003**), `sw005_circuit_public_module` (**SW-005**), `netlist_line_count` / `netlist_suffix` / `source_input.line_count`, `pcb_pipeline_handoff_key_count`, `compile_env_flags` (`OPENHAC_*` toggles for **LIB-003** / **SW-006**), `sw006_skip_layout_env_key` (**SW-006**), optional `kicad_cli_version`, optional `pcb_routing_handoff_json_sha256`, `pcb_routing_handoff_writer` (**PCB-007**), `outputs_total_bytes` / `outputs_artifact_count`, `bom_csv_column_names` / `bom_csv_data_row_count` (when BOM emitted), `lib001_bom_offer_column_names` (**LIB-001**), `lib002_bom_csv_suffix` (**LIB-002**), `lib004_bom_prod_omitted_column_count` (**LIB-004**), `spice_presets_catalog` (**SIM-002**), `spice_presets_module`, `sim002_spice_netlist_suffix`, `sim002_resolve_spice_analysis_function`, `sim002_spice_cli_flags` + `sim002_default_analysis_note` + `sim002_spice_analysis_config_module` + `sim002_spice_analysis_loader_function` (**SIM-002**), `sim001_spice_database_fields` (**SIM-001**), `sch003_schematic_erc_cli` + `sch003_kicad_erc_report_suffixes` (**SCH-003**), `sch001_kicad_sch_suffix` / `sch001_kicad_pro_suffix`, `sch_kicad_symbol_dirs_configured` + `sch_kicad_symbol_search_paths` (**SCH-001**), `pcb_kicad_footprint_dirs_configured` + `pcb_kicad_footprint_search_paths` (**PCB-001**), `sch001_kicad_sym_pinpos_module` (**SCH-001**), `sch001_pinpos_report_writer` + `sch001_pinpos_report_schema` / `{project}.openhac-sch-pinpos-report.json` (**SCH-001**), `pcb001_kicad_pcb_suffix` (**PCB-001**), `sch005_erc_rules_module` (**SCH-005**), `sig001_stackup_template_reference` (**SIG-001**), `sig002_diff_pair_intent_disclaimer` (**SIG-002**), `sig002_diff_pair_constraints_writer` + optional `sig002_diff_pair_constraints_schema` / `{project}.openhac-diff-pair-constraints.json` (**SIG-002**), `sig005_length_match_constraints_writer` + optional `sig005_length_match_constraints_schema` / `{project}.openhac-length-match-constraints.json` (**SIG-005**), `sig006_mixed_signal_handoff_writer` + optional `sig006_mixed_signal_handoff_schema` / `{project}.openhac-mixed-signal-constraints.json` (**SIG-006**), `lib003_jit_bom_columns` (**LIB-003**), `lib003_database_api_fallback_module` (**LIB-003** JIT matcher path), `lib004_prod_bom_profile_active` (**LIB-004** when prod BOM), `fab_profiles_catalog` (**MFG-004**), `mfg003_fab_handoff_markdown_suffix` (**MFG-003**), `no_autoroute_net_count` (**PCB-007**), optional `pcb007_netclass_suggestion_count` / `pcb007_netclass_hint_writer` / `{project}.openhac-netclass-hint.md` (**PCB-007** netclass suggestions; `netclass_suggestions` in routing handoff JSON), `pcb007_no_autoroute_constraints_writer` + optional `pcb007_no_autoroute_constraints_schema` / `{project}.openhac-no-autoroute-constraints.json` (**PCB-007**), `pcb_auxiliary_handoff_writer` + optional `pcb_auxiliary_handoff_schema` / `{project}.openhac-pcb-auxiliary-constraints.json` (**PCB-009** / **PCB-010**), `pcb004_stackup_handoff_writer` + optional `pcb004_stackup_handoff_schema` / `{project}.openhac-stackup-handoff.json` (**PCB-004**), `pcb009_copper_pour_handoff_note` (**PCB-009**), `pcb010_mounting_hole_handoff_note` (**PCB-010**), `release_bundle_suffix_count`, **optional** `release_zip_sha256` + `mfg005_release_zip_sha256_note` (**MFG-005**), `bom_alternates_schema` / `bom_alternates_generic_count` / `bom_alternates_total_rows` when alternates JSON exists (**LIB-002**), `mfg001_fab_export_cli` / `mfg002_assembly_export_cli` (**MFG-001** / **MFG-002** hint strings), `rel003_test_point_net_names` / `rel003_test_point_min_count_by_net` when set (**REL-003**), `rel001_reliability_policy_key_catalog` (**REL-001**), `logical_module_names` + `logical_module_reference_total` (**SCH-002**), `dfm_reference_count`, `stackup_json_summaries_count`, `pcb_pipeline_handoff.schema_ref`, `pwr002_stdlib_helpers_catalog`, `pwr002_stdlib_power_module` (**PWR-002**), `pwr002_rail_conversions_handoff_writer` + optional `pwr002_rail_conversions_handoff_schema` / `{project}.openhac-rail-conversions.json` (**PWR-002**), `str002_release_bundle_module` (**MFG-005** zip implementation), `str002_stdlib_passives_module` (**LIB-006** catalog path), `str002_netlist_gen_generate_function`, `str002_rule_check_run_erc_function` / `str002_rule_check_run_drc_function`, `lib003_db_manager_module`, `lib003_sync_jlc_module`, `sim002_spice_presets_preset_analysis_lines_function` (**SIM-002** preset lookup), `reliability_policy` (**REL-001** / **REL-003** when set), `jlc_line_policy` (**LIB-005**), `lib006_passive_catalog_policy` (**LIB-006**), and geometry / stackup / SI summaries for **PCB-004**, **SIG-005**, **SIG-006**, **MFG-004**.

## ERC example hooks (SCH-005)

`openhac.stdlib.erc_rules` provides opt-in `register_erc_hook` helpers (I2C, 1-Wire, UART RX, SPI CS / WP# / HOLD# / MISO, reset, MDIO, SWDIO, JTAG TMS / TCK, CAN RX, Ethernet PHY INT#, RS485 RE#, SD CMD / SD CD, LIN bus, power-good open-drain, I2S WS, HDMI CEC / HPD, stepper DIR, USB OTG ID, USB VBUS sense, PCIe WAKE#, RTC INT#, SMBus ALERT, sensor INT, missing footprint, …). They are **illustrative**; production rules live in project-specific hooks or future built-in packs.

**`openhac.stdlib.erc_rule_packs`** groups common hook registrations (e.g. **I2C** SDA/SCL, **SPI** CS/MISO, **SPI NOR** WP# + HOLD#, **UART + SWD**, **HDMI** CEC + HPD, **SD/MMC** CMD + CD, **JTAG** TMS + TCK, **LIN** + **RS485** RE#, **CAN RX** + **Ethernet PHY** INT#) for **SCH-005** convenience.

**`openhac.stdlib.erc_plugin_registry`** exposes those packs under stable names (e.g. `i2c_pullup_pack` maps to `apply_i2c_pullup_pack`), plus **`register_erc_plugin`** for project callables with the same `(board, *args, **kwargs)` shape. **`Board.apply_erc_plugin(name, ...)`** invokes the registry. Built-ins can be shadowed with **`register_erc_plugin(..., overwrite=True)`** when needed.

## “Next 30 tickets” (batch stance)

Full **Done** closure of every **Partial** row in [IMPLEMENTATION_STATUS.md](./IMPLEMENTATION_STATUS.md) remains a **multi-phase** program. Batches advance manifest traceability, ERC examples, CLI/simulation tests, and docs; remaining IDs stay **Partial** until acceptance criteria are met end-to-end.
