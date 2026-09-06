# Implementation status (OpenHaC)

Track record of fixes applied against [PRODUCTION_READINESS_SPEC.md](./PRODUCTION_READINESS_SPEC.md) (Phase-1), [FABRICATION_READINESS_SPEC.md](./FABRICATION_READINESS_SPEC.md) (Phase-2), [SCHEMATIC_SIGN_OFF_SPEC.md](./SCHEMATIC_SIGN_OFF_SPEC.md) (**SSO-***), [SPICE_SIGN_OFF_SPEC.md](./SPICE_SIGN_OFF_SPEC.md) (**SPS-***), [LIVE_KICAD_SPEC.md](./LIVE_KICAD_SPEC.md) (**LIVE-***), [CATALOG_DEPTH_SPEC.md](./CATALOG_DEPTH_SPEC.md) (**CAT-*** / **3D-*** / **SPS-05x**), and [WORKFLOW_GATES_SPEC.md](./WORKFLOW_GATES_SPEC.md) (**ECO-*** / **LOCK-*** / **MFG-010** / **PWR-010** / **PIN-001** / **VAR-001** / **LIVE-010** / **PLC-001** / **TST-001** / **GLD-001**). Live follow-on work is the [Sep 2026 job spec](#audit-follow-on-job-spec-sep-2026) at the top of this file. Update this file when you close spec items.

## Audit follow-on job spec (Sep 2026)

Normative executable backlog from the Sep 2026 code, overfitting, live-schematic, and performance audits. Historical Phase-1/2/SSO/SPS tables below stay as shipped history; IDs that those tables mark **Done** but the audit reopened were listed here as **Open** and are **Done** in this batch.

**Claim:** Python remains the HDL. KiCad remains the drawing renderer and ERC stamp (`kicad-cli sch erc` under `--schematic-signoff`). Do **not** rewrite the package for speed. Do **not** replace KiCad ERC with a webview or a second symbol renderer.

**Execution order:** P0 fail-closed (A) → PERF-001/002 → FAB-041 + SSO-012 → claim/overfitting (C) → remaining PERF + hygiene (E).

**Out of scope:** language rewrite; custom ERC instead of `kicad-cli sch erc`; `--require-all` implying HS/RF/EMC; HTTP fetch of vendor SPICE `.lib`.

### Summary

| Spec ID | Pri | Status | One-line target |
|---------|-----|--------|-----------------|
| **FAB-004** / **SPS-007** | P0 | Done | Gate SKiDL fallbacks; no silent `builtins.default_circuit` |
| **FAB-023** | P0 | Done | Physics net-class apply fails closed under fabrication |
| **FAB-013** | P0 | Done | Enrich `lookup_failed` aborts under fab; CI asserts `gates_passed` |
| **FAB-010** / **ABC-016** | P0 | Done | `network_allowed()` on parametric JIT / `fetch_and_map_part` |
| **CODE-001** | P0 | Done | Restore `OPENHAC_DEFER_COPPER_POURS`; SaveBoard stays in-process |
| **FAB-041** | P1 | Done | Deprecate Cytoscape webview; IR JSON may remain |
| **SSO-012** | P1 | Done | `openhac preview` = schematic + KiCad SVG; never ERC |
| **SSO-041** | P1 | Done | CI golden is `sso041_signoff_node.py`, not RS-485 |
| **FAB-051** | P1 | Done | Honest `--require-all` class (2R only, or add a multi-IC) |
| **ABC-008** | P1 | Done | Document route subset ≠ all complex boards |
| **LIB-007** | P1 | Done | Bundled reference BOM is opt-in overlay, not every lookup |
| **ABC-046** | P1 | Done | RF policy from class / `RF_Module:` prefix, not ESP32 substring |
| **SCH-006** | P1 | Done | Schematic columns from sheet tags, not `ldo`/`rs485` names |
| **CODE-003** | P1 | Done | Stdlib pin maps / RF fallback: catalog or fail |
| **CODE-004** | P1 | Done | Named placement profile; ABC-007 stays generic |
| **SPS-045** | P1 | Done | Tracked analog-island CI fixture, or Fundi stays out of the compiler |
| **PERF-001** | P1 | Done | Catalog indexes + dedupe (`SCAN` → indexed lookup) |
| **PERF-002** | P1 | Done | One SQLite connection; stdlib must not `DatabaseManager()` per part |
| **PERF-003** | P1 | Done | Parametric value/package columns or FTS; no leading `LIKE '%…%'` |
| **PERF-004** | P2 | Done | `Component.__init__`: one get + one alternates query |
| **PERF-005** | P2 | Done | Cache `schematic_lib_symbol_sexp` like pinpos |
| **PERF-006** | P1 | Done | Compile profiles preview / logic / fab; lazy manifest |
| **PERF-007** | P2 | Done | Phase wall-clock ms in the manifest |
| **PERF-008** | P2 | Done | Stretch partial: reuse pcbnew `BOARD` place→autoroute |
| **CODE-002** | P2 | Done | Isolate all `OPENHAC_*` in pytest; no dotenv for unit tests |
| **CODE-005** | P2 | Done | Escape or delete webview HTML until FAB-041 lands |
| **FAB-050** | P2 | Done | Grow mypy island: schematic IR, spice_gen, compile_pipeline |
| **CODE-006** | P2 | Done | Invented `Pin_N` count in CLI/manifest (handoff) |

**Open in this batch:** **0**. Closed 4 Sep 2026 (`pytest tests/`: 640 passed, 6 skipped; mypy island exit 0). **CODE-001:** env restore shipped; `pcbnew.SaveBoard` remains in-process (SIGSEGV is not catchable). **PERF-008:** stretch partial — `generate_layout` board reused into autoroute, not through zone fill.

Follow-on (not a reopen of FAB/PERF): live KiCad artwork overlay — [LIVE_KICAD_SPEC.md](./LIVE_KICAD_SPEC.md) (**LIVE-001…008**). Catalog depth, 3D pointers, and SPICE operator follow-on — [CATALOG_DEPTH_SPEC.md](./CATALOG_DEPTH_SPEC.md) (**CAT-001…015**, **3D-001…005**, **SPS-050…057**). Operator workflow gates — [WORKFLOW_GATES_SPEC.md](./WORKFLOW_GATES_SPEC.md) (**ECO-001**, **LOCK-001**, **MFG-010**, **PWR-010**, **PIN-001**, **VAR-001**, **LIVE-010**, **PLC-001**, **TST-001**, **GLD-001**). Does not reopen **SPS-010…044**. HTTP fetch of vendor SPICE `.lib` stays out of scope (**SPS-019** reserved unused).

---

## Live KiCad artwork overlay (LIVE-*)

Python remains the electrical source of truth. Saved `.kicad_sch` / `.kicad_pcb` are an artwork overlay (pose + user copper/wires), merged on emit. Not a second HDL: KiCad connectivity that disagrees with the graph fails compile. Preview still never runs `kicad-cli sch erc`.

| Spec ID | Pri | Status | One-line target |
|---------|-----|--------|-----------------|
| **LIVE-001** | P1 | Done | Overlay schema; key by symbol UUID then refdes (KiCad 9 `R?`) |
| **LIVE-002** | P1 | Done | Keep schematic symbol `(at x y rot)` / unit on merge; KiCad 9 instances |
| **LIVE-003** | P1 | Done | Keep PCB footprint xy/rot; skip Z3 for fully overlaid boards |
| **LIVE-004** | P1 | Done | Re-apply tracks/vias/zones; drop copper whose net vanished |
| **LIVE-005** | P1 | Done | Keep sch wires/labels/graphics for nets still in the graph |
| **LIVE-006** | P1 | Done | `--keep-kicad-artwork` / `--regenerate-artwork`; parity fail-closed |
| **LIVE-007** | P2 | Done | `preview --pcb` place-only merge on watch; no route/ERC |
| **LIVE-008** | P2 | Done | `--watch` localhost SVG viewer of KiCad export; `--no-browser` |

Pointer (not a reopen): KiCad 10 PCB IPC revert is **LIVE-010** in [WORKFLOW_GATES_SPEC.md](./WORKFLOW_GATES_SPEC.md).

---

## Catalog depth, 3D pointers, SPICE operator follow-on (CAT-* / 3D-* / SPS-05x)

Packed catalog is **depth** (named pin table + real footprint + 3D pointer), not SKU count. `--production` stays offline. Git does not ship proprietary `.lib`. Spec: [CATALOG_DEPTH_SPEC.md](./CATALOG_DEPTH_SPEC.md). Closed 6 Sep 2026 with focused pytest (`tests/test_catalog_depth.py`, `tests/test_catalog_sync_widen.py`, `tests/test_spice_operator.py`, plus related catalog/SPICE suites). HTTP fetch of vendor SPICE `.lib` stays out of scope (**SPS-019** reserved unused).

| Spec ID | Pri | Status | One-line target |
|---------|-----|--------|-----------------|
| **CAT-001** | P0 | Done | Completeness grades: `compile_ready` vs `warehouse` |
| **CAT-002** | P0 | Done | Widen jlcsearch typed categories (probe first) |
| **CAT-003** | P1 | Done | `--include-extended` on sync, capped; default stays Basic |
| **CAT-004** | P0 | Done | Pin policy: 2-pin passives; never numeric-only IC pinouts |
| **CAT-005** | P0 | Done | `database enrich --missing-pinouts`; not called from `--production` |
| **CAT-006** | P0 | Done | `openhac catalog coverage` JSON; no fetch |
| **CAT-007** | P0 | Done | `import_lcsc_csv` is warehouse, not success |
| **CAT-008** | P1 | Done | Overlay keys for 3D hash/licence and spice pointers |
| **CAT-009** | P1 | Done | Persist `catalog_tier` verified vs warehouse |
| **CAT-010** | P1 | Done | Optional Nexar/Octopart behind keys; fail closed; not default CI |
| **CAT-011** | P2 | Done | Second PCBA catalog as `part_offers`, not a second SoT |
| **CAT-012** | P2 | Done | SnapEDA/UL/SamacSys licence-gated; no silent redistrib |
| **CAT-013** | P1 | Done | KiCad symbol lib as pin-name oracle (not `Device:IC`) |
| **CAT-014** | P2 | Done | Maintainer snapshot job; not `--production` |
| **CAT-015** | P2 | Done | Parametric twins via `part_alternates` / `part_offers` |
| **3D-001** | P0 | Done | `model_3d_sha256` / license / source provenance |
| **3D-002** | P0 | Done | Prefer KiCad library 3D for JEDEC passives |
| **3D-003** | P0 | Done | `catalog prefetch-3d`; forbidden under fab / no-network |
| **3D-004** | P0 | Done | Missing 3D is a coverage row; no fake cube |
| **3D-005** | P0 | Done | No STEP/WRL in git; cache under `~/.kiro/openhac/` |
| **SPS-050** | P0 | Done | `openhac spice coverage BOARD.py` without ngspice |
| **SPS-051** | P1 | Done | Vendor-record template; `download_page` ignored by loader |
| **SPS-052** | P0 | Done | `openhac spice verify-vendor-dir` hash + arity; no network |
| **SPS-053** | P0 | Done | More Apache physics decks (diode / opto / in-amp); not vendor twins |
| **SPS-054** | P1 | Done | Refuse encrypted / LTspice `.asc`; ngspice only |
| **SPS-055** | P1 | Done | Stamp `spice_include` / `spice_subckt` from registry on `get_component` |
| **SPS-056** | P0 | Done | USER_GUIDE: vendor dir → overlay → verify → `--spice-signoff` |
| **SPS-057** | P0 | Done | Non-goals restatement; **SPS-019** remains reserved |

---

## Workflow gates (ECO / LOCK / MFG / PWR / PIN / VAR / LIVE-010 / PLC / TST / GLD)

Python remains the HDL. Native graph is electrical SoT. KiCad is the artwork overlay (**LIVE**). `--production` stays offline (**FAB-010**). `--require-all` stays the 2R golden (**FAB-051**). Spec: [WORKFLOW_GATES_SPEC.md](./WORKFLOW_GATES_SPEC.md). HTTP fetch of vendor SPICE `.lib` stays out of scope.

| Spec ID | Pri | Status | One-line target |
|---------|-----|--------|-----------------|
| **ECO-001** | P0 | Done | `{project}.openhac-eco.json` graph diff vs previous snapshot |
| **LOCK-001** | P0 | Done | `openhac.lock`; fab fail-closed when present or `--require-lock` |
| **MFG-010** | P0 | Done | `openhac export jlc` JLC BOM/CPL; no invented SKUs |
| **PWR-010** | P0 | Done | `declare_rail` + `draws_from`; over-current fails ERC |
| **PIN-001** | P0 | Done | `openhac pinout init`; refuse numeric-only IC tables |
| **VAR-001** | P0 | Done | Board variants / DNP on BOM, not netted or placed |
| **LIVE-010** | P1 | Done | Best-effort KiCad 10 PCB IPC revert; no schematic fake |
| **PLC-001** | P1 | Done | Overlay pose vs outline / courtyard on freeze/intent |
| **TST-001** | P1 | Done | `declare_testpoint`; `--require-testpoints` / fab fail-closed |
| **GLD-001** | P1 | Done | SPICE-island golden uses bundled Apache physics; 2R `--require-all` unchanged |

---

### A — Fail-closed (P0)

#### FAB-004 / SPS-007 — Ungated SKiDL circuit fallback

| Field | Content |
|-------|---------|
| **Severity** | P0 |
| **Problem** | If the native circuit looks empty, SPICE and schematic harvest silently use `builtins.default_circuit`. ERC can pass one graph while ngspice or `.kicad_sch` uses another. `OPENHAC_LEGACY_SKIDL` already gates `get_default_circuit()`. |
| **Current state** | `openhac/compiler/spice_gen.py` `_circuit_and_parts` (~215–230): SKiDL fallback, `except Exception: pass`. `openhac/schematic/collect.py` (~64–80): same pattern. Status table still marks FAB-004 Done. |
| **Target state** | Fallback only when `OPENHAC_LEGACY_SKIDL=1`. Under spice-signoff / fabrication / schematic-signoff: raise if native parts are empty. Never silent cross-circuit fallback. |
| **Acceptance criteria** | Tests: empty native + populated SKiDL does not emit SPICE/schematic from SKiDL unless the env flag is set. Sign-off raises. Dual-scan in ERC stays gated the same way. |
| **Approach** | Share `_legacy_skidl_enabled()` from `openhac/circuit.py`. Fail closed in `spice_gen` and `collect`. |

#### FAB-023 — Physics apply swallowed under fabrication

| Field | Content |
|-------|---------|
| **Severity** | P0 |
| **Problem** | IPC-2152 / physics net-classes can fail and the compile still exits 0. |
| **Current state** | `openhac/compiler/compile_pipeline.py` `phase_autoroute` (~692–780) wraps `apply_physics_net_classes` in `try/except` → `logger.warning` and continue. Same class of swallow in `layout_gen.py`. Status table marks FAB-023 Done. |
| **Target state** | Re-raise when `compile_goal=fabrication`. Empty current-set is an explicit skip recorded on `fab_audit`, not an exception swallow. |
| **Acceptance criteria** | Test: fabrication compile with `apply_physics_net_classes` raising exits non-zero. Handoff may warn. |
| **Approach** | Helper `or_raise_if_fab(goal, err)` on physics apply. |

#### FAB-013 — Enrich failures abort; `gates_passed` is a gate

| Field | Content |
|-------|---------|
| **Severity** | P0 |
| **Problem** | `lookup_failed` is copied into the manifest (`gates_passed: false`) and compile still exits 0. CI does not read that bit. |
| **Current state** | Failures appended in `compile_pipeline.py` (~147–153). `gates_passed` computed in `compile_manifest.py` (~1487) as JSON only. `scripts/ci_validate_fab_gates.py` / `ci_validate_production.py` check omitted footprints / compile_goal, not `gates_passed`. |
| **Target state** | Fabrication aborts after enrich when `enrich_failures` is non-empty. Validators assert `fab_audit.gates_passed is True` and empty `enrich_failures`. |
| **Acceptance criteria** | Negative fixture: enrich fail + `--production` → non-zero. Golden CI fails if the audit lies. |
| **Approach** | Raise in `phase_enrich_parts` under fabrication; extend `_assert_fab_audit`. |

#### FAB-010 / ABC-016 — JIT ignores `OPENHAC_NO_NETWORK`

| Field | Content |
|-------|---------|
| **Severity** | P0 |
| **Problem** | `--production` sets `OPENHAC_NO_NETWORK`, but `Resistor()` / parametric Phase 4 can still HTTP-fetch jlcsearch. |
| **Current state** | `network_allowed()` used by enrich, `Component._live_lookup` (`base.py` ~340–345), CLI enrich. **Not** used in `db_manager.py` Phase 4 (~700–727) or `api_fallback.fetch_and_map_part` (~240–268). ABC-016 marked Done for `_live_lookup` only. |
| **Target state** | `network_allowed()` at the start of `fetch_and_map_part` and parametric Phase 4. Fail closed under no-network / fabrication. |
| **Acceptance criteria** | Test: `OPENHAC_NO_NETWORK=1`, empty local row, `parametric_search` does not call HTTP (mock). `--production` cannot phone home from stdlib constructors. |
| **Approach** | One check in `fetch_and_map_part`; Phase 4 respects it. Do not fail-open if `enrich` import fails. |

#### CODE-001 — `SaveBoard` / `DEFER_COPPER_POURS` process poison

| Field | Content |
|-------|---------|
| **Severity** | P0 |
| **Problem** | `pcbnew.SaveBoard` can SIGSEGV (`except Exception` does not catch it). Pipeline sets `OPENHAC_DEFER_COPPER_POURS=1` and never restores it, so later pytest cases in-process see a different pour schedule. |
| **Current state** | Env save/restore in `run_compile_phases` `finally`. SaveBoard stays in-process; comment documents SIGSEGV. Zone fill remains a child process. Test: compile does not leave `OPENHAC_DEFER_COPPER_POURS` set. |
| **Target state** | Save/restore the env in `try/finally`. Prefer out-of-process SaveBoard. Isolate pcbnew tests. |
| **Acceptance criteria** | Test: compile with autoroute does not leave `DEFER_COPPER_POURS` set for the next test. Document SaveBoard isolation. |
| **Approach** | `try/finally` around layout/autoroute; subprocess pattern from zone fill. |

---

### B — Review path (P1)

#### FAB-041 — Deprecate webview as human review

| Field | Content |
|-------|---------|
| **Severity** | P1 |
| **Problem** | FAB-041 called Cytoscape HTML “primary human review.” That fights schematic sign-off and is a topology cartoon, not a sheet. |
| **Current state** | `Board.export_webview`, `openhac/webview/exporter.py`, CLI `--webview`. `tests/test_webview_export.py` writes HTML under a temp dir. USER_GUIDE / RELEASE_CHECKLIST / this file’s old FAB-041 row. |
| **Target state** | `--webview` / `export_webview` deprecated (warning, then removal). Hardware IR JSON may remain as a machine dump. Human preview is **SSO-012**. EE stamp remains **SSO-040**. |
| **Acceptance criteria** | CLI warns. Test does not write under `docs/`. SCOPE / USER_GUIDE / RELEASE_CHECKLIST / this FAB-041 row match the retarget. |
| **Approach** | Deprecation warning; docs; stop the test side-effect. Prefer delete of CDN HTML over XSS hardening if SSO-012 ships in the same batch (**CODE-005**). |

#### SSO-012 — Live KiCad sheet preview (not ERC)

| Field | Content |
|-------|---------|
| **Severity** | P1 |
| **Problem** | Authoring has no KiCad-symbol live view. The webview is the wrong picture. |
| **Current state** | `generate_schematic` + `embed_used_lib_symbols` + pinpos already exist. No watch, no `kicad-cli sch export svg`, no `openhac preview`. |
| **Target state** | `openhac preview board.py`: skip layout/autoroute/enrich-as-needed, `generate_schematic`, `kicad-cli sch export svg`, show/watch the SVG. Banner: not ERC-stamped. **Must not** call `kicad-cli sch erc`. Stamp stays `--schematic-signoff` (**SSO-040**). Reuse `emit_kicad` / `kicad_sym_pinpos`; no second symbol renderer. |
| **Acceptance criteria** | CLI smoke: preview writes SVG (or skips with a clear “kicad-cli missing” error). Preview path does not invoke sch erc. Sign-off tests still require ERC. |
| **Approach** | Compile profile **PERF-006** `preview` + `kicad-cli sch export svg`. File-watch re-exec with `reset_default_circuit()`. |

#### SSO-041 — Golden is `sso041_signoff_node.py`

| Field | Content |
|-------|---------|
| **Severity** | P1 |
| **Problem** | Spec target is a multi-module Device R/C/LED node. CI still compiles `complex_rs485_node.py` under `--schematic-signoff`. |
| **Current state** | `SCHEMATIC_SIGN_OFF_SPEC.md` SSO-041 vs `scripts/ci_kicad_sch_erc_golden.py` ~146–177. Status table marked Done. |
| **Target state** | `kicad-schematic-erc` compiles `examples/sso041_signoff_node.py`. Two-resistor smoke remains. RS-485 / ESP32-C3 stay fabrication goldens until MCU/connector ERC is an explicit contract. |
| **Acceptance criteria** | Script path assertion; job uses that example. |
| **Approach** | Change the golden script; keep RS-485 on the fab matrix only. |

---

### C — Claim / overfitting honesty (P1)

#### FAB-051 — Honest production-validation class

| Field | Content |
|-------|---------|
| **Severity** | P1 |
| **Problem** | `--require-all` is proved only on two 0805 resistors (`tests/fixtures/fab_golden_board.py`). README still says “supported golden board class.” |
| **Current state** | `scripts/ci_validate_production.py` `_GOLDEN` line 31. |
| **Target state** | Either the claim says **minimal 2-pin passive class**, or the validator adds a multi-IC board to `--require-all`. |
| **Acceptance criteria** | README + PRODUCTION_VALIDATION.md + this row agree. No silent expansion of the claim. |
| **Approach** | Docs first unless a second golden is explicitly added. |

#### ABC-008 — Route subset is not the complex-board claim

| Field | Content |
|-------|---------|
| **Severity** | P1 |
| **Problem** | `--route` defaults to `esp32c3_usb` and `rs485_node`. WROOM / mesh / AMR stay place-only; CI job is `continue-on-error`. |
| **Current state** | `scripts/ci_validate_complex_boards.py` ~507–529. ABC-008/009 marked Done. |
| **Target state** | Docs and `--help` state the default subset. Do not imply route+DRC for RF_Module WROOM boards. |
| **Acceptance criteria** | PRODUCTION_VALIDATION.md / ABC notes / CLI help match the subset. |
| **Approach** | Documentation; optional explicit `--route-subset` required in CI YAML comments. |

#### LIB-007 — Bundled reference BOM is opt-in

| Field | Content |
|-------|---------|
| **Severity** | P1 |
| **Problem** | `00_reference_bom.json` (ICM-42688, BMP388, QMC5883L, W25Q128, LDL1117, …) merges into every `get_component()` unless `OPENHAC_NO_BUNDLED_CATALOG_OVERLAYS=1`. Demo BOMs mutate the global catalog. |
| **Current state** | `openhac/database/catalog_overlay.py`; `package_catalog_overlays/00_reference_bom.json`. |
| **Target state** | No board-BOM merge by default. Examples pass `--catalog-overlay`. Bundled overlays for *fixups* stay documented separately if any remain. |
| **Acceptance criteria** | Test: `get_component` without overlay env does not apply IMU/LDO pinouts from `00_reference_bom.json`. |
| **Approach** | Stop auto-loading that file; move it to `examples/` or require the flag. |

#### ABC-046 — RF detection without Espressif archaeology

| Field | Content |
|-------|---------|
| **Severity** | P1 |
| **Problem** | `"WROOM"` / `"ESP32"` in the footprint string triggers RF keepout/pour rules. Other RF modules slip through; named ESP32 bricks are forced in. |
| **Current state** | `openhac/compiler/advanced_board_policy.py` ~117–125. |
| **Target state** | Declared `board_class=rf` and/or `RF_Module:` library prefix only. |
| **Acceptance criteria** | Test: footprint containing `ESP32` without `RF_Module:` and without `board_class=rf` does not emit ABC-046/047. `RF_Module:` does. |
| **Approach** | Drop substring checks; keep lib-prefix + class. |

#### SCH-006 — Schematic flow columns from intent, not names

| Field | Content |
|-------|---------|
| **Severity** | P1 |
| **Problem** | `_flow_column` keys on tokens `ldo`, `rs485`, `usb`, … in module/interface names. Rename `PowerTree` → `PSU1` and the sheet shuffles. |
| **Current state** | `openhac/schematic/layout.py` ~208–228. |
| **Target state** | Explicit sheet/zone tags or interface types already on `Module`. |
| **Acceptance criteria** | Test: modules named without those tokens still group by declared tag. No token list required for a passing layout. |
| **Approach** | Prefer `sheet_field` / interface kinds; keep tokens only as a deprecated hint behind an env flag if needed. |

#### CODE-003 — Stdlib must not invent Espressif / TPS pin maps

| Field | Content |
|-------|---------|
| **Severity** | P1 |
| **Problem** | `SwitchingRegulator` hardcodes `TPS54302` / `AP3211` maps and 4.7 µH vs 10 µH. `RF_Module()` falls back to `ESP32-WROOM-32`. |
| **Current state** | `openhac/stdlib/power.py` ~440–506; `openhac/stdlib/interface.py` ~239–244. |
| **Target state** | Pinout from catalog `pinout_json` or fail. Inductor/cap values from author params or a model. `RF_Module()` raises if parametric miss. |
| **Acceptance criteria** | Tests: missing pinout does not mock 8 pins; RF miss does not resolve WROOM. |
| **Approach** | Delete `FAMILY_PIN_MAP` / WROOM fallback; fail closed. |

#### CODE-004 — Placement profile vs silent CI env

| Field | Content |
|-------|---------|
| **Severity** | P1 |
| **Problem** | Complex validator `_placement_env` setdefaults clearance 12 mm, inflate 2.2, margin 15 mm so CI stays green. ABC-007 comments cite WROOM UNSAT. Default `Board.compile()` is not those knobs. |
| **Current state** | `scripts/ci_validate_complex_boards.py` ~157–185; `compile_pipeline.py` ~1268–1277. |
| **Target state** | Named placement profile (env or `Board` field). ABC-007 repair stays generic (gap + autosize), not a WROOM contract. |
| **Acceptance criteria** | Profile documented; complex CI sets it explicitly. Repair tests do not require Espressif names. |
| **Approach** | `OPENHAC_PLACEMENT_PROFILE=complex_ci` or equivalent; validator applies it by name. |

#### SPS-045 — Analog island in CI or not in the compiler story

| Field | Content |
|-------|---------|
| **Severity** | P1 |
| **Problem** | `examples/fundi_mig_*` is untracked. `declare_spice_ground` / island work can fork from main. |
| **Current state** | Working tree only; no Fundi strings under `openhac/`. |
| **Target state** | Either a **tracked** minimal island fixture in CI (offline overlay, `--spice-signoff --spice-island`), or Fundi stays out of compiler motivation until it is tracked. |
| **Acceptance criteria** | CI job or an explicit “not in tree” note in SPS table. No half-landed APIs without a test. |
| **Approach** | Small resistor/LDO island golden preferred over shipping the full MIG board first. |

---

### D — Speed (PERF-*)

Measured 4 Sep 2026 on this tree: `openhac.db` 29 974 rows, **zero** indexes on `components`, `get_component` ≈ 10 ms (`SCAN`); index on a copy ≈ 0.01 ms. `parametric_search` `LIKE '%10k%'` ≈ 33 ms. Golden skip-layout ≈ 1 s (manifest ≈ 350 ms). Cold schematic ≈ 1.6 s (`Device.kicad_sym` 2.22 MB). FreeRouting/Z3/pcbnew dominate fab wall-clock; **do not rewrite OpenHaC** to move those.

#### PERF-001 — Catalog indexes and dedupe

| Field | Content |
|-------|---------|
| **Severity** | P1 |
| **Problem** | Live DB has `PRAGMA index_list(components) = []`. `generic_name UNIQUE` in `schema.sql` never landed via ADD COLUMN migrations. Duplicates: `MOSFET_N_SOT-23` × 2873, `C_0pF_0603` × 1218. `get_component` `ORDER BY length(pinout_json)` scans clones. |
| **Current state** | `openhac/database/schema.sql`; `db_manager.get_component` ~203–224. |
| **Target state** | `INDEX` on `generic_name`, `category`, `supplier_sku`, `mpn`. Deduplicate keeping the longest pinout. Migration is idempotent on existing files. |
| **Acceptance criteria** | `EXPLAIN QUERY PLAN` for `generic_name = ?` is `SEARCH … INDEX`. Test: lookup 100× under 50 ms on a 30k-row fixture. Duplicate count for a known clone name drops to 1 after migrate. |
| **Approach** | `_migrate_v10_indexes` (or next schema version) in `DatabaseManager._init_db`. |

#### PERF-002 — One SQLite connection

| Field | Content |
|-------|---------|
| **Severity** | P1 |
| **Problem** | Every stdlib `Resistor()` does `DatabaseManager()` (schema + nine PRAGMA migrations). Every `get_component` opens a new connection. |
| **Current state** | `stdlib/passives.py` ~53–54 and the same pattern across stdlib. `db_manager.py` `with sqlite3.connect` per method. |
| **Target state** | Process-wide (or compile-scoped) connection, WAL. Stdlib uses `Component.db` / a shared manager, not `DatabaseManager()` per ctor. |
| **Acceptance criteria** | Test: N `Resistor()` constructions do not open N connections (mock/count). WAL pragma on the shared conn. |
| **Approach** | Lazy singleton connection on `DatabaseManager`; stdlib delete local `DatabaseManager()`. |

#### PERF-003 — Parametric without leading wildcard LIKE

| Field | Content |
|-------|---------|
| **Severity** | P1 |
| **Problem** | `LIKE '%10k%'` / `'%0805%'` cannot use a btree (~33 ms/search on 30k rows). |
| **Current state** | `db_manager.parametric_search` ~593–611. |
| **Target state** | Stored normalized `value` / `package` columns (or FTS5) as the primary match. LIKE is fallback only, documented as slow. |
| **Acceptance criteria** | Indexed equality/prefix query for `value=10k` `package=0805`. Benchmark vs current LIKE in a test or script note. |
| **Approach** | Columns filled at insert/sync; search uses them first. |

#### PERF-004 — Fewer catalog round-trips in `Component.__init__`

| Field | Content |
|-------|---------|
| **Severity** | P2 |
| **Problem** | Lookup, second `get_component`, `refresh_from_db`, `list_part_alternates` twice (`base.py` ~209–299). |
| **Target state** | One `get_component`, one alternates query. |
| **Acceptance criteria** | Unit test or spy: construction of a known generic_name hits get once. |
| **Approach** | Reuse `_comp_data`; call `list_part_alternates` once. |

#### PERF-005 — Cache embedded library symbol sexp

| Field | Content |
|-------|---------|
| **Severity** | P2 |
| **Problem** | `schematic_lib_symbol_sexp` re-reads `.kicad_sym` (Device.kicad_sym 2.22 MB). Pinpos has `lru_cache(64)` keyed by mtime; sexp does not. Cold `phase_schematic` ≈ 1.6 s on the 2R golden. |
| **Current state** | `kicad_sym_pinpos.py` `schematic_lib_symbol_sexp` ~175–210 vs `_cached_pin_map` ~380–393. |
| **Target state** | Same cache key `(path, symbol, mtime_ns)` for sexp. |
| **Acceptance criteria** | Second `generate_schematic` in-process does not re-read the full Device library (mock/stat). |
| **Approach** | Mirror `_cached_pin_map`. |

#### PERF-006 — Compile profiles and lazy manifest

| Field | Content |
|-------|---------|
| **Severity** | P1 |
| **Problem** | Iterate/preview pays enrich, fat manifest (~350 ms: three `git` calls + `kicad-cli --version`), and fab-oriented phases. |
| **Current state** | `DEFAULT_COMPILE_PHASES`; `compile_manifest.py` subprocesses ~87–150. |
| **Target state** | Profiles: **preview** (schematic + SVG; skip enrich/layout/route/ERC/fat manifest) vs **logic** vs **fabrication**. Lazy manifest: skip git/kicad-cli version unless production / `--full-manifest`. |
| **Acceptance criteria** | `openhac preview` / profile flag skips those phases. Production still writes full STR-002 manifest. |
| **Approach** | Phase subsets on `CompileState`; gate git/kicad version collection. Pairs with **SSO-012**. |

#### PERF-007 — Phase timings in the manifest

| Field | Content |
|-------|---------|
| **Severity** | P2 |
| **Problem** | No recorded phase durations; “maybe rewrite” is guesswork. |
| **Current state** | `run_compile_phases` loops with no timer (`compile_pipeline.py` ~1170–1172). |
| **Target state** | `compile_pipeline_phase_ms` map in the manifest (and preview log). |
| **Acceptance criteria** | Golden compile manifest contains per-phase milliseconds for phases that ran. |
| **Approach** | `perf_counter` around each `fn(state)`. |

#### PERF-008 — Stretch: one pcbnew board in memory

| Field | Content |
|-------|---------|
| **Severity** | P2 (stretch) |
| **Current state** | `generate_layout` returns the pcbnew board; `phase_autoroute` reuses `state.pcbnew_board`. Zone fill still LoadBoard. Stretch not fully place→DSN. |
| **Target state** | Keep one `pcbnew.BOARD` through place→physics→DSN when in-process is safe. SaveBoard isolation still **CODE-001**. |
| **Acceptance criteria** | Fewer LoadBoard calls on a skip-FreeRouting place-only compile (count via hook/test). |
| **Approach** | Pass board object through phases; subprocess only at crash boundaries. |

---

### E — Hygiene (P2)

#### CODE-002 — Pytest env isolation

| Field | Content |
|-------|---------|
| **Severity** | P2 |
| **Problem** | `load_repo_dotenv()` in `conftest.py` leaks machine `.env`. Only five `OPENHAC_*` keys are deleted. |
| **Current state** | `tests/conftest.py` ~16–34. |
| **Target state** | Snapshot/restore all `OPENHAC_*`. Dotenv only for opt-in KiCad path fixtures, not unit tests. |
| **Acceptance criteria** | Test: `OPENHAC_DETERMINISTIC` / `NO_NETWORK` / `DEFER_COPPER_POURS` in the environment do not change an unmarked test. |
| **Approach** | Expand `_TEST_ISOLATE_ENV` or clear the prefix. |

#### CODE-005 — Webview XSS / CDN until deleted

| Field | Content |
|-------|---------|
| **Severity** | P2 |
| **Problem** | Inspector `innerHTML` interpolates catalog fields; HTML pulls Google Fonts / cdnjs / jsDelivr. |
| **Current state** | `openhac/webview/exporter.py` ~104–116, ~421–452. |
| **Target state** | Prefer **FAB-041** delete. If the exporter remains: `html.escape` / `textContent`, vendored JS, no test write to `docs/`. |
| **Acceptance criteria** | Either no exporter, or a test that a `</script>` in a field does not appear raw in HTML. |
| **Approach** | Delete with FAB-041, or escape in the same PR as deprecation. |

#### FAB-050 — Grow the mypy island

| Field | Content |
|-------|---------|
| **Severity** | P2 |
| **Problem** | CI mypy is `openhac/core`, `pcb_placement.py`, `layout_gen.py` with `--follow-imports=silent`. |
| **Current state** | `.github/workflows/ci.yml` ~31–32. Status table marks FAB-050 Done. |
| **Target state** | Add `openhac/schematic/ir.py`, `openhac/compiler/spice_gen.py`, then `compile_pipeline.py`. |
| **Acceptance criteria** | CI command lists those paths; they typecheck. |
| **Approach** | Incremental; do not require repo-wide mypy in this batch. |

#### CODE-006 — Invented pins visible in handoff

| Field | Content |
|-------|---------|
| **Severity** | P2 |
| **Problem** | Handoff still invents `Pin_N` (FAB-001 refuses only in fabrication). Easy to miss a log line. |
| **Current state** | `pin_resolution.py` ~119–136; `_IMPLICIT_PIN_EVENTS`. |
| **Target state** | Count in CLI summary and manifest under handoff. Fab still fails closed. |
| **Acceptance criteria** | Compile of a missing-pinout part in handoff prints/records `invented_pin_parts > 0`. |
| **Approach** | Surface `_IMPLICIT_PIN_EVENTS` on `fab_audit` / CLI. |

---

### SPICE Sign-Off (SPS-* IDs)

Normative spec: [SPICE_SIGN_OFF_SPEC.md](./SPICE_SIGN_OFF_SPEC.md). Additive fail-closed analog gate (`--spice-signoff`). Phase-1 **SIM-001…003** stay Done.

| Spec ID | Status | Notes |
|---------|--------|-------|
| **SPS-001** | Done | Ground aliases (`GND`/`VSS`/`PGND`/`EARTH` + merge hints) map to node `0` (`spice_nodes.py`). |
| **SPS-002** | Done | Sign-off refuses dropped `pin_map` terminals. |
| **SPS-003** | Done | Instance node order follows registry / `Spice_Pin_Map`, not pin-number sort. |
| **SPS-004** | Done | Leading-digit nets get `N_` prefix; sanitization collisions raise. |
| **SPS-005** | Done | In-scope analog non-primitives without vendor/physics model fail. Connectors / test points / mounting hardware / net-ties omitted. Digital cores omitted (SPS-043). |
| **SPS-006** | Done | Instance line vs expected sanitized nodes checked after emit. |
| **SPS-010** | Done | Registry JSON schema in `openhac/compiler/spice_models.py`. |
| **SPS-011** | Done | `${OPENHAC_SPICE_VENDOR_DIR}` + sha256 for `kind=vendor`. |
| **SPS-012** | Done | Stamp `Spice_Include` / `Spice_Subckt` / `Spice_Pin_Map` / `Spice_Kind` / sha256. |
| **SPS-013** | Done | Bundled `LDO_BEH` is `kind=behavioral` (generator/waiver only). |
| **SPS-014** | Done | Missing include file fails under sign-off; no HTTP fetch. |
| **SPS-015** | Done | R/C/L/V/I value lines; other prefixes need a model under sign-off. |
| **SPS-016** | Done | `physics_checks[]` runner (`spice_physics.py`); bundled LEVEL-1 NMOS bench. |
| **SPS-017** | Done | Behavioral refused unless `allow_behavioral_spice_models`. |
| **SPS-018** | Done | Parsed `.subckt` arity must match `pin_map`. |
| **SPS-020** | Done | `declare_spice_rail` / `declared_supply_voltages_v` emit `V… 0 DC`. |
| **SPS-021** | Done | Analysis `V1` / `V(out)` fail if those names were not emitted. |
| **SPS-022** | Done | `declare_spice_probe` vs parsed OP voltages. |
| **SPS-023** | Done | `.options TEMP/TNOM=27`; benches record `temp_c`. |
| **SPS-030** | Done | CLI `--spice-signoff` implies ngspice + models + benches/probes. |
| **SPS-031** | Done | ngspice missing or non-zero exit raises (`ngspice_runner`). |
| **SPS-032** | Done | `parse_ngspice_op_voltages` extracts floats. |
| **SPS-033** | Done | Generated resistor-divider golden (`tests/test_sps_spice_signoff.py`). |
| **SPS-034** | Done | `--require-vendor-models` fails without vendor dir; tmp hashed `.lib` bench; default CI uses in-repo `kind=physics`. |
| **SPS-040** | Done | `{project}.openhac-spice-signoff-audit.json` including `coverage[]`. |
| **SPS-041** | Done | SCOPE / README / RELEASE_CHECKLIST / ARCHITECTURE / this table. |
| **SPS-042** | Done | Handoff hint markdown retained; sign-off enforces pin_map/benches. |
| **SPS-043** | Done | `declare_spice_island` / `--spice-island` subgraph sign-off; MCU omit. |
| **SPS-044** | Done | Audit `coverage[]`; failed sign-off still writes JSON with `passed: false`. |

**SPS open (v1):** **0** in the table above. **Sep 2026 reopen:** **SPS-007** (SKiDL fallback, paired with FAB-004) and **SPS-045** (island CI vs Fundi) — see [Audit follow-on job spec](#audit-follow-on-job-spec-sep-2026). Stretch reserved: SPS-008…009 / 019 / 035…039.

### Schematic Sign-Off (SSO-* IDs)

Normative spec: [SCHEMATIC_SIGN_OFF_SPEC.md](./SCHEMATIC_SIGN_OFF_SPEC.md). Additive to FAB-040 (fab may still omit the drawing).

| Spec ID | Status | Notes |
|---------|--------|-------|
| **SSO-001** | Done | Graph↔sch parity includes power nets (`openhac/schematic/parity.py`). |
| **SSO-002** | Done | Instance rotation composed into pin world coords. |
| **SSO-003** | Done | Power port pin name equals net; never `power:VCC` for a different rail. |
| **SSO-004** | Done | Single emitter `openhac.schematic.emit_kicad`; Circuit API + `phase_schematic` share it. |
| **SSO-005** | Done | No part-type graphics / keyword pin-side tables (`tests/test_sso_no_hardcoded_graphics.py`). |
| **SSO-010** | Done | SymbolResolver: `kicad_symbol` → JLC/EasyEDA → KiCad path → pinout box; sign-off fails Device passives without a lib. |
| **SSO-011** | Done | Pin positions from resolved `.kicad_sym`; stub only with `OPENHAC_SCHEMATIC_STUB_ONLY`. |
| **SSO-020** | Done | `no_connect` from pin type / unconnected / NC net on flat and hierarchical sheets. |
| **SSO-021** | Done | `power:PWR_FLAG` instanced per power/GND net on the sheet. |
| **SSO-022** | Done | Fanout ≥ 3 uses labels; fanout 2 uses a wire when axis-aligned. |
| **SSO-030** | Done | Multi-sheet hierarchy; hier pin type from net pin types. |
| **SSO-031** | Done | Schematic IR then emit; title block has no “Fabrication Ready” slogan. |
| **SSO-040** | Done | `--schematic-signoff` forces schematic + `kicad-cli sch erc`. |
| **SSO-041** | Done | Shipped smoke exists. **Sep 2026 reopen:** CI still compiles `complex_rs485_node.py`; target remains `examples/sso041_signoff_node.py` — see job spec above. |
| **SSO-042** | Done | Grep gate for `_resistor_graphic` / `_detect_symbol_type`. |
| **SSO-050** | Done | SCOPE / FAB-040 / README / this table. |

**SSO open (v1 table):** **0 / 16** closed IDs. **Sep 2026 reopen:** **SSO-012** (preview SVG) and **SSO-041** (CI golden path) — see [Audit follow-on job spec](#audit-follow-on-job-spec-sep-2026). Stretch reserved: SSO-013…019 / 023…029 / 032…039.

### Phase-2 Fabrication Readiness (FAB-* IDs)

Normative spec: [FABRICATION_READINESS_SPEC.md](./FABRICATION_READINESS_SPEC.md). All Phase-2 IDs start **Open** until acceptance criteria land.

| Spec ID | Status | Notes |
|---------|--------|--------|
| **FAB-001** | Done | `pin_resolution.get_pins_from_data` refuses invented/corrupt pinouts under fabrication; `Component._get_pins_from_data` delegates. Tests in `tests/test_fab_phase2_gates.py`. |
| **FAB-002** | Done | Pad mismatches logged at warning; `assert_footprint_pin_pad_or_raise` auto-strict when `compile_goal=fabrication`. |
| **FAB-003** | Done | Omitted footprint refs recorded; fab place/zip refuse; export respects `OPENHAC_OMITTED_FOOTPRINT_REFS`. |
| **FAB-004** | Done | Native SoT via `get_default_circuit()`. **Sep 2026 reopen:** unguarded SKiDL fallback in `spice_gen` / `schematic.collect` — **SPS-007** in job spec. |
| **FAB-010** | Done | `network_allowed()` used by enrich and `_live_lookup`. **Sep 2026 reopen:** parametric JIT / `fetch_and_map_part` still HTTP — job spec FAB-010 / ABC-016. |
| **FAB-011** | Done | Fabrication auto-enables verified-parts gate; synthetic watermarks rejected in DRC. |
| **FAB-012** | Done | `api_cache.db` gitignored/untracked; default cache under `~/.cache/openhac/` (`OPENHAC_API_CACHE_PATH`). |
| **FAB-013** | Done | Enrich failures recorded on `CompileState` / manifest. **Sep 2026 reopen:** `lookup_failed` does not abort; CI does not assert `gates_passed`. |
| **FAB-020** | Done | `pcb_metrics.footprint_count` + fab_audit; place parity enforced via FAB-002/003 gates. |
| **FAB-021** | Done | `unrouted_net_count` in metrics; fab routing phase fails if unrouted > 0 unless `allow_unrouted_nets`. |
| **FAB-022** | Done | `phase_kicad_pcb_drc` already required in fabrication; report path stored for fab_audit. |
| **FAB-023** | Done | Incremental: fab raises on omitted footprints / pad / enrich import. **Sep 2026 reopen:** physics net-class apply still swallowed under fabrication. |
| **FAB-030** | Done | `--production` sets fab goal, pad strict, verified parts, `OPENHAC_NO_NETWORK`, schematic off by default. |
| **FAB-031** | Done | `scripts/ci_fab_golden.py` + `kicad-fab-golden` CI job runs `export fab --zip` when `kicad-cli` present. |
| **FAB-032** | Done | Manifest `fab_audit` / `openhac.fab_audit.v1`. |
| **FAB-040** | Done | `--production` defaults schematic off; fab may omit drawing. EE stamp path is SSO (`--schematic-signoff`), not fabrication. |
| **FAB-041** | Done | CLI `--webview` shipped. **Sep 2026 retarget:** deprecate Cytoscape as review path; preview is SSO-012; IR JSON may remain. |
| **FAB-042** | Done | API stability section in `docs/API_REFERENCE.md`. |
| **FAB-050** | Done | CI `OPENHAC_NO_NETWORK=1`; mypy island on core + placement/layout. **Sep 2026 reopen:** grow mypy to schematic IR, spice_gen, compile_pipeline. |
| **FAB-051** | Done | Blocking fab golden + `--require-all` on the 2R fixture. **Sep 2026 reopen:** claim honesty — 2-pin class only, or add a multi-IC board. |


**Phase-2 historical table:** **0 / 20** unmarked. **Sep 2026 reopen** (see job spec): **FAB-004, FAB-010, FAB-013, FAB-023, FAB-041, FAB-050, FAB-051**.

### Advanced Board Capabilities (ABC-* IDs)

Normative spec: [ADVANCED_BOARD_CAPABILITIES_SPEC.md](./ADVANCED_BOARD_CAPABILITIES_SPEC.md).

| Spec ID | Status | Notes |
|---------|--------|-------|
| **ABC-001** | Done | Fab design settings (min hole/clearance/width) injected into pcbnew before FreeRouting. |
| **ABC-002** | Done | Copper pours filled via safe child-process `ZONE_FILLER`; deferred until after FreeRouting when autorouting (`OPENHAC_DEFER_COPPER_POURS`). |
| **ABC-003** | Done | Thermal-relief pad↔zone defaults; `OPENHAC_POUR_PAD_CONNECTION=solid` for fab route metrics. |
| **ABC-004** | Done | Routability env knobs (`OPENHAC_ROUTABILITY_*`) + denser pack defaults for complex CI. |
| **ABC-005** | Done | Pre-route FP min-drill audit; duplicate pad-number net sync (RF thermals); relax board min-hole to stock FP drills. |
| **ABC-006** | Done | `unrouted_net_count` hardens on connectivity API failure. |
| **ABC-007** | Done | Repair retry expands board / placement gap on route/DRC failure. |
| **ABC-008** | Done | `--route-subset` exists. **Sep 2026 reopen:** default subset is C3/RS-485 only — document that it is not the full complex-board route claim. |
| **ABC-009** | Done | WROOM thermal-via ceiling documented; route subset prefers C3/RS-485. |
| **ABC-016** | Done | `_live_lookup` gated by `network_allowed()`. **Sep 2026 reopen:** parametric JIT is not — paired with FAB-010. |
| **ABC-017** | Done | Stock KiCad FP map preferred over `Device:Q`; EasyEDA fallback. |
| **ABC-018** | Done | `voltage_rating` / `power_watts` populated from live/enrich attributes. |
| **ABC-019** | Done | `footprint_source` recorded on live/enrich rows. |
| **ABC-020** | Done | API mixed example + `--api` validator. |
| **ABC-026** | Done | BGA / ball-package detection heuristic. |
| **ABC-027** | Done | Fab fails without `allow_manual_bga_fanout`. |
| **ABC-028** | Done | `declare_fanout_intent` → manifest + autoroute exclusions. |
| **ABC-029** | Done | Fanout constraints JSON artifact. |
| **ABC-030** | Done | board_profiles note for dense packages. |
| **ABC-036** | Done | `highspeed` requires stackup ref under fab. |
| **ABC-037** | Done | Diff pairs require Z0 under fab+highspeed. |
| **ABC-038** | Done | HS nets excluded from FreeRouting unless waived. |
| **ABC-039** | Done | Netclass/rules handoff file beside PCB. |
| **ABC-040** | Done | Length-match intent recording. |
| **ABC-046** | Done | `rf` profile keepout check. **Sep 2026 reopen:** detection uses `ESP32`/`WROOM` substrings; require class / `RF_Module:` prefix. |
| **ABC-047** | Done | Ground-pour intent check under `rf`. |
| **ABC-048** | Done | RF/EMC checklist in fab handoff. |
| **ABC-049** | Done | RF courtyard keepout helper. |
| **ABC-050** | Done | SCOPE honesty preserved (no EMC performance claim). |

**ABC open (stretch placeholders ABC-010…015, 021…025, 031…035, 041…045):** tracked as Open in the normative spec; not blocking Phase-1–4 policy Done. **Sep 2026 reopen:** **ABC-008**, **ABC-016**, **ABC-046** — see [Audit follow-on job spec](#audit-follow-on-job-spec-sep-2026).

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
| **SCH-002** | Done | Flat **``.kicad_sch``** by default; multi-sheet when ``OPENHAC_SCHEMATIC_MULTI_SHEET=1`` or part count ≥ ``OPENHAC_SCHEMATIC_MULTI_SHEET_MIN_PARTS`` (default 25). Hierarchical sheets + pins generated; optional ``OpenHaC_SchSheet`` decouples sheet grouping from placement ``OpenHaC_Module``. Manifest **``logical_modules``** / hierarchy handoff + **``examples/hierarchy_authoring.md``**. |
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

**Phase-1:** **Zero** open **Partial** rows for the **48** numbered spec IDs: historical table rows stay **Done**. Optional Phase-1 **stretch** work is tracked in per-ID Notes and in [PRODUCTION_READINESS_SPEC.md](./PRODUCTION_READINESS_SPEC.md).

**Phase-2 historical table:** still lists **20 / 20 Done**. The Sep 2026 reopen of **FAB-004, FAB-010, FAB-013, FAB-023, FAB-041, FAB-050, FAB-051** (and paired **SPS-007** / **ABC-016**) is **closed** in the [Audit follow-on job spec](#audit-follow-on-job-spec-sep-2026).

| Bucket | Count | Meaning |
|--------|--------|--------|
| **Done** (all 48 Phase-1 spec IDs) | **48** | Phase-1 acceptance (see production spec). Historical rows unchanged. |
| **Done (extra rows)** | **5** | Layout stub, Z3 overlap, Board DRC, interface validation, ERC net-level (supporting work, not a single spec ID). |
| **Done (Phase-2 FAB-* historical)** | **20** | Shipped slice as of the Phase-2 close. |
| **Open (Phase-2 FAB-* reopened)** | **0** | Closed in the Sep 2026 batch. |
| **Open (Sep 2026 follow-on)** | **0** | 28-row batch Done (4 Sep 2026). CODE-001 SaveBoard still in-process; PERF-008 stretch partial. |

### Stretch backlog (follow-on batches)

The [Sep 2026 job spec](#audit-follow-on-job-spec-sep-2026) is **closed**. Remaining stretch (not that batch):

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
