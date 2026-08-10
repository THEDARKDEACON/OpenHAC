# Implementation status (OpenHaC)

Track record of fixes applied against [PRODUCTION_READINESS_SPEC.md](./PRODUCTION_READINESS_SPEC.md) (Phase-1) and [FABRICATION_READINESS_SPEC.md](./FABRICATION_READINESS_SPEC.md) (Phase-2). Update this file when you close spec items.

### Phase-2 Fabrication Readiness (FAB-* IDs)

Normative spec: [FABRICATION_READINESS_SPEC.md](./FABRICATION_READINESS_SPEC.md). All Phase-2 IDs start **Open** until acceptance criteria land.

| Spec ID | Status | Notes |
|---------|--------|--------|
| **FAB-001** | Done | `pin_resolution.get_pins_from_data` refuses invented/corrupt pinouts under fabrication; `Component._get_pins_from_data` delegates. Tests in `tests/test_fab_phase2_gates.py`. |
| **FAB-002** | Done | Pad mismatches logged at warning; `assert_footprint_pin_pad_or_raise` auto-strict when `compile_goal=fabrication`. |
| **FAB-003** | Done | Omitted footprint refs recorded; fab place/zip refuse; export respects `OPENHAC_OMITTED_FOOTPRINT_REFS`. |
| **FAB-004** | Done | Native `openhac.core.circuit` is SoT via `get_default_circuit()`; SKiDL `builtins.default_circuit` only when `OPENHAC_LEGACY_SKIDL=1`. Dual-scan gated the same way. |
| **FAB-010** | Done | `network_allowed()` denies under fabrication unless `OPENHAC_ALLOW_NETWORK`. |
| **FAB-011** | Done | Fabrication auto-enables verified-parts gate; synthetic watermarks rejected in DRC. |
| **FAB-012** | Done | `api_cache.db` gitignored/untracked; default cache under `~/.cache/openhac/` (`OPENHAC_API_CACHE_PATH`). |
| **FAB-013** | Done | Enrich import/per-part failures recorded on `CompileState` / manifest; fab raises on import failure. |
| **FAB-020** | Done | `pcb_metrics.footprint_count` + fab_audit; place parity enforced via FAB-002/003 gates. |
| **FAB-021** | Done | `unrouted_net_count` in metrics; fab routing phase fails if unrouted > 0 unless `allow_unrouted_nets`. |
| **FAB-022** | Done | `phase_kicad_pcb_drc` already required in fabrication; report path stored for fab_audit. |
| **FAB-023** | Done | Enrich/layout paths log exceptions; fab raises on omitted footprints / pad / enrich import (incremental). |
| **FAB-030** | Done | `--production` sets fab goal, pad strict, verified parts, `OPENHAC_NO_NETWORK`, schematic off by default. |
| **FAB-031** | Done | `scripts/ci_fab_golden.py` + `kicad-fab-golden` CI job runs `export fab --zip` when `kicad-cli` present. |
| **FAB-032** | Done | Manifest `fab_audit` / `openhac.fab_audit.v1`. |
| **FAB-040** | Done | `--production` defaults schematic off; SCOPE demotes sch as SoT. |
| **FAB-041** | Done | Webview/IR documented as primary review in SCOPE / USER_GUIDE / RELEASE_CHECKLIST; CLI `--webview`. |
| **FAB-042** | Done | API stability section in `docs/API_REFERENCE.md`. |
| **FAB-050** | Done | CI: `OPENHAC_NO_NETWORK=1`; mypy hard gate on `openhac/core` + placement/layout (`--follow-imports=silent`); layout/fab golden validators blocking. |
| **FAB-051** | Done | Blocking `kicad-fab-golden` via `ci_validate_fab_gates.py --require-layout`; fixtures golden + FAB-001/FAB-003 negatives; hard `fab_audit` asserts. |


**Phase-2 open:** **0 / 20**.

### Phase-1 completion (all 48 spec IDs)

**Every numbered spec ID is marked Done** in the table below. **Done** follows the repo rule: *full target met **or** the spec was narrowed so acceptance matches shipped OpenHaC* (see **Phase-1 completion** in [PRODUCTION_READINESS_SPEC.md](./PRODUCTION_READINESS_SPEC.md)). Notes still record **stretch / future** work (multi-sheet KiCad, in-tool SI, signing, …) where aspirational text in older spec sections described a longer horizon.

### Historical note (why “Partial” existed before)

Earlier revisions used **Partial** for useful slices that did not yet meet every aspirational **Target state** paragraph. That split was retired in favor of **Phase-1 Done + explicit future notes** so the status table matches the normative completion model above.

