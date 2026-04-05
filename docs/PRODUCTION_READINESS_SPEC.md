# OpenHaC — Production Readiness Specification

**Purpose:** Capture known gaps between the current codebase and a *credible* “hardware from code” product that can support **production-grade PCBs**, aligned with what an electrical engineer must cover across design, verification, and manufacturing.

**Audience:** Core maintainers, contributors, and anyone scoping roadmap or acceptance criteria.

**Status:** Normative *target* definition — not a commitment that all items are implemented.

**Progress:** Completed or in-progress items are tracked in [IMPLEMENTATION_STATUS.md](./IMPLEMENTATION_STATUS.md).

**Scope:** Product capability tiers and non-goals: [SCOPE.md](./SCOPE.md).

**Conventions**

| Severity | Meaning |
|----------|---------|
| **P0** | Blocks honest “production” claims or causes silent wrong output |
| **P1** | Major functional gap for typical EE workflow |
| **P2** | Important for advanced designs or enterprise adoption |
| **P3** | Process, compliance, or long-tail EE concerns |

Each requirement includes: **problem**, **current state** (as of this spec), **target state**, **acceptance criteria**, and **implementation approach** (phased where useful).

---

## 0. Product scope tiers (strategic framing)

### STR-001 — Define explicit product tiers

| Field | Content |
|-------|---------|
| **Severity** | P1 |
| **Problem** | “Everything an EE would do” is not a single compiler; over-scoping leads to misleading marketing and unmaintainable promises. |
| **Current state** | README implies a full pipeline through placed/routed PCB and manufacturing; implementation is partial. |
| **Target state** | Documented **tiers** (e.g. Tier A: netlist + BOM + KiCad handoff; Tier B: placement + DRC; Tier C: fab bundle + pinned toolchain; Tier D: optional SI/PI with stackup model). Each tier has explicit **in** / **out** scope. |
| **Acceptance criteria** | Single `SCOPE.md` or README section lists each tier, required tools, and **non-goals**. Marketing and CLI `--help` align with tier. |
| **Approach** | Start with Tier A honesty; add tiers as features land. |

### STR-002 — Release engineering & repeatability

| Field | Content |
|-------|---------|
| **Severity** | P2 |
| **Problem** | Production requires reproducible builds, audit trails, and explicit human sign-off where automation cannot prove safety/EMC. |
| **Current state** | **``manifest_schema_version``** (e.g. ``1.0``); **sorted JSON keys**; optional **``release_tag``** / **``build_profile``** (``Board`` attrs or **``OPENHAC_RELEASE_TAG``** / **``OPENHAC_BUILD_PROFILE``**); optional **``net_roles``** / **``length_match_groups``**; **``compile(..., output_dir=...)``** / **``openhac compile -o``**; **``output_directory``** when set. |
| **Target state** | Optional **human approval**; CI golden deterministic hashes; pinned **``dist/<project>/<version>/``** convention in tooling. |
| **Acceptance criteria** | CI produces deterministic artifact list; manifest is machine-readable (JSON). |
| **Approach** | Phase 1: manifest + hashes; Phase 2: signing / optional approval workflow. |

---

## 1. Component & library engineering

### LIB-001 — Multi-vendor BOM strategy

| Field | Content |
|-------|---------|
| **Severity** | P2 |
| **Problem** | Real products use multiple distributors and alternates; LCSC/JLC-only bias is a supply-chain risk. |
| **Current state** | Optional **``mouser_sku``** / **``digikey_sku``** + BOM **Mouser_SKU** / **DigiKey_SKU**; SQLite **``part_offers``** (ranked supplier rows) + BOM **``Ranked_Offers``**. |
| **Target state** | Full **offers** table with ranked alternates (see **LIB-002**). |
| **Acceptance criteria** | Schema + API can store ≥2 offers per `generic_name`; BOM export can select primary vs alternate columns. |
| **Approach** | Extend `components` or add `part_offers(part_id, supplier, sku, …)`; migration script. |

### LIB-002 — Approved alternates & equivalence

| Field | Content |
|-------|---------|
| **Severity** | P2 |
| **Problem** | Production BOMs need ranked alternates and equivalence (not ad-hoc duplicate rows). |
| **Current state** | SQLite **``part_alternates``** (ranked rows per **``primary_generic``**); **``DatabaseManager.list_part_alternates``** / **``insert_part_alternate``**; BOM **``Alternate_SKUs``** lists alternates. |
| **Target state** | `alternate_group_id` + rank + **equivalence notes** (pin-compatible, verified). |
| **Acceptance criteria** | BOM CSV can expand or collapse alternates per CM template. |
| **Approach** | New table `part_alternates`; UI/API later. |

### LIB-003 — Safe live lookup mapping

