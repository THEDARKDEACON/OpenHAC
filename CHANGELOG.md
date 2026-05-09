# Changelog

Notable changes to OpenHaC. The package version in `pyproject.toml` is canonical; this file is checked in CI (SW-004).

## [0.2.0]

### Phase-1 production-readiness (all 48 spec IDs)

- **Compiler pipeline** (`compile_pipeline.py`): ordered `CompileState` phases replacing ad-hoc compile flow; easier to test and swap phases.
- **Compile manifest** (STR-002): JSON audit trail with 100+ traceability fields (`openhac_version`, `git_*`, pipeline phases, env flags, artifact counts, BOM columns, routing handoff SHA256, etc.).
- **No global Component class stomp** (ARCH): `Board.__init__` no longer mutates `Component.require_kicad_symbols` / `strict_jit_lookups`; contextvars compile context isolates per-compile flags.
- **ERC** (SCH-004/SCH-005): `declare_power_rail`, `power_net_prefixes`, PWR_FLAG checks; 30+ ERC hook examples; `erc_plugin_registry` with `register_erc_plugin` / `Board.apply_erc_plugin`.
- **DRC** (PCB-006): IPC-2152 trace-width check; `Board.min_trace_width_mm` override; fab profile geometry merge (MFG-004).
- **KiCad schematic** (SCH-001): `.kicad_sym` pin `(at)` lookup; alphanumeric pin sort; generated `{project}.openhac-generated.kicad_sym` + `sym-lib-table`; deterministic UUIDs.
- **KiCad schematic ERC** (SCH-003): `kicad-cli sch erc` integration; `--kicad-erc` / `--kicad-erc-json` CLI flags.
- **PCB layout** (PCB-001/PCB-002): footprints from `*.pretty`; pad↔net assignment; strict pin↔pad match (`--strict-footprint-pads`); pin-pad coverage report JSON.
- **Z3 placement** (PCB-005): axis-aligned bbox minimum gap + center L1 max distance constraints.
- **Autorouting** (PCB-007): FreeRouting DSN/SES round-trip; KiCad 9 pcbnew fallback; `declare_no_autoroute_net`; netclass hint markdown.
- **Fabrication export** (MFG-001/MFG-002): `openhac export fab` — Gerbers, Excellon drill, CSV position via `kicad-cli`; optional IPC-2581; assembly CSV.
- **Release bundle** (MFG-005): `--zip-release` deterministic zip with SHA256 sidecar.
- **SPICE** (SIM-001/SIM-002): `.cir` generation; `spice_include` / `spice_subckt` DB fields; `--spice-preset` / `--spice-line` / `--spice-analysis-json` CLI; AC, tran, DC, noise, op presets.
- **Database** (LIB-001–LIB-006): `part_offers` (ranked distributors); `part_alternates` with group IDs; JIT confidence (high/medium/low); production BOM profile; JLC assembly class budgets (`jlc_class_line_limits`); strict passive catalog fields.
- **Per-rail power ERC** (PWR-001/PWR-002): dict `source_current_max_ma` vs dict `max_current_draw_ma`; `declare_rail_conversion` with efficiency propagation; rail conversions handoff JSON.
- **SI/PCB handoff** (SIG-002/SIG-005/SIG-006): diff-pair intent JSON; length-match constraints JSON; mixed-signal ground roles + merge hints; DRC warn/fail on undocumented AGND↔DGND split.
- **Reliability** (REL-001/REL-003): passive voltage derating with ambient temperature margin; per-net minimum test-point counts.
- **Fab profiles** (MFG-004): `jlc.json`, `generic_2layer.json`, `eurocircuits_4layer.json`, `oshpark_2layer.json`.
- **CLI** (SW-002): `openhac compile`, `simulate`, `doctor`, `export fab`, `export assembly`; `--skip-layout`, `--deterministic`, `--require-verified-parts`, `--kicad-symbol-dir`, `--kicad-footprint-dir`, `--sync-jlc-before`, `--auto-enrich-board`, `--catalog-overlay`, and more.
- **Database schema** evolved through v8: parametric fields (v2), SPICE subckt (v3), part_offers (v4), alternate group IDs (v5), pinout_json / symbol_data (v6), thermal / dimensions / lifecycle / compliance / supply chain (v7), package / stock (v8).

### Stretch batches (Apr 2026)

- **ERC plugin registry**: `openhac.stdlib.erc_plugin_registry` — stable names for all `erc_rule_packs` exports; `register_erc_plugin` / `apply_erc_plugin` / `list_erc_plugin_names`; `Board.apply_erc_plugin`.
- **LIB-005 per-class JLC line budgets**: `Board(jlc_class_line_limits=...)`; `jlc_class_line_counts_from_circuit()`; manifest `jlc_assembly_line_summary.by_class`.
- **REL-001 capacitor temperature derating**: `Board.ambient_operating_temp_c` + `cap_voltage_temp_derating_percent_per_c` + `cap_voltage_rating_reference_temp_c`; DRC applies temp factor to cap voltage check.
- **REL-003 per-net test-point minimums**: `Board.test_point_min_count_by_net`; DRC `_count_test_points_on_net_ci`; manifest `rel003_test_point_min_count_by_net`.
- **PCB-007 KiCad netclass handoff**: `_netclass_suggestions` / `_write_netclass_hint_md`; `{project}.openhac-netclass-hint.md`; `netclass_suggestions` in routing handoff JSON.
- **SIG-006 pcbnew keepouts and net-ties**: `declare_keepout_rect`; `declare_net_tie`; auto net-tie intent from `declare_net_merge_hint(via='net_tie')`; emitted into `.kicad_pcb` when pcbnew available.
- **Catalog overlays**: bundled `package_catalog_overlays/*.json` merge automatically; `--catalog-overlay` / `OPENHAC_CATALOG_OVERLAY` for project-specific overrides.
- **Auto board sizing**: tight deterministic pack using pcbnew footprint bboxes; `OPENHAC_AUTO_BOARD_PACK_COLS`, `OPENHAC_AUTO_BOARD_MARGIN_FACTOR`, `OPENHAC_AUTO_BOARD_MIN_EDGE_MARGIN_MM`.
- **schema.sql updated to v8**: schema file now reflects all migration columns so fresh installs and test setups get the complete table definition.
- **pyproject.toml**: removed unused `setuptools-scm` build dependency (version is hardcoded).