| Spec ID | Status | Notes |
|---------|--------|--------|
| **SW-003** | Done | Netlist/BOM generation raises on failure; `Board.compile()` no longer swallows importer errors for core steps. Manifest **``sw003_netlist_gen_module``** (**``openhac.compiler.netlist_gen``**) for pipeline traceability. |
| **SW-002** | Done | `openhac compile` / `simulate` resolve a `board` variable and call `compile()` / `simulate()` with `--name`, `--no-route`, `--no-schematic`, optional `-o` / `output_dir`, and `--deterministic` (sets `OPENHAC_DETERMINISTIC=1` for the run). `compile` also supports `--skip-layout` (sets `OPENHAC_SKIP_LAYOUT=1`), `--require-verified-parts` (sets `OPENHAC_REQUIRE_VERIFIED_PARTS=1`), and `--kicad-symbol-dir` / `--kicad-footprint-dir` (sets `KICAD8_SYMBOL_DIR` / `KICAD8_FOOTPRINT_DIR` for the run). CLI also provides `openhac doctor [--json] [--strict] [--strict-headless] [--strict-layout] [--print-env]` plus global `--db-path` to set `OPENHAC_DB_PATH` for the run (affects compile/simulate/sync/seed/doctor). |
| **SW-001** | Done | GitHub Actions workflow runs Ruff + pytest on Python 3.11 and 3.12. |
| **PWR-001** | Done | Per-rail ERC: dict `source_current_max_ma` vs dict `max_current_draw_ma` by rail key; scalar draw forbidden when dict supply is used; nested scalar `source_current_max_ma` ignored under a dict-supply subtree. DRC still sums dict draws for conservative IPC width. |
| **SCH-001** | Done | **``.kicad_sym``** pin **``(at)``** lookup (**``kicad_sym_pinpos``** + **``SymbolPinResolver``**); wires/labels use library offsets when symbol libs are found on **``OPENHAC_KICAD_SYMBOL_DIRS``** / **``KICAD*_SYMBOL_DIR``**. **Stretch:** for SKiDL-native parts, OpenHaC generates a project-local **``{project}.openhac-generated.kicad_sym``** plus **``sym-lib-table``** and emits schematic `lib_id` as **``OpenHaC:<part.name>``**, so KiCad does not render `?` placeholders. Deterministic UUIDs via **``OPENHAC_DETERMINISTIC_UUIDS=1``** / **``OPENHAC_DETERMINISTIC_SCHEMATIC=1``** / **``OPENHAC_DETERMINISTIC=1``**; stable sort/order; optional pinpos report **``{project}.openhac-sch-pinpos-report.json``** (schema **``openhac.sch_pinpos_report.v1``**). Golden graph isomorphism vs KiCad pin coords still future. |
| **PCB-001** | Done | Footprints loaded from `*.pretty` via `PCB_IO_MGR.KICAD_SEXP`; refs/values and module-grid positions applied. Manifest **``pcb001_kicad_pcb_suffix``** (**``.kicad_pcb``**); manifest **``str002_pcb_placement_module``** (**``openhac.compiler.pcb_placement``**); manifest **``pcb_kicad_footprint_dirs_configured``** + **``pcb_kicad_footprint_search_paths``** record the resolved footprint roots for audit/debug. |
| **PCB-002** | Done | Pads get `NETINFO_ITEM` from SKiDL pin nets; **``pin_pad_coverage_warnings``** vs **``.kicad_mod``**; **``Board(strict_footprint_pin_pad_match=True)``** → **``generate_layout``** raises **``LayoutGenerationError``** if any connected pin lacks a matching pad name. Full KiCad ratsnest vs GUI parity not guaranteed. |
| **Layout stub** | Done | Failed `pcbnew` no longer writes a fake minimal `.kicad_pcb`; raises `LayoutGenerationError`. |
| **Z3 overlap** | Done | Non-overlap constraints use the same **all_modules** list as bounds (nested modules consistent). |
| **PCB-005** | Done | `distance_min` uses axis-aligned bbox minimum gap (`layout_constraints.add_bbox_minimum_gap`); `distance_max` uses center L1 (`add_center_l1_max`). Manifest **``str002_layout_constraints_module``** (**``openhac.compiler.layout_constraints``**). |
| **PCB-006** | Done | DRC **fails** if IPC-2152 width for `max_current_draw_ma` exceeds default `min_trace_width_mm` (0.15mm). |
| **MFG-001** | Done | ``openhac export fab <pcb> -o <dir>`` runs ``kicad-cli`` **gerbers**, **drill** (Excellon mm), **pos** (CSV mm, front+back). Optional ``--ipc2581``. Optional ``--zip`` / ``--zip-file`` zips the output directory. Manifest **``mfg001_fab_export_cli``** records the underlying **gerbers** subcommand hint; manifest **``mfg001_export_fab_module``** (**``openhac.compiler.export_fab``**). |
| **STR-001** | Done | [SCOPE.md](./SCOPE.md) defines capability tiers A–C + non-goals; README “What it does” aligned. |
| **SW-004** | Done | README + **``./RELEASE_CHECKLIST.md``**; **``scripts/verify_openhac_version.py``** + **``scripts/check_release_strings.py``** + **``scripts/check_changelog_version.py``** (``CHANGELOG.md`` **``## [version]``** vs pyproject) + CI; User-Agent / version; **``scripts/example_build.py``**; CLI **``export assembly``**, release flags. |
| **SCH-004** | Done | ``Board.declare_power_rail(name, net)`` registers net IDs; PWR_FLAG ERC applies to declared rails **or** default prefixes **or** **``Board(power_net_prefixes=...)``**; single-pin power nets are not double-reported as floating (PWR_FLAG supplies the second anchor). Optional **``{project}.openhac-power-rails.json``** (**``openhac.power_rail_handoff.v1``**) + manifest **``sch004_power_rail_handoff_*``** when rails were declared (documentation / CM checklist handoff). KiCad **functional pin types** in-tool still future. |
| **SCH-005** | Done | ``register_erc_hook``; **``uart_rx_pullup_erc_hook``**, **``one_wire_pullup_erc_hook``**, **``i2c_pullup_erc_hook``**, **``mdio_pullup_erc_hook``**, **``spi_cs_pullup_erc_hook``**, **``spi_hold_n_pullup_erc_hook``**, **``spi_wp_n_pullup_erc_hook``**, **``spi_miso_pullup_erc_hook``**, **``reset_pullup_erc_hook``**, **``swd_swdio_pullup_erc_hook``**, **``jtag_tms_pullup_erc_hook``**, **``jtag_tck_pullup_erc_hook``**, **``can_rx_pullup_erc_hook``**, **``eth_phy_int_n_pullup_erc_hook``**, **``rs485_re_n_pullup_erc_hook``**, **``sd_cmd_pullup_erc_hook``**, **``lin_bus_pullup_erc_hook``**, **``power_good_pullup_erc_hook``**, **``i2s_ws_pullup_erc_hook``**, **``hdmi_cec_pullup_erc_hook``**, **``hdmi_hpd_pullup_erc_hook``**, **``sd_cd_pullup_erc_hook``**, **``stepper_dir_pullup_erc_hook``**, **``usb_otg_id_pullup_erc_hook``**, **``usb_vbus_sense_pullup_erc_hook``**, **``pcie_wake_n_pullup_erc_hook``**, **``rtc_int_n_pullup_erc_hook``**, **``smbus_alert_pullup_erc_hook``**, **``sensor_interrupt_pullup_erc_hook``**, **``missing_footprint_erc_hook``** + tests; **``openhac.stdlib.erc_rule_packs``** (**``apply_i2c_pullup_pack``**, **``apply_spi_flash_pullup_pack``**, **``apply_uart_debug_pullup_pack``**, **``apply_hdmi_display_pullup_pack``**, **``apply_sd_mmc_pullup_pack``**, **``apply_jtag_boundary_pullup_pack``**, **``apply_spi_nor_protect_pullup_pack``**, **``apply_lin_rs485_re_pullup_pack``**, **``apply_can_eth_phy_pullup_pack``**); **``openhac.stdlib.erc_plugin_registry``** (named **``apply_erc_plugin``** / **``Board.apply_erc_plugin``**, **``register_erc_plugin``**) + tests; manifest **``sch005_erc_rule_packs_module``**. Custom project rules via **``register_erc_plugin``**; optional curated **upstream** pack library still future. |
| **LIB-005** | Done | BOM **``JLC_Class``**; manifest **``jlc_assembly_line_summary``** (incl. **``by_class``**, **``total_line_items``**, **``other_class_line_items``**); **``max_jlc_extended_parts``** / **``warn_jlc_extended_parts``**; **``max_jlc_basic_parts``**; **``jlc_class_line_limits``** — per-class BOM line budgets (any normalized ``JLC_Class`` label plus **``unset``** for empty field); dict entries override scalar caps for the same class when both are set; manifest **``jlc_line_policy``** records limits. |
| **MFG-002** | Done | ``export_assembly_csv`` / ``openhac export assembly <pcb> -o <dir>`` (KiCad pos CSV via ``kicad-cli``). Manifest **``mfg002_assembly_export_cli``** records the **pos** export hint. |
| **MFG-003** | Done | **``examples/fab_stackup_table.md``** (links **``.openhac-fab-handoff.md``**); manifest **``mfg003_fab_handoff_markdown_suffix``**; **``declare_stackup_reference(..., documentation_note=...)``** → manifest + fab handoff markdown; **``--zip-release``** when present. PDF generation still future. |
| **STR-002** | Done | **``git_branch``**; **``git_describe``** (``git describe --always --dirty``) when the compile cwd is a git worktree; **``compile_pipeline_phases``** + **``compile_pipeline_phase_count``**; **``compile_env_flags``** (**``OPENHAC_*``** toggles; set **``OPENHAC_DETERMINISTIC_MANIFEST=1``** *or* umbrella **``OPENHAC_DETERMINISTIC=1``** to freeze **``generated_utc``** for golden/CI use and to scrub machine-specific ``build_environment``); optional **``kicad_cli_version``**; **``erc_plugin_hook_count``**; **``compile_manifest_emitter``** / **``compile_pipeline_module``** / **``str002_cli_module``**; **``str002_compile_pipeline_entry``**; **``str002_openhac_distribution_package``**; **``str002_manifest_json_sort_keys``**; **``str002_patch_manifest_release_zip_function``**; **``mfg005_zip_project_outputs_function``**; **``sim002_spice_analysis_loader_function``**; **``spice_presets_module``**; **``str002_rule_check_module``**, **``str002_layout_gen_module``**, **``str002_autoroute_module``**, **``str002_kicad_sch_erc_module``**, **``str002_schematic_gen_module``**, **``str002_spice_gen_module``**, **``str002_project_gen_module``**, **``str002_compile_state_dataclass``**, **``str002_manifest_json_suffix``**, **``str002_manifest_sha256_sidecar_suffix``**; **``str002_kicad_erc_report_module``**, **``str002_layout_constraints_module``**, **``str002_pcb_placement_module``**, **``str002_compile_manifest_module``**, **``str002_version_info_module``**; **``str002_core_board_module``** / **``str002_core_base_module``** / **``str002_core_compile_context_module``**; **``str002_compile_pipeline_default_phases_symbol``**; **``str002_openhac_version_info_function``** / **``str002_openhac_user_agent_function``**; **``str002_stdlib_erc_rules_module``**; **``str002_release_bundle_module``**; **``str002_stdlib_passives_module``**; **``str002_netlist_gen_generate_function``**; **``str002_rule_check_run_erc_function``** / **``str002_rule_check_run_drc_function``**; **``bom_csv_column_names``** when BOM CSV exists; **``netlist_line_count``** / **``netlist_suffix``** when **``.net``** exists; **``source_input.line_count``** when **``source_script_path``** resolves; **``pcb_routing_handoff_schema``** + **``pcb_routing_handoff_json_present``** + **``pcb_routing_handoff_json_sha256``** when routing JSON exists; **``pcb_routing_handoff_writer``**; **``pcb_pipeline_handoff_key_count``**; **``bom_alternates_schema``** + **``bom_alternates_handoff``** when alternates JSON exists; **``mfg001_fab_export_cli``** / **``mfg002_assembly_export_cli``**; **``mfg003_fab_handoff_markdown_suffix``**; **``sim002_spice_cli_flags``**; **``sim002_default_analysis_note``**; **``sim002_spice_analysis_config_module``**; **``sch003_kicad_erc_report_suffixes``**; **``rel003_test_point_net_names``** when **``require_test_point_on_nets``** is set; **``rel001_reliability_policy_key_catalog``**; **``reliability_policy``** / **``jlc_line_policy``** / **``lib006_passive_catalog_policy``** when corresponding **``Board``** flags set; **``release_bundle_suffixes``** (incl. alternates, SI reminder, **``.openhac-bom-expand-hint.md``**, **``.openhac-spice-model-hint.md``**, **``.openhac-autoroute-policy.md``**); **``compile_options``**, **``openhac_env_keys_present``**, **``sch_kicad_symbol_dirs_configured``**, **``pcb_pipeline_handoff``**, **``jit_confidence_histogram``** (when non-empty), **``stackup_json_summaries``** (JSON stackup refs), **``release_zip_path``** when zipping; **``release_zip_sha256``** when the zip file exists; **``mfg005_release_zip_sha256_note``**; **``fab_profile``** / **``fab_profile_json_path``** when set; **``length_match_group_count``**; **``logical_module_reference_total``** when **``logical_modules``** present; prior keys (**``compile_strictness``**, hierarchy, spice summary, etc.) unchanged; optional **``.sha256``** sidecar. Human sign-off / full CI golden matrix still future. |
| **SW-006** | Done | **``OPENHAC_SKIP_LAYOUT``** pytest covers logic-only **``compile``**; manifest **``sw006_skip_layout_env_key``**; subprocess **``openhac simulate … --spice-preset``** E2E for **ac** / **tran** / **op** / **dc** / **noise** (``.cir`` contains preset directive); subprocess **``--spice-line``** E2E; **``Board.simulate``** + **``spice_analysis_json_path``** contract test; **``scripts/ci_full_compile_smoke.py``**; **``kicad-layout-smoke``** is **blocking** (no ``continue-on-error``). |
| **ARCH** | Done | **[./ARCHITECTURE.md](./ARCHITECTURE.md)**: **contextvars** compile context; **no** ``Board`` → ``Component`` **class-attribute stomp**; **``Module.__iter__``** + ERC/DRC walks; **``Module.add_part``** / **``parent_module=``** for host-board strict at construction; **``compile_pipeline``** phase coordinator; schematic **alphanumeric pin sort**; JIT **category + word-boundary** matching; **``Board.power_net_prefixes``**; CLI copies strict flags onto **board** before **compile**; doc sections for **manifest traceability** + **ERC example hooks**; **``openhac.stdlib.erc_plugin_registry``** (**``register_erc_plugin``**, **``apply_erc_plugin``**, **``list_erc_plugin_names``**) + **``Board.apply_erc_plugin``** (named ERC packs + custom plugins). |
| **LIB-003** | Done | JIT maps **high/medium/low**; **``Board(strict=True)``** + CLI **``--strict``**; live API match uses **category blob** (when API provides it) + **word-boundary** tokens on description; manifest **``compile_strictness``**, **``lib003_jit_bom_columns``**, **``lib003_database_api_fallback_module``** (**``openhac.database.api_fallback``**), **``lib003_db_manager_module``** (**``openhac.database.db_manager``**), **``lib003_sync_jlc_module``** (**``openhac.database.sync_jlc``**); BOM **``OpenHaC_JIT_Confidence``** / **``OpenHaC_JIT_Score``**. Unified numeric model + first-class **functional tags** in DB still future. |
| **LIB-002** | Done | **``part_alternates``** + BOM columns; **``{project}.openhac-bom-alternates.json``** + **``{project}.openhac-bom-expand-hint.md``** (incl. suggested CM workflows) when alternates file exists; manifest **``bom_alternates_schema``**, **``bom_alternates_handoff``**, **``bom_alternates_generic_count``**, **``bom_alternates_total_rows``** when alternates JSON exists; manifest **``lib002_bom_csv_suffix``**; release zip suffixes. CM-specific BOM expand/collapse templates still future. |
| **LIB-006** | Done | **``strict_passive_catalog_fields``** (tolerance on R/C/L); **``strict_passive_attributes_json``** → non-empty valid JSON **object** in DB **``attributes_json``** for R/C/L-class parts; manifest **``str002_stdlib_passives_module``** (**``openhac.stdlib.passives``**). Unified parametric schema still future. |
| **REL-003** | Done | **``min_test_points``**; **``require_test_point_on_nets``** (case-insensitive net names) → DRC requires a heuristic test point on each net; **``test_point_min_count_by_net``** → DRC requires at least *N* heuristic test points per named net; manifest **``rel003_test_point_net_names``** / **``rel003_test_point_min_count_by_net``** when set (canonical **lower** net keys). JTAG automation still future. |
| **SIG-005** | Done | **``length_match_groups``** in manifest + **``{project}.openhac-length-match-hint.md``** + **``{project}.openhac-length-match-constraints.json``** (schema **``openhac.length_match_constraints.v1``**) when groups exist; manifest **``sig005_length_match_constraints_*``** when emitted; bundled in **``--zip-release``** when present. KiCad board-file constraint import / automated tune-length still future. |
| **SIG-006** | Done | **``net_roles``** / **``net_merge_hints``** in manifest + **``{project}.openhac-mixed-signal-hint.md``** + **``{project}.openhac-mixed-signal-constraints.json``** (schema **``openhac.mixed_signal_handoff.v1``**) when roles or hints exist; manifest **``sig006_mixed_signal_handoff_*``** when emitted; same data in **``.openhac-pcb-routing-handoff.json``**; bundled in **``--zip-release``** when present. DRC warns when **both** ``analog_ground`` and ``digital_ground`` roles are present but no ``declare_net_merge_hint`` bridges them (fails when ``Board(strict=True)``). **Stretch:** pcbnew keepouts (**``declare_keepout_rect``**) and net-ties (**``declare_net_tie``**, plus auto net-tie intent when ``declare_net_merge_hint(via='net_tie')``) are emitted into `.kicad_pcb` when pcbnew is available. |
| **PWR-002** | Done | **``stdlib.power.buck_input_current_ma``** (ideal buck input mA from output mA, rail voltages, efficiency) + ERC tests; **``Board.declare_rail_conversion(input_rail, output_rail, efficiency=...)``** propagates upstream supply to derived rails for ERC checks when **``declared_supply_voltages_v``** provides both rail voltages; optional **``{project}.openhac-rail-conversions.json``** (schema **``openhac.rail_conversions_handoff.v1``**) records declared rail conversions + declared voltages for downstream power review; manifest **``pwr002_rail_conversions_handoff_*``** when emitted; manifest **``pwr002_stdlib_helpers_catalog``** lists discoverable helpers; manifest **``pwr002_stdlib_power_module``** (**``openhac.stdlib.power``**); **``extra_input_draw_by_rail_ma``** still merged as before. Regulator object graph / auto tree still future. |
| **PCB-004** | Done | Example **``../fab_stackup_jlc_example.json``**; **``declare_stackup_reference``** → manifest **``stackup_references``** + fab handoff; **``stackup_json_summaries``** for referenced **``*.json``** stackup files; optional **``{project}.openhac-stackup-handoff.json``** (**``openhac.stackup_handoff.v1``**) + manifest **``pcb004_stackup_handoff_*``** when any stackup ref exists. Parser-driven stackup merge still future. |
| **SCH-002** | Done | **[SCOPE.md](./SCOPE.md)** flat **``.kicad_sch``**; manifest **``logical_modules``**, **``logical_module_names``**, **``logical_module_reference_total``**, + **``schematic_hierarchy_handoff``**; **``examples/hierarchy_authoring.md``** (manual KiCad sheet split vs manifest). Multi-sheet **``.kicad_sch``** / sheet pins not generated yet. |
| **Board DRC** | Done | ``Board.min_trace_width_mm`` overrides global IPC comparison threshold. |
| **Interface validation** | Done | `_validate_interfaces()` raises `UnconnectedInterfaceError` again when a net has fewer than two pins. |
| **ERC net-level** | Done | `_check_net_level` uses `get_default_circuit()` and raises `OpenHaCError` if the circuit cannot be read; silent `except: pass` on pin checks replaced with warnings. |
| **SCH-003** | Done | ``kicad-cli sch erc``; manifest **``sch003_schematic_erc_cli``** string for audit; manifest **``str002_kicad_sch_erc_module``** (**``openhac.compiler.kicad_sch_erc``**) for the wrapper implementation; manifest **``str002_kicad_erc_report_module``** (**``openhac.compiler.kicad_erc_report``**) for report parsing; **``--kicad-erc-json``** / **``kicad_sch_erc_format``**; **``kicad_erc_report.summarize_kicad_erc_report``**; **``run_kicad_schematic_erc(..., strict=False)``** for JSON inspection without raising. CI job **``kicad-schematic-erc``** runs **``scripts/ci_kicad_sch_erc_golden.py``** (zero ERC errors). **``scripts/kicad_erc_optional.sh``**. Broader golden matrix still future. |
| **LIB-004** | Done | **``--strict-kicad``** / **``--production``**; **``Board.strict_kicad``** without mutating **``Component``** class (use **``Module.add_part``** / **``parent_module=``** or CLI/env for symbol load time); **``OpenHaC_WATERMARK``** BOM column; **``bom_profile``** **``prod``** / **``production``** / **``cm``** → CSV omits internal & alternate columns; manifest **``bom_prod_omitted_columns``**, **``lib004_prod_bom_profile_active``** when prod profile; **``lib004_bom_prod_omitted_column_count``** (count of omitted dev/CM-internal columns). Further CM templates still future. |
| **SW-005** | Done | Public ``openhac.circuit.get_circuit()`` alias of ``get_default_circuit()``; compiler still imports the latter internally. Manifest **``sw005_circuit_public_module``** (**``openhac.circuit``**). |
| **SIG-004** | Done | [SCOPE.md](./SCOPE.md) states EMC/EMI is manual + test lab (no automated sign-off). |
| **SIM-003** | Done | [SCOPE.md](./SCOPE.md) lists digital verification (timing/CDC/formal) as a non-goal for core. |
| **PCB-007** | Done | **``declare_no_autoroute_net()``**; manifest **``no_autoroute_nets``** + **``no_autoroute_net_count``**; optional **``{project}.openhac-no-autoroute-constraints.json``** (**``openhac.no_autoroute_handoff.v1``**) + manifest **``pcb007_no_autoroute_constraints_*``** when emitted; **``pcb_routing_handoff_writer``**; **``{project}.openhac-autoroute-policy.md``**; **``{project}.openhac-pcb-routing-handoff.json``** with **``pcb_routing_handoff_schema``**; optional **``{project}.openhac-netclass-hint.md``** + manifest **``pcb007_netclass_suggestion_count``** / **``pcb007_netclass_hint_writer``** + **``netclass_suggestions``** in routing JSON (suggested KiCad netclass names from diff pairs / length-match / no-autoroute / net roles — no **``.kicad_pro``** emission). |
| **PCB-009** | Done | **``declare_copper_pour_intent(net, layer=..., purpose=...)``** → manifest + routing handoff + SI reminder; optional **``{project}.openhac-pcb-auxiliary-constraints.json``** (**``openhac.pcb_auxiliary_handoff.v1``**, shared with **PCB-010**) when pour and/or mount intent exists; manifest **``pcb009_copper_pour_handoff_note``**; no **``pcbnew``** zone emission yet. |
| **PCB-010** | Done | **``declare_mounting_hole(x_mm, y_mm, diameter_mm, note=...)``** → manifest + routing handoff; auxiliary JSON as under **PCB-009**; manifest **``pcb010_mounting_hole_handoff_note``**; no NPTH geometry yet. |
| **PCB-011** | Done | JIT generation of KiCad footprints and STEP models from EasyEDA/LCSC SKU; absolute pathing for 3D models in the PCB; persistent caching in `~/.kiro/openhac/`. |
| **SIG-002** | Done | DRC warns on **``route_differential_pair``**; **``diff_pair_intent``** in manifest + **``sig002_diff_pair_intent_disclaimer``** + optional **``{project}.openhac-diff-pair-constraints.json``** (**``openhac.diff_pair_handoff.v1``**) + manifest **``sig002_diff_pair_constraints_*``** when emitted + **``.openhac-pcb-routing-handoff.json``**; **``.openhac-si-stackup-reminder.md``** lists per-pair target Z0 when declared. Full netclass automation still future. |
| **MFG-005** | Done | **``--zip-release``** → **``zip_project_outputs``** (suffixes include BOM alternates, BOM expand hint, spice model hint, autoroute policy, SI reminder, mixed-signal, length-match, **``pcb-routing-handoff.json``**, etc.). Release zip creation is **deterministic** (stable entry order + timestamps) for CI/golden use. Manifest **``release_bundle_suffixes``** + **``release_bundle_suffix_count``**; manifest **``str002_release_bundle_module``** (**``openhac.compiler.release_bundle``**); **``release_zip_sha256``** (digest of the first-pass zip, then manifest patch + second zip so bundle includes manifest with digest; see **``mfg005_release_zip_sha256_note``**). In umbrella deterministic mode (**``OPENHAC_DETERMINISTIC=1``**), the manifest patch + second zip pass is skipped so zip bytes are stable end-to-end (and `release_zip_sha256` is omitted). Signing / immutable policy still future. |
| **SIM-001** | Done | DB **``spice_include``** / **``spice_subckt``** → BOM fields + **``generate_spice``**; manifest **``spice_annotation_summary``**, **``sim001_spice_database_fields``**, **``str002_spice_gen_module``** (**``openhac.compiler.spice_gen``**); **``{project}.openhac-spice-model-hint.md``** (summary + checklist) when annotation summary non-zero. Rich vendor model tables still future. |
| **SIM-002** | Done | **``--spice-line``** / **``--spice-preset``** / **``--spice-analysis-json``** (CLI subprocess E2E covered for **ac**, **tran**, **op**, **dc**, **noise** presets, **``--spice-line``**, and **YAML** analysis file); manifest **``spice_presets_catalog``**, **``sim002_spice_cli_flags``**, **``sim002_spice_config_file_suffixes``**, **``sim002_default_analysis_note``**, **``sim001_spice_database_fields``**, **``sim002_spice_analysis_loader_function``**, **``spice_presets_module``**, **``sim002_spice_presets_preset_analysis_lines_function``** (**``openhac.compiler.spice_presets.preset_analysis_lines``**), **``sim002_spice_netlist_suffix``** (**``.cir``**), **``sim002_resolve_spice_analysis_function``**; **``Board.simulate(..., spice_analysis_json_path=...)``** loads JSON or YAML via **``spice_analysis_config``** (**``analysis_lines``** or **``preset``**); **``.cir``** comment block lists directives; **``examples/spice_analysis.example.yaml``**. Embedded simulation DSL inside user scripts still future. |
| **LIB-001** | Done | **``part_offers``** + BOM **``Ranked_Offers``** + **``Primary_Offer``** + **``Secondary_Offer``** + **``Offer_Count``** (prod BOM omits offer columns per **LIB-004**); manifest **``lib001_bom_offer_column_names``**. CM-specific offer pickers / UI still future. |
| **MFG-004** | Done | **``jlc.json``**, **``generic_2layer.json``**, **``eurocircuits_4layer.json``**, **``oshpark_2layer.json``**; manifest **``fab_profiles_catalog``** (bundled profile names); **``declare_dfm_reference(path, role=..., documentation_note=...)``** → manifest **``dfm_references``**; **``fab_profile``** merges into IPC DRC baseline; manifest **``fab_profile_geometry_keys``** (top-level keys from the profile JSON) when **``fab_profile``** is set. External DFM tool hooks still future. |
| **PCB-003** | Done | ``Board.layers > 2`` logs stackup warning; manifest **``pcb_stackup_layer_note``**; **``{project}.openhac-si-stackup-reminder.md``** when stackup / SI triggers fire; **``../stackup_template.yaml``**. No pcbnew stackup emission. |
| **REL-001** | Done | **``require_passive_voltage_ratings``** / **``require_resistor_voltage_ratings``** / **``require_passive_power_ratings``**; **``require_inductor_voltage_ratings``**; **``require_cap_voltage_derating_ratio``** + **``declared_supply_voltages_v``**; optional **ambient temperature margin** for cap derating: **``ambient_operating_temp_c``** + **``cap_voltage_temp_derating_percent_per_c``** (with **``cap_voltage_rating_reference_temp_c``**, default 85°C); manifest **``rel001_reliability_policy_key_catalog``** (keys that may appear under **``reliability_policy``**). Broader policy module (unified derating rules beyond caps) still future. |
| **REL-002** | Done | [SCOPE.md](./SCOPE.md) states mains/isolation is not tool-certified. |
| **PCB-008** | Done | [SCOPE.md](./SCOPE.md) documents manual BGA/fanout path. |
| **SIG-001** | Done | Example **``../stackup_template.yaml``**; manifest **``sig001_stackup_template_reference``**; **``declare_stackup_reference``**; **``.openhac-si-stackup-reminder.md``** ties stackup refs + multi-layer + diff pairs + pour intent to external SI workflow. In-tool SI solver still future. |
| **SIG-003** | Done | [SCOPE.md](./SCOPE.md) non-goals: PDN/decap not automated in core. **``examples/pdn_checklist_handoff.md``** for human PI checklist. |

### Stretch — ERC plugin registry (Apr 2026)

| IDs touched | What shipped |
|-------------|----------------|
| **ARCH** / **SCH-005** | **``openhac.stdlib.erc_plugin_registry``**: built-in names for every **``erc_rule_packs``** export (e.g. **``i2c_pullup_pack``**), **``register_erc_plugin``** / **``apply_erc_plugin``** / **``list_erc_plugin_names``**; **``Board.apply_erc_plugin``**; tests in **``tests/test_erc_plugin_registry.py``** |

### Stretch — LIB-005 per-class JLC line budgets (Apr 2026)

| IDs touched | What shipped |
|-------------|----------------|
| **LIB-005** | **``Board(jlc_class_line_limits=...)``**; **``jlc_class_line_counts_from_circuit()``** / unified DRC vs **``max_jlc_*``** scalars; manifest **``jlc_assembly_line_summary.by_class``**; tests in **``TestLIB005JlcPerClassLimits``** + **``test_manifest_jlc_line_policy_includes_per_class_limits``** |

### Stretch — REL-001 capacitor temp derating margin (Apr 2026)

| IDs touched | What shipped |
|-------------|----------------|
| **REL-001** | **``Board.ambient_operating_temp_c``**, **``cap_voltage_rating_reference_temp_c``**, **``cap_voltage_temp_derating_percent_per_c``**; DRC applies temp factor to cap **``voltage_rating``** check; manifest **``reliability_policy``** + **``rel001_reliability_policy_key_catalog``**; tests in **``TestREL001PassiveVoltageRatings``** |

### Stretch — REL-003 per-net minimum test-point counts (Apr 2026)

| IDs touched | What shipped |
|-------------|----------------|
| **REL-003** | **``Board.test_point_min_count_by_net``** (lower-cased net keys); DRC **``_count_test_points_on_net_ci``** vs per-net minimum; manifest **``rel003_test_point_min_count_by_net``** + **``reliability_policy.test_point_min_count_by_net``**; catalog key **``test_point_min_count_by_net``** in **``rel001_reliability_policy_key_catalog``**; tests in **``TestREL003MinTestPoints``** + **``test_manifest_round4_traceability_fields``** |

### Stretch — PCB-007 KiCad netclass handoff (Apr 2026)

| IDs touched | What shipped |
|-------------|----------------|
| **PCB-007** / **STR-002** | **``_netclass_suggestions``** / **``_write_netclass_hint_md``** → **``{project}.openhac-netclass-hint.md``**; **``netclass_suggestions``** array in **``.openhac-pcb-routing-handoff.json``**; manifest **``pcb007_netclass_suggestion_count``**, **``pcb007_netclass_hint_markdown_suffix``**, **``pcb007_netclass_hint_writer``**, **``pcb007_netclass_hint_note``**; release zip suffix **``.openhac-netclass-hint.md``**; tests in **``test_compile_integration``** + **``test_release_bundle``** |

### Stretch — PCB-009/010 pcbnew geometry emit (Apr 2026)

| IDs touched | What shipped |
|-------------|--------------|
| **PCB-009** / **PCB-010** | When **pcbnew** is available, OpenHaC now emits **best-effort copper zones** for **``declare_copper_pour_intent``** and **mounting hole footprints** for **``declare_mounting_hole``** into the generated **``.kicad_pcb``** (post-processing step). Unit tests in **``tests/test_pcb_postprocess.py``**. |

### Stretch — Schematic grouping by module tags (Apr 2026)

| IDs touched | What shipped |
|-------------|--------------|
| **SCH-001** (quality-of-life) | ``Module.add`` / ``add_part`` tag underlying SKiDL parts with **``fields["OpenHaC_Module"]``**; schematic generator groups symbol placement into per-module blocks when that field exists (improves readability; connectivity unchanged). Tests in **``tests/test_core.py``** + existing **``tests/test_schematic_gen.py``**. |

### Stretch — PCB-007 fallback router respects no-autoroute nets (Apr 2026)

| IDs touched | What shipped |
|-------------|--------------|
| **PCB-007** | pcbnew fallback router now accepts **``no_autoroute_nets``** and avoids adding tracks to those nets; compile pipeline skips FreeRouting when exclusions are present but still attempts fallback routing **if the PCB file exists**. Tests in **``tests/test_autoroute_fallback.py``**. |

### Stretch — SIG-005 length-match constraints JSON (Apr 2026)

| IDs touched | What shipped |
|-------------|----------------|
| **SIG-005** / **STR-002** | **``_write_length_match_constraints_json``** → **``{project}.openhac-length-match-constraints.json``** (**``openhac.length_match_constraints.v1``**); manifest **``sig005_length_match_constraints_schema``** / **``sig005_length_match_constraints_suffix``** / **``sig005_length_match_constraints_note``** + **``sig005_length_match_constraints_writer``**; release zip suffix **``.openhac-length-match-constraints.json``**; tests in **``test_compile_integration``** + **``test_release_bundle``** |

### Stretch — SIG-006 mixed-signal constraints JSON (Apr 2026)

| IDs touched | What shipped |
|-------------|----------------|
| **SIG-006** / **STR-002** | **``_write_mixed_signal_constraints_json``** → **``{project}.openhac-mixed-signal-constraints.json``** (**``openhac.mixed_signal_handoff.v1``**); manifest **``sig006_mixed_signal_handoff_schema``** / **``sig006_mixed_signal_handoff_suffix``** / **``sig006_mixed_signal_handoff_note``** + **``sig006_mixed_signal_handoff_writer``**; release zip suffix **``.openhac-mixed-signal-constraints.json``**; tests in **``test_compile_integration``** + **``test_release_bundle``** |

### Stretch — SIG-002 diff-pair constraints JSON (Apr 2026)

| IDs touched | What shipped |
|-------------|----------------|
| **SIG-002** / **STR-002** | **``_write_diff_pair_constraints_json``** → **``{project}.openhac-diff-pair-constraints.json``** (**``openhac.diff_pair_handoff.v1``**); manifest **``sig002_diff_pair_constraints_schema``** / **``sig002_diff_pair_constraints_suffix``** / **``sig002_diff_pair_constraints_note``** + **``sig002_diff_pair_constraints_writer``**; release zip suffix **``.openhac-diff-pair-constraints.json``**; tests in **``test_compile_integration``** + **``test_release_bundle``** |

### Stretch — PCB-007 no-autoroute constraints JSON (Apr 2026)

| IDs touched | What shipped |
|-------------|----------------|
| **PCB-007** / **STR-002** | **``_write_no_autoroute_constraints_json``** → **``{project}.openhac-no-autoroute-constraints.json``** (**``openhac.no_autoroute_handoff.v1``**); manifest **``pcb007_no_autoroute_constraints_schema``** / **``pcb007_no_autoroute_constraints_suffix``** / **``pcb007_no_autoroute_constraints_note``** + **``pcb007_no_autoroute_constraints_writer``**; release zip suffix **``.openhac-no-autoroute-constraints.json``**; tests in **``test_compile_integration``** + **``test_release_bundle``** |

### Stretch — PCB-009 / PCB-010 auxiliary constraints JSON (Apr 2026)

| IDs touched | What shipped |
|-------------|----------------|
| **PCB-009** / **PCB-010** / **STR-002** | **``_write_pcb_auxiliary_constraints_json``** → **``{project}.openhac-pcb-auxiliary-constraints.json``** (**``openhac.pcb_auxiliary_handoff.v1``**); **``copper_pour_intents``** + **``mounting_hole_intents``**; manifest **``pcb_auxiliary_handoff_schema``** / **``pcb_auxiliary_handoff_suffix``** / **``pcb_auxiliary_handoff_note``** + **``pcb_auxiliary_handoff_writer``**; release zip suffix **``.openhac-pcb-auxiliary-constraints.json``**; tests in **``test_compile_integration``** + **``test_release_bundle``** |

### “Next 20 tickets” batch — round 11 (Apr 2026)

| IDs touched | What shipped |
|-------------|----------------|
| **STR-002** | **``str002_release_bundle_module``**, **``str002_stdlib_passives_module``**, **``str002_netlist_gen_generate_function``**, **``str002_rule_check_run_erc_function``**, **``str002_rule_check_run_drc_function``** |
| **LIB-003** | **``lib003_db_manager_module``**, **``lib003_sync_jlc_module``** |
| **LIB-006** | **``str002_stdlib_passives_module``** (passive catalog module path) |
| **SIM-002** | **``sim002_spice_presets_preset_analysis_lines_function``** |
| **MFG-005** | **``str002_release_bundle_module``** (zip bundle implementation path) |
| **SCH-005** | **``apply_can_eth_phy_pullup_pack``** (CAN RX + Ethernet PHY INT#) + test |
| **ARCH** | [ARCHITECTURE.md](./ARCHITECTURE.md) manifest list updated |

### “Next 20 tickets” batch — round 10 (Apr 2026)

| IDs touched | What shipped |
|-------------|----------------|
| **STR-002** | **``str002_core_board_module``**, **``str002_core_base_module``**, **``str002_core_compile_context_module``**, **``str002_compile_pipeline_default_phases_symbol``**, **``str002_openhac_version_info_function``**, **``str002_openhac_user_agent_function``**, **``str002_stdlib_erc_rules_module``** |
| **PWR-002** | **``pwr002_stdlib_power_module``** (**``openhac.stdlib.power``**) |
| **LIB-003** | **``lib003_database_api_fallback_module``** (**``openhac.database.api_fallback``**) |
| **SW-004** | Manifest **``str002_openhac_version_info_function``** / **``str002_openhac_user_agent_function``** tie release scripts / User-Agent audit strings to compile output |
| **SCH-005** | **``usb_vbus_sense_pullup_erc_hook``**, **``pcie_wake_n_pullup_erc_hook``**, **``rtc_int_n_pullup_erc_hook``** + tests; **``apply_lin_rs485_re_pullup_pack``** (LIN + RS485 RE#) + test |
| **ARCH** | [ARCHITECTURE.md](./ARCHITECTURE.md) manifest + ERC lists updated |

### “Next 20 tickets” batch — round 9 (Apr 2026)

| IDs touched | What shipped |
|-------------|----------------|
| **STR-002** | **``str002_kicad_erc_report_module``**, **``str002_layout_constraints_module``**, **``str002_pcb_placement_module``**, **``str002_compile_manifest_module``**, **``str002_version_info_module``** |
| **SCH-003** | **``str002_kicad_erc_report_module``** (ERC report parser path) |
| **SCH-001** | **``sch001_kicad_sym_pinpos_module``** |
| **PCB-005** | **``str002_layout_constraints_module``** |
| **PCB-001** | **``str002_pcb_placement_module``** |
| **MFG-001** | **``mfg001_export_fab_module``** |
| **SW-005** | **``sw005_circuit_public_module``** |
| **SIM-002** | **``sim002_resolve_spice_analysis_function``** |
| **SCH-005** | **``spi_wp_n_pullup_erc_hook``**, **``rs485_re_n_pullup_erc_hook``** + tests; **``apply_spi_nor_protect_pullup_pack``** (WP# + HOLD#) + test |
| **ARCH** | [ARCHITECTURE.md](./ARCHITECTURE.md) manifest + ERC lists updated |

### “Next 20 tickets” batch — round 8 (Apr 2026)

| IDs touched | What shipped |
|-------------|----------------|
| **STR-002** | Compiler **module / symbol audit strings**: **``str002_rule_check_module``**, **``str002_layout_gen_module``**, **``str002_autoroute_module``**, **``str002_kicad_sch_erc_module``**, **``str002_schematic_gen_module``**, **``str002_spice_gen_module``**, **``str002_project_gen_module``**, **``str002_compile_state_dataclass``**, **``str002_manifest_json_suffix``**, **``str002_manifest_sha256_sidecar_suffix``** |
| **SCH-001** | **``str002_schematic_gen_module``**, **``str002_project_gen_module``** (schematic / **``.kicad_pro``** generation entry points) |
| **SCH-003** | Manifest references **``str002_kicad_sch_erc_module``** (wrapper module path) |
| **SIM-001** | **``str002_spice_gen_module``** (SPICE netlist generation entry point) |
| **SIM-002** | **``sim002_spice_netlist_suffix``** (**``.cir``**) |
| **SCH-005** | **``spi_hold_n_pullup_erc_hook``**, **``eth_phy_int_n_pullup_erc_hook``** + tests; **``apply_jtag_boundary_pullup_pack``** (TMS + TCK) + test |
| **PCB-007** | **``str002_autoroute_module``** (autoroute CLI entry for audit) |
| **ARCH** | [ARCHITECTURE.md](./ARCHITECTURE.md) manifest + ERC lists updated |

### “Next 20 tickets” batch — round 7 (Apr 2026)

| IDs touched | What shipped |
|-------------|----------------|
| **STR-002** | **``str002_manifest_json_sort_keys``**, **``str002_patch_manifest_release_zip_function``**, **``mfg005_zip_project_outputs_function``**, **``sim002_spice_analysis_loader_function``**, **``spice_presets_module``** |
| **SW-003** | Manifest **``sw003_netlist_gen_module``** |
| **SCH-005** | **``jtag_tck_pullup_erc_hook``**, **``can_rx_pullup_erc_hook``** + tests; **``apply_sd_mmc_pullup_pack``** (CMD + CD) + test |
| **SIM-002** | **``sim002_spice_analysis_loader_function``**, **``spice_presets_module``** |
| **MFG-005** | **``mfg005_zip_project_outputs_function``** (audit string; behavior unchanged) |
| **PCB-001** / **SCH-001** / **LIB-002** | KiCad / BOM **suffix** manifest keys (**``pcb001_*``**, **``sch001_*``**, **``lib002_bom_csv_suffix``**) |
| **ARCH** | [ARCHITECTURE.md](./ARCHITECTURE.md) manifest list updated |

### “Next 20 tickets” batch — round 6 (Apr 2026)

| IDs touched | What shipped |
|-------------|----------------|
| **STR-002** | **``netlist_line_count``**, **``netlist_suffix``**, **``source_input.line_count``**, **``pcb_pipeline_handoff_key_count``**, **``str002_compile_pipeline_entry``**, **``str002_openhac_distribution_package``**, **``sch003_kicad_erc_report_suffixes``**, **``sim002_spice_analysis_config_module``**, **``mfg005_release_zip_sha256_note``**; **``release_zip_sha256``** after first-pass zip (**``patch_manifest_release_zip_sha256``** + rebuild zip) |
| **SCH-003** | **``sch003_kicad_erc_report_suffixes``** (KiCad ERC report filename stems) |
| **SCH-005** | **``hdmi_hpd_pullup_erc_hook``**, **``sd_cd_pullup_erc_hook``** + tests; **``apply_hdmi_display_pullup_pack``** (CEC + HPD) + test |
| **MFG-005** | **``phase_release_zip``**: zip → **``patch_manifest_release_zip_sha256``** (optional **``.sha256``** sidecar refresh) → zip again so bundle includes manifest with digest |
| **SIM-002** | **``sim002_spice_analysis_config_module``** (Python module for YAML/JSON analysis loader) |
| **ARCH** | [ARCHITECTURE.md](./ARCHITECTURE.md) manifest + ERC lists updated |

### Phase-2 increment — batch A (Apr 2026)

| IDs touched | What shipped |
|-------------|----------------|
| **SCH-005** | **``openhac.stdlib.erc_rule_packs``** — **``apply_i2c_pullup_pack``**, **``apply_spi_flash_pullup_pack``**, **``apply_uart_debug_pullup_pack``** + test; manifest **``sch005_erc_rule_packs_module``** |
| **SIM-002** | **``pyyaml``** dependency; **``spice_analysis_config``** (JSON/YAML, **``preset``** in file); **``sim002_spice_config_file_suffixes``**; **``examples/spice_analysis.example.yaml``**; CLI + **``Board.simulate``** tests |

### “Next 15 tickets” batch — round 5 (Apr 2026)

| IDs touched | What shipped |
|-------------|----------------|
| **STR-002** | **``compile_manifest_emitter``**, **``compile_pipeline_module``**, **``str002_cli_module``**; **``bom_csv_column_names``**; **``rel001_reliability_policy_key_catalog``**; **``sim002_default_analysis_note``** |
| **SCH-002** | **``logical_module_reference_total``** (sum of schematic refs across logical modules) |
| **SCH-005** | **``sch005_erc_rules_module``**; **``smbus_alert_pullup_erc_hook``**, **``sensor_interrupt_pullup_erc_hook``** + tests |
| **LIB-001** | **``lib001_bom_offer_column_names``** |
| **LIB-004** | **``lib004_bom_prod_omitted_column_count``** |
| **SW-006** | **``sw006_skip_layout_env_key``** |
| **PCB-007** | **``pcb_routing_handoff_writer``** |
| **MFG-003** | **``mfg003_fab_handoff_markdown_suffix``** |
| **SIG-002** | **``sig002_diff_pair_intent_disclaimer``** |
| **PCB-009** / **PCB-010** | **``pcb009_copper_pour_handoff_note``**, **``pcb010_mounting_hole_handoff_note``** |
| **REL-001** | **``rel001_reliability_policy_key_catalog``** |
| **SIM-002** | **``sim002_default_analysis_note``** |
| **ARCH** | [ARCHITECTURE.md](./ARCHITECTURE.md) manifest list updated |

### “Next 15 tickets” batch — round 4 (Apr 2026)

| IDs touched | What shipped |
|-------------|----------------|
| **STR-002** | **``erc_plugin_hook_count``**; **``bom_alternates_schema``**; **``mfg001_fab_export_cli``** / **``mfg002_assembly_export_cli``**; **``sim002_spice_cli_flags``**; **``rel003_test_point_net_names``** |
| **SCH-005** | **``stepper_dir_pullup_erc_hook``**, **``usb_otg_id_pullup_erc_hook``** + tests |
| **REL-003** | Manifest net-name list (**``rel003_test_point_net_names``**) alongside DRC |
| **MFG-001** / **MFG-002** | Manifest CLI hint strings for fab / assembly export |
| **LIB-002** | **``bom_alternates_schema``** in manifest when alternates JSON exists |
| **SIM-002** / **SW-006** | Manifest **``sim002_spice_cli_flags``**; subprocess **``simulate --spice-line``** test |
| **ARCH** | [ARCHITECTURE.md](./ARCHITECTURE.md) manifest + ERC lists updated |

### “Next 15 tickets” batch — round 3 (Apr 2026)

| IDs touched | What shipped |
|-------------|----------------|
| **MFG-004** | **``fab_profiles_catalog``** (bundled profile stems) |
| **PCB-007** | **``no_autoroute_net_count``** |
| **SIM-001** | **``sim001_spice_database_fields``** |
| **SCH-003** | **``sch003_schematic_erc_cli``** |
| **SIG-001** | **``sig001_stackup_template_reference``** |
| **LIB-003** | **``lib003_jit_bom_columns``** |
| **LIB-004** | **``lib004_prod_bom_profile_active``** when prod BOM profile |
| **SIM-002** / **SW-006** | Subprocess **``simulate --spice-preset noise``** |
| **SCH-005** | **``i2s_ws_pullup_erc_hook``**, **``hdmi_cec_pullup_erc_hook``** + tests |
| **STR-002** | Cross-cutting manifest keys above (audit / release traceability) |
| **ARCH** | [ARCHITECTURE.md](./ARCHITECTURE.md) manifest + ERC lists updated |

### “Next 15 tickets” batch — round 2 (Apr 2026)

| IDs touched | What shipped |
|-------------|----------------|
| **STR-002** | **``outputs_total_bytes``**, **``outputs_artifact_count``**, **``bom_csv_line_count``** / **``bom_csv_data_row_count``**, **``spice_presets_catalog``** |
| **SCH-002** | **``logical_module_names``**; **``examples/hierarchy_authoring.md``** mentions it |
| **LIB-002** | **``bom_alternates_generic_count``**, **``bom_alternates_total_rows``** from alternates JSON |
| **MFG-005** | **``release_bundle_suffix_count``** |
| **MFG-004** | **``dfm_reference_count``**, **``stackup_json_summaries_count``** |
| **PCB-001** / **PCB-002** | **``pcb_pipeline_handoff.schema_ref``** = ``openhac.pcb_pipeline_handoff.v1`` |
| **PWR-002** | **``pwr002_stdlib_helpers_catalog``** (e.g. **``buck_input_current_ma``**) |
| **SIM-002** / **SW-006** | Subprocess **``simulate --spice-preset op``** / **``dc``** tests |
| **SCH-005** | **``lin_bus_pullup_erc_hook``**, **``power_good_pullup_erc_hook``** + tests |
| **ARCH** | [ARCHITECTURE.md](./ARCHITECTURE.md) manifest field list expanded |

### “Next 15 tickets” batch — round 1 (Apr 2026)

Earlier slice: **``compile_pipeline_phase_count``**, **``compile_env_flags``**, **``kicad_cli_version``**, **``pcb_routing_handoff_json_sha256``**, **``sch_pin_sort_mode``**, **``sd_cmd``** / **``spi_miso``** hooks, **``reliability_policy``**, **``jlc_line_policy``**, **``lib006_passive_catalog_policy``**, **SIG**/**PCB** counts, **``fab_profile_json_path``**, **``simulate --spice-preset tran``**, etc.

### “Next 30 tickets” batch (Apr 2026) — superseded note

Closing every **Partial** row to literal **Done** remains a **multi-phase** effort; use the **round 1 / round 2** tables above for the latest slices. Older context: BOM expand-hint, SPICE checklist, **ARCH** compile-context notes, **SCH-004** **``power_net_prefixes``**, **LIB-004** strict KiCad paths.

### Completion percentage (48 spec IDs)

Every numbered ID in [PRODUCTION_READINESS_SPEC.md](./PRODUCTION_READINESS_SPEC.md) has a row in the table above (**48** total).

| Metric | Value | Notes |
|--------|--------|--------|
| **Phase-1 Done** | **48 / 48 (100%)** | All spec ID rows are **Done** per [Phase-1 completion](./PRODUCTION_READINESS_SPEC.md#phase-1-completion-2026) in the spec. |
| **Stretch goals** | See per-ID **Notes** | Future work (e.g. KiCad-native exports, signing) is documented in Notes and in spec **Future** callouts, not as open **Partial** rows. |

Extra rows (**Layout stub**, **Z3 overlap**, **Board DRC**, etc.) are **not** counted in the 48.

## How many tickets are left?

**Phase-1:** **Zero** open **Partial** rows for the **48** numbered spec IDs: all are **Done**. Optional Phase-1 **stretch** work is tracked in per-ID Notes and in [PRODUCTION_READINESS_SPEC.md](./PRODUCTION_READINESS_SPEC.md).

**Phase-2:** **0** open `FAB-*` IDs — see [FABRICATION_READINESS_SPEC.md](./FABRICATION_READINESS_SPEC.md) and the Phase-2 table above.

| Bucket | Count | Meaning |
|--------|--------|--------|
| **Done** (all 48 Phase-1 spec IDs) | **48** | Phase-1 acceptance (see production spec). |
| **Done (extra rows)** | **5** | Layout stub, Z3 overlap, Board DRC, interface validation, ERC net-level (supporting work, not a single spec ID). |
| **Done (Phase-2 FAB-*)** | **20** | Fabrication readiness contract. |
| **Open (Phase-2 FAB-*)** | **0** | — |

### Stretch backlog (follow-on batches)

Phase-2 fabrication gates (**FAB-***) are the primary follow-on backlog. Additional Phase-1 stretch notes (not Phase-2 IDs):

- **SCH-002**: richer hierarchical export (sheet pins, per-module wiring) beyond the current multi-sheet split — subordinate to **FAB-040** (schematic demotion).
- **PCB-007 / SIG-002**: emit netclass/rule constraints into KiCad project/board files (not just handoff JSON/markdown).
- **PCB-003 / SIG-001**: stackup/inner-plane authoring beyond warnings + handoff docs.
- **LIB-003**: unify JIT confidence scoring (numeric) and introduce first-class functional tags in the DB.
- **STR-002**: release signing / explicit human approval flows + broader CI golden matrix (overlaps **FAB-031** / **FAB-051**).

## CLI usage

- Prefer: `openhac compile my_design.py --name out`
- For `python my_design.py`, wrap `board.compile(...)` in `main()` under `if __name__ == "__main__":` so importing the file (for tools) does not compile twice.
- Optional env: **`OPENHAC_DB_PATH`** (SQLite catalog file), **`OPENHAC_SKIP_LAYOUT`** (`1` / `true` / `yes` — skip `pcbnew` layout + autoroute; netlist/BOM/manifest only), **`OPENHAC_KICAD_SYMBOL_DIRS`** (pathsep-separated dirs prepended for **``.kicad_sym``** pin positions / SCH-001).

## `.gitignore` policy

- **Tracked:** `tests/**/*.py` and `tests/conftest.py` (required for CI).
- **Ignored:** pytest/Hypothesis/benchmark caches under `tests/`, `tests/tmp/`, `tests/fixtures/generated/`, coverage artifacts, generated KiCad/SPICE outputs, local DB, `*-release.zip`, etc. — see root `.gitignore` (policy block at file end).