| Field | Content |
|-------|---------|
| **Severity** | P0 |
| **Problem** | JIT API fallback can assign **wrong** symbol/footprint; silent cache insert failures desync DB. |
| **Current state** | **Discrete confidence** (high/medium/low) on JIT paths; **low** rejected unless `--allow-risky-parts` / env / `allow_risky_part_lookups`; **medium** also rejected when **``Board(strict_jit_lookups=True)``**, **``OPENHAC_STRICT_JIT``**, or **``openhac compile --strict-jit``**; live match uses **category metadata** (when present) plus **word-boundary** description tokens to reduce false positives; `_live_lookup` cache errors raise ``PartDatabaseWriteError``; internal fields stripped before INSERT. |
| **Target state** | Numeric confidence + unified `Board(strict=True)`; optional `--allow-risky-parts` tiers. |
| **Acceptance criteria** | Tests assert low-confidence lookup raises or requires flag; DB errors are not swallowed in default mode. |
| **Approach** | Refactor `_live_lookup` / `api_fallback` to return structured result; strict mode in `Board.compile()`. |

### LIB-004 — Synthetic parts when KiCad libs missing

| Field | Content |
|-------|---------|
| **Severity** | P1 |
| **Problem** | 99-pin synthetic parts hide real pinout errors until late stages. |
| **Current state** | Synthetic parts set **``OpenHaC_WATERMARK=SYNTHETIC_KICAD_SYMBOL``**; **`openhac compile --strict-kicad`** / env **``OPENHAC_STRICT_KICAD``**; **`openhac compile --production`** enables strict KiCad + strict JIT for the compile. |
| **Target state** | Explicit **dev / prod** profiles and BOM-visible watermarks in non-strict mode. |
| **Acceptance criteria** | Environment flag or ``Board(strict_kicad=True)`` / CLI enforces hard failure (met for opt-in strict). |
| **Approach** | `strict` flag plumbed from CLI and `compile()`. |

### LIB-005 — Assembly class & cost hints

| Field | Content |
|-------|---------|
| **Severity** | P3 |
| **Problem** | JLC basic vs extended vs hand-solder drives cost and DFM. |
| **Current state** | DB `jlc_class` → **`JLC_Class`** + BOM column; optional **`Board.max_jlc_extended_parts`** → **`run_drc`** fails if Extended-class line items exceed the limit. |
| **Target state** | Richer **warn**-only policies or per-class budgets. |
| **Acceptance criteria** | ERC/DRC optional rule for “max extended parts” or similar. |
| **Approach** | Rule plugin reading `jlc_class`. |

### LIB-006 — Unified parametric + electrical model

| Field | Content |
|-------|---------|
| **Severity** | P2 |
| **Problem** | “Right” 10k resistor needs tolerance, tempco, V, P, derating in one model. |
| **Current state** | Partial fields in DB; **``Board(strict_passive_catalog_fields=True)``** → DRC requires non-empty DB **``tolerance``** for resistor-class parts. |
| **Target state** | **Part schema** with required fields per category; validation on `Component()` or module wrapper. |
| **Acceptance criteria** | Cannot emit BOM for passives missing critical attrs when strict mode on. |
| **Approach** | Pydantic/dataclass validators per category. |

---

## 2. Schematic & connectivity

### SCH-001 — Correct schematic connectivity

| Field | Content |
|-------|---------|
| **Severity** | P0 |
| **Problem** | Generated `.kicad_sch` may not match SKiDL connectivity (grid wiring / pin index bugs). |
| **Current state** | As before + **``kicad_sym_pinpos``**: wire/label endpoints use **``.kicad_sym``** pin **``(at x y)``** when the library is found (**``OPENHAC_KICAD_SYMBOL_DIRS``**, **``KICAD*_SYMBOL_DIR``**, or **``/usr/share/kicad/symbols``**); **``EmptySymbolPinResolver``** / tests can force legacy index-based stubs. **``lib_id``** emission uses **``part_library_name``** (SKiDL **``SchLib.filename``**). Pin ordering on nets uses **alphanumeric natural sort** for non-numeric designators (e.g. BGA-style **A2** vs **A10**). Instance rotation beyond **0°** not composed yet. |
| **Target state** | Wires at **symbol pin positions** from lib definitions; KiCad ERC clean on golden designs. |
| **Acceptance criteria** | Golden-file tests: SKiDL net graph **isomorphic** to exported schematic net graph (parsed or round-tripped). |
| **Approach** | Rewrite wire emission using **pin identity** from SKiDL; add regression tests. |

### SCH-002 — Hierarchical schematics in KiCad

| Field | Content |
|-------|---------|
| **Severity** | P2 |
| **Problem** | EEs use hierarchical sheets; Python `Module` ≠ KiCad hierarchy. |
| **Current state** | Flat symbol grid; **[SCOPE.md](./SCOPE.md)** documents **no** generated hierarchical **``.kicad_sch``**; compile manifest **``logical_modules``** lists top-level **``Module``** names and contained part references for external sheet authoring. |
| **Target state** | Optional export: **one sheet per Module** with hierarchical pins. |
| **Acceptance criteria** | Example design produces multi-sheet `.kicad_sch` that KiCad loads. |
| **Approach** | Phase 1: design file format mapping; Phase 2: generator. |

