# Implementation status (OpenHaC)

Track record of fixes applied against [PRODUCTION_READINESS_SPEC.md](./PRODUCTION_READINESS_SPEC.md). Update this file when you close spec items.

### Why are many rows **Partial**?

In this repo, **Done** means the spec’s *full* target state is met (or the spec was narrowed to match). **Partial** means we shipped something **useful and real** that moves toward the ticket, but one or more of the following still applies:

1. **Upstream / tool boundary** — e.g. true schematic pin coordinates need KiCad symbol geometry; full ratsnest sign-off needs KiCad GUI or deeper `pcbnew` API use (**SCH-001**, **PCB-002**).
2. **Explicit “phase 2” in the spec** — e.g. manifest exists, but human sign-off or deterministic release zips are a separate step (**STR-002**, **MFG-005**).
3. **Policy or product depth** — e.g. alternates table + BOM column exist, but CM-specific offer expansion does not (**LIB-002**); JIT strictness exists, but a single `Board(strict=True)` umbrella does not (**LIB-003**).
4. **Optional CI / environment** — e.g. full layout smoke depends on distro KiCad + Python bindings (**SW-006** `kicad-layout-smoke` is `continue-on-error` until stable).

**Dependencies:** Some partials *do* depend on later work (e.g. richer **SIG-002** netclasses help **PCB-007**). Others are **documentation-only** or **integration** gaps and do not block unrelated tickets. Use [PRODUCTION_READINESS_SPEC.md](./PRODUCTION_READINESS_SPEC.md) per-ID **Target state** / **Approach** for the intended sequence.

### Phased completion & velocity

The normative spec often describes an **end state** (e.g. multi-sheet KiCad, full SI). Closing **~30 Partial rows** to literal **Done** is a **multi-month** program, not a single change set. To move faster *without* pretending unfinished work is finished:

1. **Phase-1 acceptance** — Ship a **tested, narrow** slice per ID; record it in the Notes column (what shipped + explicit “still future”).
2. **Tighten spec text when appropriate** — If Phase-1 matches product intent for an ID, narrow **Target state** / **Acceptance** in [PRODUCTION_READINESS_SPEC.md](./PRODUCTION_READINESS_SPEC.md) so **Done** is achievable.
3. **Parallel workstreams** — Split by subsystem (manifest/BOM, DRC/ERC, CLI, fab profiles, simulation) so multiple contributors or sessions don’t conflict.
4. **Let CI enforce “done”** — Prefer deterministic pytest (and optional KiCad jobs) over manual ticket sign-off for each increment.