### SCH-003 — ERC parity with KiCad

| Field | Content |
|-------|---------|
| **Severity** | P1 |
| **Problem** | Custom ERC cannot replace KiCad ERC rules (pin types, power, conflicts). |
| **Current state** | OpenHaC ERC in ``rule_check`` (pre-check); ``kicad-cli sch erc`` when ``kicad_sch_erc`` / ``--kicad-erc``; optional **JSON** report; **`summarize_kicad_erc_report`**; **`run_kicad_schematic_erc(..., strict=False)`** to write JSON without treating CLI exit as fatal. GitHub Actions job **`kicad-schematic-erc`** runs **`scripts/ci_kicad_sch_erc_golden.py`** (compile → schematic → ERC, assert zero errors). **`scripts/kicad_erc_optional.sh`**. |
| **Target state** | CI job on golden project; parse JSON report for assertions. |
| **Acceptance criteria** | CI or doc script runs KiCad ERC on golden project. |
| **Approach** | Wrapper subprocess + parse exit code. |

### SCH-004 — Power net detection

| Field | Content |
|-------|---------|
| **Severity** | P2 |
| **Problem** | Prefix-based `_POWER_NET_PREFIXES` is fragile. |
| **Current state** | **`Board.declare_power_rail(name, net)`** registers nets for PWR_FLAG ERC alongside prefix heuristics; **`Board(power_net_prefixes=(...))`** extends default prefixes; single load + missing flag is not mis-reported as a floating net. |
| **Target state** | **Net classes** or richer `PowerNet` metadata (beyond registration). |
| **Acceptance criteria** | User can declare `declare_power_rail("3V3", net)` without name hacks. |
| **Approach** | Extend `Board` / `Net` metadata. |

### SCH-005 — Interface validation depth

| Field | Content |
|-------|---------|
| **Severity** | P2 |
| **Problem** | `>= 2 pins per net` is necessary but insufficient (wrong domain, missing pulls). |
| **Current state** | **`Board.register_erc_hook`** during **`run_erc`**; **`openhac.stdlib.erc_rules`** includes I2C / 1-Wire / UART RX / SPI CS / reset / MDIO pull-up examples + **`missing_footprint_erc_hook`**. |
| **Target state** | **Built-in** rule packs (digital vs analog, max fanout, …). |
| **Acceptance criteria** | At least one plugin example (e.g. “I2C must have pull-ups”). |
| **Approach** | Hook after net-level ERC; extend `stdlib/erc_rules.py` with more examples. |

---

## 3. Signal integrity, power integrity, EMC

### SIG-001 — Signal integrity (pre/post layout)

| Field | Content |
|-------|---------|
| **Severity** | P3 |
| **Problem** | High-speed designs need impedance, reflection, eye analysis. |
| **Current state** | Example **``docs/stackup_template.yaml``** for handoff; no in-tool solver. |
| **Target state** | Tier D: export to external SI tools **or** integrate basic calculator + stackup. |
| **Acceptance criteria** | Documented handoff (e.g. HyperLynx, KiCad field solver) + **stackup file** export. |
| **Approach** | Start with **documentation + stackup YAML**; tool integration later. |

### SIG-002 — Differential pairs — declared vs enforced

| Field | Content |
|-------|---------|
| **Severity** | P0 |
| **Problem** | `route_differential_pair()` is stored on `Board` but **not** consumed by placer/router; impedance target is **non-functional**. |
| **Current state** | Constraint recorded only; **`run_drc`** emits a **warning** when any `diff_pair` constraint exists; **README** / **SCOPE** state that geometry is **not** driven by OpenHaC. |
| **Target state** | Pass targets to **DSN**/**router rules** / KiCad **netclass** + **width/spacing**, or remove API until implemented. |
| **Acceptance criteria** | Diff-pair nets have **consistent** width/gap in exported PCB or documented **failure** if unsupported. |
| **Approach** | Map to KiCad netclasses + `pcbnew` rules; or strip API and document. |

### SIG-003 — Power integrity (PDN)

| Field | Content |
|-------|---------|
| **Severity** | P3 |
| **Problem** | Decap strategy and target impedance are core to modern EE. |
| **Current state** | **[SCOPE.md](./SCOPE.md)** lists PDN/decap as non-automated in core. |
| **Target state** | Optional: **decap count** / **cap values** from module templates + PI checklist export. |
| **Acceptance criteria** | Design doc + optional validation script. |
| **Approach** | Library of PDN recipes per MCU family. |

### SIG-004 — EMC / EMI

| Field | Content |
|-------|---------|
| **Severity** | P3 |
| **Problem** | Shielding, return paths, split planes — expert-driven. |
| **Current state** | **[SCOPE.md](./SCOPE.md)** non-goals: EMC/EMI is **manual** + test lab; no automated EMC sign-off. |
| **Target state** | **Guidelines** in docs; **no** false claim of automated EMC sign-off. |
| **Acceptance criteria** | Scope doc states EMC is **manual** + test lab. |
| **Approach** | Documentation only. |

### SIG-005 — Timing / length matching

| Field | Content |
|-------|---------|
| **Severity** | P2 |
| **Problem** | DDR/QSPI need **length skew** rules. |
| **Current state** | **``Board.register_length_match_group(name, nets)``** → **``length_match_groups``** in compile manifest (documentation handoff). |
| **Target state** | Export **length match groups** to KiCad or router constraints. |
| **Acceptance criteria** | Single demo: match group on net list exported to project settings. |
| **Approach** | Research KiCad 8+ rules format; emit JSON/S-expression fragments. |

### SIG-006 — Analog / mixed-signal discipline

| Field | Content |
|-------|---------|
| **Severity** | P2 |
| **Problem** | AGND/DGND, star grounds, guard rings. |
| **Current state** | **``Board.declare_net_role(net, role)``** → **``net_roles``** in compile manifest (documentation handoff). |
| **Target state** | **Net roles** (`analog_ground`, `digital_ground`) + **merge** rules (ferrite/bead) in code. |
| **Acceptance criteria** | Example: separate nets with explicit `connect_at` point. |
| **Approach** | Extend `Interface` / net metadata. |

---

## 4. PCB physical design

### PCB-001 — Placement must reach `pcbnew`

| Field | Content |
|-------|---------|
| **Severity** | P0 |
| **Problem** | Z3 sets `placed_x/y` but `generate_layout` **shadows** `Board` with `pcbnew.BOARD()` and never places footprints. |
| **Current state** | Footprints are loaded from `*.pretty` via SEXP I/O, positioned from module anchors + local grid, refs/values set; outline still edge-segments only. |
| **Target state** | Fine-grained pad positions from solver, footprint rotation, and verified netlist ↔ PCB parity with KiCad’s schematic update flow. |
| **Acceptance criteria** | Golden PCB has **N** footprints for **N** parts; positions match solver within tolerance. |
| **Approach** | New module `pcb_placement.py`: iterate `default_circuit.parts`, `pcbnew.Footprint.Load`, `SetPosition`. |

### PCB-002 — Netlist → PCB bridge

| Field | Content |
|-------|---------|
| **Severity** | P0 |
| **Problem** | No authoritative bridge from SKiDL nets to `pcbnew` pads for routing. |
| **Current state** | **``place_circuit_on_board``** + **``pin_pad_coverage_warnings``** as before; **``Board(strict_footprint_pin_pad_match=True)``** makes **``generate_layout``** fail fast on pad-name mismatches (**``LayoutGenerationError``**). Full ratsnest parity vs KiCad GUI still manual. |
| **Target state** | **Import netlist** or **build connectivity** in `pcbnew` after footprint place (KiCad’s netlist import or python API). |
| **Acceptance criteria** | KiCad **Ratsnest** shows correct airwires vs SKiDL. |
| **Approach** | Use KiCad’s **Update PCB from schematic** workflow if sch exists; else pad-net mapping from SKiDL. |

### PCB-003 — Layer count vs stackup

| Field | Content |
|-------|---------|
| **Severity** | P1 |
| **Problem** | `Board(layers=6)` does not define **stackup** or **plane assignment**. |
| **Current state** | **``layers > 2``** logs a stackup warning; example YAML template for humans (**SIG-001**). |
| **Target state** | **Stackup definition** drives `pcbnew` layer setup. |
| **Acceptance criteria** | 4-layer example with **GND plane** inner layer documented in generated project. |
| **Approach** | YAML stackup → `pcbnew` layer setup + preset JSON. |

### PCB-004 — Dielectric material model

| Field | Content |
|-------|---------|
| **Severity** | P2 |
| **Problem** | Impedance needs Dk/Df, thickness, copper weight. |
| **Current state** | Example vendor stackup JSON: **`docs/fab_stackup_jlc_example.json`** (human / calculator handoff). |
| **Target state** | Stackup file with **material specs**; feeds impedance calculator (SIG-001). |
| **Acceptance criteria** | Single fab’s stackup JSON checked in as example. |
| **Approach** | Vendor-specific templates (JLC, Eurocircuits). |

### PCB-005 — Geometric constraints (distance)

| Field | Content |
|-------|---------|
| **Severity** | P1 |
| **Problem** | `distance_min/max` uses **Manhattan** (`dx+dy`) on module origins, not **clearance between bounding boxes** or **centroid distance**. |
| **Current state** | `distance_min` → bbox minimum gap; `distance_max` → L1 distance between box centers (`layout_constraints.py` + `layout_gen.solve_placement`). |
| **Target state** | Optional **configurable metric** (Euclidean center, explicit Manhattan-on-origin) if users need legacy behavior. |
| **Acceptance criteria** | Unit tests: two squares 10×10 mm; `min_distance=10` means **gap** or **center** as documented. |
| **Approach** | Non-overlap + **separation** constraint on **axis-aligned bounding boxes**. |

### PCB-006 — DRC: enforce IPC trace width vs current

| Field | Content |
|-------|---------|
| **Severity** | P1 |
| **Problem** | `calculate_ipc2152_trace_width` is **logged** but not a **failure** when fab minimum is exceeded. |
| **Current state** | `run_drc` logs only. |
| **Target state** | **Violation** if required width > **design rule** max **or** if user trace class too small; or **force** netclass min width in export. |
| **Acceptance criteria** | Test: high current module **fails DRC** in strict mode. |
| **Approach** | Compare required width to **board.default_rules**; raise `DRCViolationError`. |

### PCB-007 — Autorouter vs production quality

| Field | Content |
|-------|---------|
| **Severity** | P1 |
| **Problem** | FreeRouting is not SI-aware; **not** sufficient alone for USB HS etc. |
| **Current state** | **README** + **SCOPE**: FreeRouting is **routing assistance**, not HS/RF guaranteed; cross-ref **SIG-002**. |
| **Target state** | **Optional** skip autoroute for HS nets; netclass-based **do not route** flags. |
| **Acceptance criteria** | README tier table: Tier B = “routing assistance”, not “HS guaranteed”. |
| **Approach** | Docs + netclass-based **do not route** flags. |

### PCB-008 — Fanout / escape (BGAs, fine pitch)

| Field | Content |
|-------|---------|
| **Severity** | P2 |
| **Problem** | Dense packages need fanout strategy. |
| **Current state** | **[SCOPE.md](./SCOPE.md)** documents manual / external fanout path. |
| **Target state** | **Footprint-aware** fanout templates or **export** to external tool. |
| **Acceptance criteria** | At least **documentation** + issue tracker label for future automation. |
| **Approach** | Defer automation; document manual path. |

### PCB-009 — Planes, pours, thermal relief

| Field | Content |
|-------|---------|
| **Severity** | P2 |
| **Problem** | Real boards need **copper pours** and **via stitching**. |
| **Current state** | Outline only. |
| **Target state** | **API** for “GND pour on layer 1” + KiCad zone creation via `pcbnew`. |
| **Acceptance criteria** | Example board with **one** GND zone. |
| **Approach** | `pcbnew.ZONE` API wrapper. |

### PCB-010 — Mechanical / enclosure

| Field | Content |
|-------|---------|
| **Severity** | P2 |
| **Problem** | Mounting holes, keepouts, connector at enclosure opening. |
| **Current state** | `constrain_edge` only. |
| **Target state** | **Keepout regions**, **mounting hole** parts, **edge connector** constraints. |
| **Acceptance criteria** | Example: `board.add_mounting_hole(mmx, mmy, dia)`. |
| **Approach** | NPTH pads + mechanical layer shapes. |

---

## 5. Simulation

### SIM-001 — SPICE with real models

| Field | Content |
|-------|---------|
| **Severity** | P1 |
| **Problem** | `spice_gen` emits generic lines; **no** vendor `.lib` / subckts. |
| **Current state** | DB **``spice_include``** → **``.include``** in **``generate_spice``**; device lines unchanged. |
| **Target state** | **subckt** refs per part, **mapping table** from MPN to model file. |
| **Acceptance criteria** | One **LDO** or **MOSFET** sim with vendor model from `models/` dir. |
| **Approach** | Extend DB: `spice_model_path`; generator emits includes. |

### SIM-002 — Analysis types beyond `.tran`

| Field | Content |
|-------|---------|
| **Severity** | P2 |
| **Problem** | AC, noise, corners are standard EE workflow. |
| **Current state** | **``analysis_lines``** on **``generate_spice``** / **``Board.simulate``**; CLI **``--spice-line``** (repeatable). |
| **Target state** | **`simulation` block** in code or YAML: `analysis: [tran, ac, …]`. |
| **Acceptance criteria** | User can select AC sweep without editing generator. |
| **Approach** | Template-based `spice_gen` from config object. |

### SIM-003 — Digital verification

| Field | Content |
|-------|---------|
| **Severity** | P3 |
| **Problem** | Digital boards need timing, CDC, formal methods — **outside** SPICE. |
| **Current state** | **[SCOPE.md](./SCOPE.md)** lists **digital verification** (timing, CDC, formal) as a **non-goal** for core. |
| **Target state** | **Out of scope** for OpenHaC core **or** integration stub (export to Yosys/SymbiYosys — future). |
| **Acceptance criteria** | Scope doc explicitly lists digital verification as **non-goal** unless Tier X. |
| **Approach** | Documentation only. |

---

## 6. Manufacturing outputs

### MFG-001 — Gerber, drill, optional IPC-2581

| Field | Content |
|-------|---------|
| **Severity** | P0 |
| **Problem** | Production needs **fab outputs**; not generated in-repo today. |
| **Current state** | **`openhac export fab`** wraps `kicad-cli` **gerbers**, **drill** (Excellon), **pos** (CSV). Optional **`--ipc2581`**. Optional **`--zip` / `--zip-file`** archives the output directory. CI golden zip still future. |
| **Target state** | **IPC-2581** export flag; CI golden artifact zip for a reference project. |
| **Acceptance criteria** | CI artifact contains `.zip` of Gerbers for golden project. |
| **Approach** | Extend `export_fab.py`; add `--format ipc2581` when needed. |

### MFG-002 — Pick-and-place / centroid

| Field | Content |
|-------|---------|
| **Severity** | P1 |
| **Problem** | Assembly needs **pos file** + **polarity**. |
| **Current state** | **`openhac export assembly <pcb> -o <dir>`** / `export_assembly_csv` — KiCad **pos** CSV (mm, front/back) via `kicad-cli`. |
| **Target state** | Optional non-KiCad centroid script; IPC-7351 naming polish if CM-specific. |
| **Acceptance criteria** | CM can ingest file without manual KiCad clicks. |
| **Approach** | Same as fab: wrap `kicad-cli pcb export pos`; document in README/CLI. |

### MFG-003 — Fab drawing / documentation

| Field | Content |
|-------|---------|
| **Severity** | P3 |
| **Problem** | Dimensions, tolerances, layer stack table on **drawing**. |
| **Current state** | **``examples/fab_stackup_table.md``** — human-editable stackup table for fab docs; link to **``docs/fab_stackup_jlc_example.json``**. PDF from KiCad plot still manual. |
| **Target state** | **Generate PDF** from template or export KiCad **plot** + **stackup table** page. |
| **Acceptance criteria** | One example PDF in `examples/` with stackup table. |
| **Approach** | Latex/PDF template or KiCad plot. |

### MFG-004 — DFM / DFA integration

| Field | Content |
|-------|---------|
| **Severity** | P2 |
| **Problem** | Fab-specific DFM (annular ring, mask sliver) — **not** generic constants only. |
| **Current state** | **``openhac/fab_profiles/*.json``** + **``Board(fab_profile=...)``** merge into IPC width DRC baseline. |
| **Target state** | More profiles + **optional** external DFM tool hook. |
| **Acceptance criteria** | Switching fab profile changes min clearance/trace in one place. |
| **Approach** | `fab_profiles/jlc.json` + merge into DRC. |

### MFG-005 — Revision-controlled release bundles

| Field | Content |
|-------|---------|
| **Severity** | P2 |
| **Problem** | Production needs **immutable** release packages. |
| **Current state** | **``output_dir``** / **``-o``**; manifest **``output_directory``**; **``openhac compile --zip-release``** / **``Board.compile(..., release_zip_path=...)``** zips known artifacts (``release_bundle.zip_project_outputs``). |
| **Target state** | First-class **version** segment in default layout + signing / immutable artifact policy in CI. |
| **Acceptance criteria** | Same inputs → same hashes in CI. |
| **Approach** | Output directory layout + manifest. |

---

## 7. Power architecture

### PWR-001 — Rail-aware power budget

| Field | Content |
|-------|---------|
| **Severity** | P0 |
| **Problem** | `source_current_max_ma` / `max_current_draw_ma` as **dict** (e.g. `flight_controller.py`) is **skipped** by ERC (`isinstance` check); **multi-rail intent is silently ignored**. |
| **Current state** | **Per-rail** ERC in `rule_check._run_power_budget`: dict supply vs dict draw by key; scalar draw rejected when dict supply exists; nested scalar `source_current_max_ma` ignored under a dict-supply subtree. |
| **Target state** | Richer modeling (efficiency, cascaded input current — see **PWR-002**). |
| **Acceptance criteria** | Example `flight_controller` either **passes** meaningful rail ERC or **fails fast** with clear error until implemented. |
| **Approach** | Model `Rail` objects; `Module` registers draw/supply per rail ID; graph validation. |

### PWR-002 — Cascaded converters & efficiency

| Field | Content |
|-------|---------|
| **Severity** | P2 |
| **Problem** | 3V3 drawn from 5V buck must account for **efficiency** and **input current**, not one global mA sum. |
| **Current state** | **``Module.extra_input_draw_by_rail_ma``** merged into per-rail draw during power budget DRC (converter / loss hook). |
| **Target state** | Optional **efficiency** on regulators; **tree** walk from load to source. |
| **Acceptance criteria** | Unit test: buck 5V→3V3 with η reports **input** current on 12V rail. |
| **Approach** | Extend `VoltageRegulator` with `efficiency` and `parent_rail` links. |

---

## 8. Reliability, safety, testability

### REL-001 — Derating rules

| Field | Content |
|-------|---------|
| **Severity** | P2 |
| **Problem** | Caps/resistors need voltage/power/temp derating. |
| **Current state** | Opt-in **``Board(require_passive_voltage_ratings=True)``** → DRC requires DB **``voltage_rating``** for capacitors; optional **``require_cap_voltage_derating_ratio``** + **``declared_supply_voltages_v``** enforces rating ≥ ratio×nominal on matching nets. |
| **Target state** | **Policy** module: e.g. cap V rating ≥ 2× rail; warn in ERC. |
| **Acceptance criteria** | One rule implemented + test. |
| **Approach** | Category-specific rules in `rule_check` plugins. |

### REL-002 — Clearance / creepage (mains/isolation)

| Field | Content |
|-------|---------|
| **Severity** | P3 |
| **Problem** | IEC spacing for AC/mains. |
| **Current state** | **[SCOPE.md](./SCOPE.md)** disclaims certified mains / creepage tooling. |
| **Target state** | **Disclaimer** + optional **clearance** rules when `mains` net class present. |
| **Acceptance criteria** | Scope doc: **no** certified mains tool without expert review. |
| **Approach** | Docs + future rule pack. |

### REL-003 — Testability (ICT, test points, JTAG)

| Field | Content |
|-------|---------|
| **Severity** | P2 |
| **Problem** | Production test needs **access**. |
| **Current state** | Seeded **``TP_Mech_1mm``** + **``openhac.stdlib.test_points.MechTestPoint1mm``**; optional **``Board(min_test_points=N)``** → DRC counts heuristic test points (``TP_`` generic, DB **``testability``**, ``TestPoint`` footprint, ref **``TP…``**). |
| **Target state** | **DRC** by net class / per-module budgets; JTAG / boundary-scan hooks. |
| **Acceptance criteria** | Example adds 3 test points; appears in BOM. |
| **Approach** | Standard footprint + ERC rule. |

---

## 9. Software quality & developer experience

### SW-001 — Continuous integration

| Field | Content |
|-------|---------|
| **Severity** | P1 |
| **Problem** | No automated test/lint on push. |
| **Current state** | No `.github/workflows` in repo. |
| **Target state** | CI: **ruff**, **pytest**, **mypy** (optional strict), matrix Python 3.11–3.13. |
| **Acceptance criteria** | PRs blocked on red CI. |
| **Approach** | Add `ci.yml`; cache deps. |

### SW-002 — CLI wired to real compile

| Field | Content |
|-------|---------|
| **Severity** | P0 |
| **Problem** | `openhac compile` only **execs** script; **`--name`**, **`--no-route`**, **`--no-schematic`** ignored; no `board.compile()` invocation. |
| **Current state** | As implemented in `cli.py`. |
| **Target state** | **Convention**: script defines `board` or calls `main()`; CLI finds `Board` instance **or** explicit `compile()` entrypoint; passes **all** flags to `compile()`. |
| **Acceptance criteria** | Integration test: temp script + CLI produces expected files with flags. |
| **Approach** | `inspect` module or `runpy` + convention document. |

### SW-003 — Failure semantics (fail closed)

| Field | Content |
|-------|---------|
| **Severity** | P0 |
| **Problem** | Netlist errors **logged**; ImportError paths **warn**; ERC **returns early** silently on some SKiDL failures. |
| **Current state** | Partial success mistaken for success. |
| **Target state** | **`compile` aborts** on any generator error; **non-zero exit** from CLI; **no** silent ERC skip. |
| **Acceptance criteria** | Injected failure → exit code 1 + no partial artifacts (or manifest lists “failed”). |
| **Approach** | Single exception aggregator; `raise` from `netlist_gen`; remove bare `return` in ERC without explicit “skipped” reason. |

### SW-004 — Documentation accuracy

| Field | Content |
|-------|---------|
| **Severity** | P1 |
| **Problem** | README claims **fully placed and routed**; references **`build.py`** missing; version strings inconsistent (`OpenHaC/1.0` vs `2.0`). |
| **Current state** | README tier wording + env/CLI notes; **[docs/RELEASE_CHECKLIST.md](./RELEASE_CHECKLIST.md)**; **`openhac --version`**; User-Agent via `openhac.version_info`; **`scripts/example_build.py`**. |
| **Target state** | Per-release doc checklist; any remaining version strings grep-clean. |
| **Acceptance criteria** | Checklist review before each release. |
| **Approach** | Edit README; add `scripts/example_build.py` if needed. |

### SW-005 — API consistency (`default_circuit`)

| Field | Content |
|-------|---------|
| **Severity** | P1 |
| **Problem** | Mix of `builtins.default_circuit` and `from skidl import default_circuit`. |
| **Current state** | **`openhac.circuit.get_circuit()`** is a public alias of **`get_default_circuit()`**; compiler modules use the latter. |
| **Target state** | New code prefers **`get_circuit()`**; internal imports optionally unified. |
| **Acceptance criteria** | Single documented public helper; mypy-friendly. |
| **Approach** | Alias in `circuit.py`; gradual refactor of imports. |

### SW-006 — End-to-end tests

| Field | Content |
|-------|---------|
| **Severity** | P1 |
| **Problem** | Tests don’t cover **`Board.compile()`**, **pcbnew**, or **CLI**. |
| **Current state** | Integration + subprocess CLI as before; optional CI job **``kicad-layout-smoke``** (**``continue-on-error``**) runs **``scripts/ci_full_compile_smoke.py``** on Ubuntu after **``apt install kicad``** (full **``.kicad_pcb``** when ``pcbnew`` imports). Logic-only E2E uses **``OPENHAC_SKIP_LAYOUT``**. |
| **Target state** | **Integration** test with **mocked pcbnew** or **headless** KiCad in CI (optional job). |
| **Acceptance criteria** | At least one E2E: script → `.net` + `.csv` + exit 0. |
| **Approach** | Fixtures with minimal SKiDL circuit; skip KiCad job if binary missing. |

---

## 10. Implementation roadmap (suggested order)

| Phase | Focus | Requirements |
|-------|--------|--------------|
| **0 — Honesty** | Stop silent wrong behavior | SW-003, SW-004, LIB-003, PCB-001 (document gap if not fixed), STR-001 |
| **1 — Core PCB** | Placement + netlist bridge | PCB-001, PCB-002, SW-002, SW-006 |
| **2 — Power & DRC** | Trust engineering checks | PWR-001, PCB-006, PCB-005 |
| **3 — Manufacturing** | Fab handoff | MFG-001, MFG-002, MFG-005, STR-002 |
| **4 — Schematic trust** | KiCad + schematic correctness | SCH-001, SCH-003 |
| **5 — Advanced** | SI, PI, EMC docs, digital | SIG-*, SIM-*, REL-* |

---

## Appendix A — Traceability matrix

| ID | Severity |
|----|----------|
| STR-001, STR-002 | P1, P2 |
| LIB-001 to LIB-006 | P2, P2, P0, P1, P3, P2 |
| SCH-001 to SCH-005 | P0, P2, P1, P2, P2 |
| SIG-001 to SIG-006 | P3, P0, P3, P3, P2, P2 |
| PCB-001 to PCB-010 | P0, P0, P1, P2, P1, P1, P1, P2, P2, P2 |
| SIM-001 to SIM-003 | P1, P2, P3 |
| MFG-001 to MFG-005 | P0, P1, P3, P2, P2 |
| PWR-001, PWR-002 | P0, P2 |
| REL-001 to REL-003 | P2, P3, P2 |
| SW-001 to SW-006 | P1, P0, P0, P1, P1, P1 |

---

## Appendix B — Related files (audit)

| Area | Primary files |
|------|-----------------|
| Compile pipeline | `openhac/core/board.py`, `openhac/core/compile_context.py`, `openhac/compiler/compile_pipeline.py`, `openhac/compiler/*.py` |
| Software architecture notes | `docs/ARCHITECTURE.md` |
| Schematic round-trip (SCH-001) | `openhac/compiler/schematic_gen.py` (`schematic_geometry`, wire/label parsers) |
| PCB pad ↔ net (PCB-002) | `openhac/compiler/pcb_placement.py` (`pin_pad_coverage_warnings`, `kicad_mod_pad_numbers`) |
| CI layout smoke (SW-006) | `.github/workflows/ci.yml`, `scripts/ci_full_compile_smoke.py` |
| Release zip (MFG-005) | `openhac/compiler/release_bundle.py` |
| ERC report parse (SCH-003) | `openhac/compiler/kicad_erc_report.py` |
| Release checklist (SW-004) | `docs/RELEASE_CHECKLIST.md` |
| SKiDL default circuit | `openhac/circuit.py` (`get_default_circuit`, `get_circuit` — SW-005) |
| ERC/DRC | `openhac/compiler/rule_check.py` |
| Example ERC hooks | `openhac/stdlib/erc_rules.py` (SCH-005) |
| Layout | `openhac/compiler/layout_gen.py` |
| CLI | `openhac/cli.py` |
| Components | `openhac/core/base.py`, `openhac/database/*` |
| Examples | `flight_controller.py` (rail budget — see PWR-001) |
| Fab DRC hints | `openhac/fab_profiles/` (`jlc`, `generic_2layer`, `eurocircuits_4layer`, … — MFG-004) |
| Stackup example | `docs/stackup_template.yaml` (SIG-001) |

---

*End of specification.*