| Spec ID | Status | Notes |
|---------|--------|--------|
| **SW-003** | Done | Netlist/BOM generation raises on failure; `Board.compile()` no longer swallows importer errors for core steps. |
| **SW-002** | Done | `openhac compile` / `simulate` resolve a `board` variable and call `compile()` / `simulate()` with `--name`, `--no-route`, `--no-schematic`, optional `-o` / `output_dir`. |
| **SW-001** | Done | GitHub Actions workflow runs Ruff + pytest on Python 3.11 and 3.12. |
| **PWR-001** | Done | Per-rail ERC: dict `source_current_max_ma` vs dict `max_current_draw_ma` by rail key; scalar draw forbidden when dict supply is used; nested scalar `source_current_max_ma` ignored under a dict-supply subtree. DRC still sums dict draws for conservative IPC width. |
| **SCH-001** | Partial | **``.kicad_sym``** pin **``(at)``** lookup (**``kicad_sym_pinpos``** + **``SymbolPinResolver``**); wires/labels use library offsets when **``Device.kicad_sym``** (etc.) is on **``OPENHAC_KICAD_SYMBOL_DIRS``** / **``KICAD*_SYMBOL_DIR``**; manifest **``sch_kicad_symbol_dirs_configured``**; **``EmptySymbolPinResolver``** forces legacy index stubs; **``part_library_name``** for **``SchLib``**; **alphanumeric natural sort** for non-numeric pin numbers on nets (BGA-style order). Golden graph isomorphism vs KiCad pin coords still future. |
| **PCB-001** | Partial | Footprints loaded from `*.pretty` via `PCB_IO_MGR.KICAD_SEXP`; refs/values and module-grid positions applied. |
| **PCB-002** | Partial | Pads get `NETINFO_ITEM` from SKiDL pin nets; **``pin_pad_coverage_warnings``** vs **``.kicad_mod``**; **``Board(strict_footprint_pin_pad_match=True)``** → **``generate_layout``** raises **``LayoutGenerationError``** if any connected pin lacks a matching pad name. Full KiCad ratsnest vs GUI parity not guaranteed. |
| **Layout stub** | Done | Failed `pcbnew` no longer writes a fake minimal `.kicad_pcb`; raises `LayoutGenerationError`. |
| **Z3 overlap** | Done | Non-overlap constraints use the same **all_modules** list as bounds (nested modules consistent). |
| **PCB-005** | Done | `distance_min` uses axis-aligned bbox minimum gap (`layout_constraints.add_bbox_minimum_gap`); `distance_max` uses center L1 (`add_center_l1_max`). |
| **PCB-006** | Done | DRC **fails** if IPC-2152 width for `max_current_draw_ma` exceeds default `min_trace_width_mm` (0.15mm). |
| **MFG-001** | Done | ``openhac export fab <pcb> -o <dir>`` runs ``kicad-cli`` **gerbers**, **drill** (Excellon mm), **pos** (CSV mm, front+back). Optional ``--ipc2581``. Optional ``--zip`` / ``--zip-file`` zips the output directory. |
| **STR-001** | Done | [SCOPE.md](./SCOPE.md) defines capability tiers A–C + non-goals; README “What it does” aligned. |
| **SW-004** | Partial | README + **``docs/RELEASE_CHECKLIST.md``**; **``scripts/verify_openhac_version.py``** + **``scripts/check_release_strings.py``** + **``scripts/check_changelog_version.py``** (``CHANGELOG.md`` **``## [version]``** vs pyproject) + CI; User-Agent / version; **``scripts/example_build.py``**; CLI **``export assembly``**, release flags. |
| **SCH-004** | Done | ``Board.declare_power_rail(name, net)`` registers net IDs; PWR_FLAG ERC applies to declared rails **or** default prefixes **or** **``Board(power_net_prefixes=...)``**; single-pin power nets are not double-reported as floating (PWR_FLAG supplies the second anchor). KiCad **functional pin types** in-tool still future. |
| **SCH-005** | Partial | ``register_erc_hook``; **``uart_rx_pullup_erc_hook``**, **``one_wire_pullup_erc_hook``**, **``i2c_pullup_erc_hook``**, **``mdio_pullup_erc_hook``**, **``spi_cs_pullup_erc_hook``**, **``reset_pullup_erc_hook``**, **``missing_footprint_erc_hook``** + tests. Built-in digital rule packs still future. |
| **LIB-005** | Partial | BOM **``JLC_Class``**; manifest **``jlc_assembly_line_summary``**; **``max_jlc_extended_parts``** / **``warn_jlc_extended_parts``**; **``max_jlc_basic_parts``** DRC cap. Per-class budgets still future. |
| **MFG-002** | Done | ``export_assembly_csv`` / ``openhac export assembly <pcb> -o <dir>`` (KiCad pos CSV via ``kicad-cli``). |
| **MFG-003** | Partial | **``examples/fab_stackup_table.md``** (links **``.openhac-fab-handoff.md``**); **``declare_stackup_reference(..., documentation_note=...)``** → manifest + fab handoff markdown; **``--zip-release``** when present. PDF generation still future. |
| **STR-002** | Partial | **``git_branch``**; **``release_bundle_suffixes``** (incl. alternates, SI reminder, **``.openhac-bom-expand-hint.md``**, **``.openhac-spice-model-hint.md``**, **``.openhac-autoroute-policy.md``**); **``compile_options``**, **``openhac_env_keys_present``**, **``sch_kicad_symbol_dirs_configured``**, **``pcb_pipeline_handoff``**, **``jit_confidence_histogram``** (when non-empty), **``stackup_json_summaries``** (JSON stackup refs), **``release_zip_path``** when zipping; **``fab_profile``** when set; **``length_match_group_count``**; prior keys (**``compile_strictness``**, hierarchy, spice summary, etc.) unchanged; optional **``.sha256``** sidecar. Human sign-off / full CI golden matrix still future. |
| **SW-006** | Partial | **``OPENHAC_SKIP_LAYOUT``** pytest covers logic-only **``compile``**; subprocess **``openhac simulate … --spice-preset ac``** E2E (``.cir`` contains preset directive); **``Board.simulate``** + **``spice_analysis_json_path``** contract test; **``scripts/ci_full_compile_smoke.py``**; **``kicad-layout-smoke``** (**``continue-on-error``**). |
| **ARCH** | Partial | **[docs/ARCHITECTURE.md](./ARCHITECTURE.md)**: **contextvars** compile context; **no** ``Board`` → ``Component`` **class-attribute stomp**; **``Module.__iter__``** + ERC/DRC walks; **``Module.add_part``** / **``parent_module=``** for host-board strict at construction; **``compile_pipeline``** phase coordinator; schematic **alphanumeric pin sort**; JIT **category + word-boundary** matching; **``Board.power_net_prefixes``**; CLI copies strict flags onto **board** before **compile**. Full plugin registry still future. |
| **LIB-003** | Partial | JIT maps **high/medium/low**; **``Board(strict=True)``** + CLI **``--strict``**; live API match uses **category blob** (when API provides it) + **word-boundary** tokens on description; manifest **``compile_strictness``**; BOM **``OpenHaC_JIT_Confidence``** / **``OpenHaC_JIT_Score``**. Unified numeric model + first-class **functional tags** in DB still future. |
| **LIB-002** | Partial | **``part_alternates``** + BOM columns; **``{project}.openhac-bom-alternates.json``** + **``{project}.openhac-bom-expand-hint.md``** when alternates file exists; release zip suffixes. CM-specific BOM expand/collapse templates still future. |
| **LIB-006** | Partial | **``strict_passive_catalog_fields``** (tolerance on R/C/L); **``strict_passive_attributes_json``** → non-empty valid JSON **object** in DB **``attributes_json``** for R/C/L-class parts. Unified parametric schema still future. |
| **REL-003** | Partial | **``min_test_points``**; **``require_test_point_on_nets``** (case-insensitive net names) → DRC requires a heuristic test point on each net. Per-net-class budgets / JTAG still future. |
| **SIG-005** | Partial | **``length_match_groups``** in manifest + **``{project}.openhac-length-match-hint.md``**; bundled in **``--zip-release``** when present. KiCad-native constraint export still future. |
| **SIG-006** | Partial | **``net_roles``** / **``net_merge_hints``** in manifest + **``{project}.openhac-mixed-signal-hint.md``**; same data in **``.openhac-pcb-routing-handoff.json``**; bundled in **``--zip-release``** when present. Automated merge / AGND enforcement still future. |
| **PWR-002** | Partial | **``stdlib.power.buck_input_current_ma``** (ideal buck input mA from output mA, rail voltages, efficiency) + ERC tests; **``extra_input_draw_by_rail_ma``** still merged as before. Regulator object graph / auto tree still future. |
| **PCB-004** | Partial | Example **``docs/fab_stackup_jlc_example.json``**; **``declare_stackup_reference``** → manifest **``stackup_references``** + fab handoff; **``stackup_json_summaries``** for referenced **``*.json``** stackup files. Parser-driven stackup merge still future. |
| **SCH-002** | Partial | **[SCOPE.md](./SCOPE.md)** flat **``.kicad_sch``**; manifest **``logical_modules``** + **``schematic_hierarchy_handoff``**; **``examples/hierarchy_authoring.md``** (manual KiCad sheet split vs manifest). Multi-sheet **``.kicad_sch``** / sheet pins not generated yet. |
| **Board DRC** | Done | ``Board.min_trace_width_mm`` overrides global IPC comparison threshold. |
| **Interface validation** | Done | `_validate_interfaces()` raises `UnconnectedInterfaceError` again when a net has fewer than two pins. |
| **ERC net-level** | Done | `_check_net_level` uses `get_default_circuit()` and raises `OpenHaCError` if the circuit cannot be read; silent `except: pass` on pin checks replaced with warnings. |
| **SCH-003** | Partial | ``kicad-cli sch erc``; **``--kicad-erc-json``** / **``kicad_sch_erc_format``**; **``kicad_erc_report.summarize_kicad_erc_report``**; **``run_kicad_schematic_erc(..., strict=False)``** for JSON inspection without raising. CI job **``kicad-schematic-erc``** runs **``scripts/ci_kicad_sch_erc_golden.py``** (zero ERC errors). **``scripts/kicad_erc_optional.sh``**. Broader golden matrix still future. |
| **LIB-004** | Partial | **``--strict-kicad``** / **``--production``**; **``Board.strict_kicad``** without mutating **``Component``** class (use **``Module.add_part``** / **``parent_module=``** or CLI/env for symbol load time); **``OpenHaC_WATERMARK``** BOM column; **``bom_profile``** **``prod``** / **``production``** / **``cm``** → CSV omits internal & alternate columns; manifest **``bom_prod_omitted_columns``**. Further CM templates still future. |
| **SW-005** | Done | Public ``openhac.circuit.get_circuit()`` alias of ``get_default_circuit()``; compiler still imports the latter internally. |
| **SIG-004** | Done | [SCOPE.md](./SCOPE.md) states EMC/EMI is manual + test lab (no automated sign-off). |
| **SIM-003** | Done | [SCOPE.md](./SCOPE.md) lists digital verification (timing/CDC/formal) as a non-goal for core. |
| **PCB-007** | Partial | **``declare_no_autoroute_net()``**; manifest **``no_autoroute_nets``**; **``{project}.openhac-autoroute-policy.md``** (skip layout / no-autoroute nets / diff pairs / **``auto_route=False``**); **``{project}.openhac-pcb-routing-handoff.json``**. KiCad netclass export still future. |
| **PCB-009** | Partial | **``declare_copper_pour_intent(net, layer=..., purpose=...)``** → manifest + routing handoff + SI reminder; no **``pcbnew``** zone emission yet. |
| **PCB-010** | Partial | **``declare_mounting_hole(x_mm, y_mm, diameter_mm, note=...)``** → manifest + routing handoff; no NPTH geometry yet. |
| **SIG-002** | Partial | DRC warns on **``route_differential_pair``**; **``diff_pair_intent``** in manifest + **``.openhac-pcb-routing-handoff.json``**; **``.openhac-si-stackup-reminder.md``** lists per-pair target Z0 when declared. Full netclass automation still future. |
| **MFG-005** | Partial | **``--zip-release``** → **``zip_project_outputs``** (suffixes include BOM alternates, BOM expand hint, spice model hint, autoroute policy, SI reminder, mixed-signal, length-match, **``pcb-routing-handoff.json``**); manifest **``release_bundle_suffixes``**. Signing / immutable policy still future. |
| **SIM-001** | Partial | DB **``spice_include``** / **``spice_subckt``** → BOM fields + **``generate_spice``**; manifest **``spice_annotation_summary``**; **``{project}.openhac-spice-model-hint.md``** when annotation summary non-zero. Rich vendor model tables still future. |
| **SIM-002** | Partial | **``--spice-line``** / **``--spice-preset``** / **``--spice-analysis-json``** (CLI subprocess E2E covered for **ac** preset); **``Board.simulate(..., spice_analysis_json_path=...)``**; **``.cir``** comment block lists directives; presets **tran**, **ac**, **op**, **dc**, **noise**. YAML simulation block still future. |
| **LIB-001** | Partial | **``part_offers``** + BOM **``Ranked_Offers``** + **``Primary_Offer``** + **``Secondary_Offer``** + **``Offer_Count``** (prod BOM omits offer columns per **LIB-004**). CM-specific offer pickers / UI still future. |
| **MFG-004** | Partial | **``jlc.json``**, **``generic_2layer.json``**, **``eurocircuits_4layer.json``**, **``oshpark_2layer.json``**; **``declare_dfm_reference(path, role=..., documentation_note=...)``** → manifest **``dfm_references``**; **``fab_profile``** merges into IPC DRC baseline. External DFM tool hooks still future. |
| **PCB-003** | Partial | ``Board.layers > 2`` logs stackup warning; manifest **``pcb_stackup_layer_note``**; **``{project}.openhac-si-stackup-reminder.md``** when stackup / SI triggers fire; **``docs/stackup_template.yaml``**. No pcbnew stackup emission. |
| **REL-001** | Partial | **``require_passive_voltage_ratings``** / **``require_resistor_voltage_ratings``** / **``require_passive_power_ratings``**; **``require_inductor_voltage_ratings``**; **``require_cap_voltage_derating_ratio``** + **``declared_supply_voltages_v``**. Broader policy module / temp derating still future. |
| **REL-002** | Done | [SCOPE.md](./SCOPE.md) states mains/isolation is not tool-certified. |
| **PCB-008** | Done | [SCOPE.md](./SCOPE.md) documents manual BGA/fanout path. |
| **SIG-001** | Partial | Example **``docs/stackup_template.yaml``**; **``declare_stackup_reference``**; **``.openhac-si-stackup-reminder.md``** ties stackup refs + multi-layer + diff pairs + pour intent to external SI workflow. In-tool SI solver still future. |
| **SIG-003** | Done | [SCOPE.md](./SCOPE.md) non-goals: PDN/decap not automated in core. **``examples/pdn_checklist_handoff.md``** for human PI checklist. |

### “Next 30 tickets” batch (Apr 2026)

Closing every **Partial** row to literal **Done** is still a **multi-phase** effort. This batch lands **cross-cutting architecture** (see **ARCH** row and [ARCHITECTURE.md](./ARCHITECTURE.md)) plus targeted spec movement on **SCH-001** (alphanumeric pin order), **SCH-004** (**``power_net_prefixes``**), **LIB-003** (category-aware / word-boundary JIT matching), and **LIB-004** (instance-level strict KiCad without `Board` mutating **``Component``** globals). The remaining **Partial** IDs stay open; continue subsystem-by-subsystem with tests and status updates.

## How many tickets are left?

[PRODUCTION_READINESS_SPEC.md](./PRODUCTION_READINESS_SPEC.md) defines **48** numbered requirement sections (STR-, LIB-, SCH-, SIG-, PCB-, SIM-, MFG-, PWR-, REL-, SW-).

This table does **not** list all 48—only items we have explicitly closed or partially shipped:

| Bucket | Approx. count | Meaning |
|--------|----------------|--------|
| **Done** (spec-aligned rows above) | **17** | SW-001–003/005, PWR-001, PCB-005/006, MFG-001/002, STR-001, SCH-004, SIG-003/004, SIM-003, REL-002, PCB-008 |
| **Partial** | **~30** | Rows above with status **Partial** (exact count drifts as rows are added); none are “fully done” to spec acceptance until notes say **Done**. |
| **Done (extra rows)** | **5** | Layout stub, Z3 overlap, Board DRC, interface validation, ERC net-level (overlap spec themes but not a single ID) |
| **Not individually tracked here** | **~3** | Spec IDs with no dedicated row yet (approx.; deeper SIM-only / niche PCB items). |

**So:** if you count “left” as *anything not fully done to spec acceptance*, roughly **~30** table rows stay **Partial**, plus **~3** spec IDs not given their own row. The normative spec lists **48** numbered IDs (**STR/LIB/SCH/SIG/PCB/SIM/MFG/PWR/REL/SW**); many are **Done**, but **full closure** of every ID’s *target state* is still a multi-phase effort. Use the spec’s roadmap table for priority order.

## CLI usage

- Prefer: `openhac compile my_design.py --name out`
- For `python my_design.py`, wrap `board.compile(...)` in `main()` under `if __name__ == "__main__":` so importing the file (for tools) does not compile twice.
- Optional env: **`OPENHAC_DB_PATH`** (SQLite catalog file), **`OPENHAC_SKIP_LAYOUT`** (`1` / `true` / `yes` — skip `pcbnew` layout + autoroute; netlist/BOM/manifest only), **`OPENHAC_KICAD_SYMBOL_DIRS`** (pathsep-separated dirs prepended for **``.kicad_sym``** pin positions / SCH-001).

## `.gitignore` policy

- **Tracked:** `tests/**/*.py` and `tests/conftest.py` (required for CI).
- **Ignored:** pytest/Hypothesis/benchmark caches under `tests/`, `tests/tmp/`, `tests/fixtures/generated/`, coverage artifacts, generated KiCad/SPICE outputs, local DB, `*-release.zip`, etc. — see root `.gitignore` (policy block at file end).
