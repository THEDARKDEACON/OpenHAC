# OpenHaC — Catalog depth, 3D pointers, and SPICE model operations (CAT / 3D / SPS-05x)

**Purpose:** Normative contract for **packing the component catalog by depth** (named pin table, real footprint, 3D pointer), widening vendor reach without treating SKU count as success, and **operator follow-on** for SPICE models (coverage, vendor-dir verify, more in-repo physics decks). Not a model CDN.

**Audience:** Core maintainers implementing catalog sync/enrich, 3D prefetch, and SPICE registry tooling.

**Status:** Normative. Progress tracked in [IMPLEMENTATION_STATUS.md](./IMPLEMENTATION_STATUS.md) (CAT / 3D / SPS-05x table). Product scope: [SCOPE.md](./SCOPE.md).

**Relationship:** Does **not** reopen closed FAB/PERF/SSO/LIVE rows. Does **not** reopen [SPS-010…044](./SPICE_SIGN_OFF_SPEC.md) (registry, vendor dir, sha256, analog island, `--require-vendor-models` stay as shipped). **SPS-019** (auto-download with license allow-list) stays **reserved and unused**. `--production` stays offline (**FAB-010**). Analogous to [LIVE_KICAD_SPEC.md](./LIVE_KICAD_SPEC.md) (**LIVE-***): additive IDs, not a rewrite of closed tables.

---

## Product lock

- **Packed catalog is depth, not SKU count.** A row is compile-ready only when it has a **named pin table**, a **real footprint** (not a placeholder like `Device:Q` / `Device:IC` without pads), and a **3D pointer** that exists on disk or is a documented KiCad library model. `--production` must not JIT-fetch any of those (**FAB-010**, **FAB-011**).
- **Two-terminal passives** may use a generic 2-pin table derived from package. **ICs without a named pinout** stay **unverified warehouse** (overlay / enrich). Never invent pin names from pin count.
- **`import_lcsc_csv` is warehouse**, not a success metric. A 500k-row dump without pinouts looks packed and still fails compile on ICs.
- **SPICE:** Git does **not** ship proprietary vendor `.lib`. No scrape of analog.com / ti.com as a compile feature. No decrypting encrypted LTspice. Operator path: registry JSON + `OPENHAC_SPICE_VENDOR_DIR` + sha256. Analog islands stay **SPS-043**. `--production` does **not** imply SPICE sign-off.
- **3D files stay out of git** (`.step` / `.wrl` gitignored). EasyEDA JIT already exists; fabrication must see **cache-on-disk**, not a fetch.

```
jlcsearch ──► openhac sync ──► SQLite rows (warehouse or compile_ready)
Digi-Key / Mouser / TME ──► openhac database enrich ──► named pinouts
EasyEDA ──► prefetch-3d (network) ──► ~/.kiro/openhac/ cache
overlay JSON ──► pinout / footprint / 3D / spice pointers
spice overlay + OPENHAC_SPICE_VENDOR_DIR ──► verify-vendor-dir ──► --spice-signoff
coverage report (no fetch) ──► compile / CI
```

---

## Honest claims

**Catalog.** `openhac sync` plus enrich either leaves a row **compile-ready offline** (named pins, real footprint, 3D pointer) or the coverage report marks it **warehouse**. SKU count is not a gate.

**SPICE.** `--spice-signoff` already instantiates a registered vendor or in-repo physics model, or it fails (**SPS-010…018**, **SPS-034**). This document adds coverage/verify tooling and more open physics decks. It does **not** add HTTP fetch of vendor macromodels.

**3D.** A packed catalog without a STEP/WRL pointer is still an empty board in the 3D viewer. Treat 3D as a first-class catalog field, same as pin table and footprint — populated **before** `--production`.

---

## Modes and severity

| Mode | Network | Catalog | 3D | SPICE |
|------|---------|---------|----|-------|
| **handoff** | Allowed unless `OPENHAC_NO_NETWORK` | Warehouse rows may warn | JIT enrich allowed | Generic `.cir` allowed |
| **`--production` / fabrication** | **Denied** | Offline compile-ready rows only | Cache/library on disk; no fetch | Unchanged; does **not** imply sign-off |
| **`spice_signoff`** | n/a for `.lib` | n/a | n/a | Registry + vendor dir + sha256 (existing SPS) |
| **catalog maintainer** (`sync` / `enrich` / `prefetch-3d`) | Allowed | Widen + deepen | Prefetch into cache | `verify-vendor-dir` is local-only |

| Severity | Meaning |
|----------|---------|
| **P0** | Silent wrong pins, fake completeness, or a fetch under production |
| **P1** | Reach / operator polish; optional aggregators |
| **P2** | Second assembler, licence-gated symbol shops, snapshot jobs |

Each requirement includes: **problem**, **current state**, **target state**, **acceptance criteria**, and **approach**.

---

## Completeness grades (CAT-001)

| Grade | Meaning |
|-------|---------|
| **`compile_ready`** | Named `pinout_json` (pin `name` ≠ pin `num` for every pin, except two-terminal passives where `1`/`2` is the table) + resolvable `kicad_footprint` + 3D ok (**3D-001** / **3D-002**) |
| **`warehouse`** | SKU/MPN (and maybe package/stock) without a named pin table and/or without a real footprint |

Coverage CLI and docs **must** use these grades. Do not report “N parts synced” as the success line.

---

## A. Catalog — CAT-001…015

Leverage [`openhac/database/sync_jlc.py`](../../openhac/database/sync_jlc.py) (`CATEGORY_ENDPOINTS`, nine typed routes, Basic/in-stock), [`openhac/database/enrich.py`](../../openhac/database/enrich.py), [`openhac/database/vendor_apis.py`](../../openhac/database/vendor_apis.py) (Digi-Key / Mouser / JLC / TME), overlays in [`openhac/database/package_catalog_overlays/`](../../openhac/database/package_catalog_overlays/).

### CAT-001 — Completeness grades on a row

| Field | Content |
|-------|---------|
| **Severity** | P0 |
| **Problem** | Row count and “synced from JLC” look like a packed DB. Compile still invents pins on ICs. |
| **Current state** | `components` has `pinout_json`, `kicad_footprint`, `model_3d_local` (schema v6/v9). No grade helper. `openhac sync` reports insert counts. |
| **Target state** | Helper next to `DatabaseManager.get_component` returns `compile_ready` or `warehouse` per **Completeness grades**. Coverage CLI (**CAT-006**) and docs use those words. |
| **Acceptance criteria** | Unit test: two-terminal 0603 with 2-pin table + real FP + library 3D → `compile_ready`. MCU row with SKU only → `warehouse`. Numeric-only MCU pinout → `warehouse`. |
| **Approach** | `catalog_grade(row) -> str` in `db_manager.py` (or a small `catalog_coverage.py`). Do not fetch. |

### CAT-002 — Widen jlcsearch typed categories

| Field | Content |
|-------|---------|
| **Severity** | P0 |
| **Problem** | Sync covers nine categories (`resistors`, `capacitors`, `leds`, `mosfets`, `microcontrollers`, `voltage_regulators`, `diodes`, `switches`, `accelerometers`). Crystals, inductors, connectors, and most passives used on real boards are missing as Basic in-stock rows. |
| **Current state** | [`CATEGORY_ENDPOINTS`](../../openhac/database/sync_jlc.py) hard-codes typed `/{cat}/list.json?in_stock=true` (passives also `is_basic=true`). Comment says only those endpoints are confirmed. |
| **Target state** | Probe typed `https://jlcsearch.tscircuit.com/{cat}/list.json` **before** adding a category. First adds if HTTP 200 and a non-empty list: **inductors**, **crystals**, **connectors**, **fuses** or **beads**, **BJTs**. Skip categories with no typed schema. Default still `in_stock=true`; keep `is_basic=true` on passives unless **CAT-003**. Map new cats in `KICAD_SYMBOL_MAP`, `_package_to_footprint`, `_derive_generic_name`. |
| **Acceptance criteria** | Test: mocked 200 for `/inductors/list.json` inserts inductor rows; mocked 404 is skipped with a warning, not a crash. Default `openhac sync` includes the new cats when the live (or fixture) probe succeeds. Pin policy **CAT-004** applies. |
| **Approach** | Extend `CATEGORY_ENDPOINTS`; probe helper; do not scrape HTML. |

### CAT-003 — Optional Extended parts (not default)

| Field | Content |
|-------|---------|
| **Severity** | P1 |
| **Problem** | Basic-only miss many ICs. Dumping all Extended without a cap recreates the 500k-CSV lie. |
| **Current state** | Passives hard-code `is_basic=true`. No `--include-extended`. |
| **Target state** | `openhac sync --include-extended` drops `is_basic=true`, with `--max-per-category N` (required or default cap). Default remains Basic. |
| **Acceptance criteria** | Default sync URLs still contain `is_basic=true` for passives. Flag omits that query param. Cap truncates inserts. |
| **Approach** | CLI on `cmd_sync`; pass flags into `sync_catalog`. |

### CAT-004 — Pin policy: two-terminal vs IC

| Field | Content |
|-------|---------|
| **Severity** | P0 |
| **Problem** | Numeric-only pinouts (`name == num`) look like pin tables and still wire the wrong pad. Sync of MCUs/regulators can write that. |
| **Current state** | `sync_jlc.py` (~983) **warns** on numeric-only pinouts from vendor enrich. Bulk `sync_catalog` often writes **no** `pinout_json` at all. Placeholder symbols (`MCU_Module:Generic_MCU`, `Regulator_Linear:AMS1117-5.0`) are used for whole categories. |
| **Target state** | **Two-terminal** R/C/L/LED/diode: write a 2-pin table from package (`1`/`2` or A/K for diodes). **MOSFET** category: D/G/S only when the category is FET. **MCU / regulator / IC / connector (multi-pin):** **must not** write numeric-only pinouts. Leave `pinout_json` empty → `warehouse` until overlay or enrich. |
| **Acceptance criteria** | Test: resistor sync fixture has 2-pin table. MCU sync fixture has empty `pinout_json`. Vendor enrich that returns numeric-only pins for an IC is a **hard skip** (not stored). |
| **Approach** | Classifier by category + pin-count; reuse the numeric-only check; skip `update_component_from_vendor` pinout write for ICs. |

### CAT-005 — Post-sync enrich for missing named pinouts

| Field | Content |
|-------|---------|
| **Severity** | P0 |
| **Problem** | `openhac database enrich` requires `--skus-file`. Sync does not walk the DB for holes. |
| **Current state** | Enrich entrypoint exists; Digi-Key is the usual named-pin source; Mouser often empty. |
| **Target state** | `openhac database enrich --missing-pinouts` (or `--from-db`) walks rows lacking a named pinout and uses existing vendor APIs. Honors `network_allowed()`. **Never** invoked from `--production` / fabrication compile. |
| **Acceptance criteria** | Test: DB with warehouse MCU + mocked Digi-Key named pins → row becomes named (or stays warehouse if APIs empty). `OPENHAC_NO_NETWORK=1` does not HTTP. Compile `--production` does not call this walker. |
| **Approach** | Query `pinout_json` IS NULL / numeric-only; reuse enrich; rate-limit. |

### CAT-006 — Coverage report CLI (no fetch)

| Field | Content |
|-------|---------|
| **Severity** | P0 |
| **Problem** | No single number for “how much of this DB can actually compile.” |
| **Current state** | Manifest `fab_audit` lists enrich failures per board. No catalog-wide coverage. `collect_spice_coverage` is board-only under sign-off. |
| **Target state** | `openhac catalog coverage` prints counts: `compile_ready` / `warehouse` / named pinout / resolvable footprint / 3D on disk or `kicad_lib` / spice registry hit. JSON (`openhac.catalog_coverage.v1`) for CI. **Does not fetch.** |
| **Acceptance criteria** | Fixture DB: counts match helper. Running the command with `OPENHAC_NO_NETWORK=1` does not open a socket. |
| **Approach** | CLI subparser; reuse **CAT-001** / **3D-001** / `lookup_registry`. |

### CAT-007 — CSV dump is warehouse, not success

| Field | Content |
|-------|---------|
| **Severity** | P0 |
| **Problem** | [`import_lcsc_csv.py`](../../openhac/database/import_lcsc_csv.py) can ingest 500k rows with weak footprint maps and **no pinouts**. Easy to call that a packed catalog. |
| **Current state** | Module docstring describes download/import. No `catalog_tier`. Placeholder `CATEGORY_TO_KICAD` includes `Device:IC`. |
| **Target state** | Banner on import: warehouse import; rows without pinouts are not compile-ready. Optional `--warehouse-only` sets `catalog_tier=warehouse` (**CAT-009**). README / USER_GUIDE one-liner. |
| **Acceptance criteria** | Running the importer prints the banner. Test: imported row without pinout grades `warehouse`. |
| **Approach** | Stderr banner; `catalog_tier` column when **CAT-009** lands, else attributes JSON. |

### CAT-008 — Overlay fields for 3D and SPICE pointers

| Field | Content |
|-------|---------|
| **Severity** | P1 |
| **Problem** | Overlay README lists pinout / footprint / MPN only. 3D and SPICE pointers are already DB columns (`model_3d_local`, `spice_include`, `spice_subckt`) but not documented as overlay keys. |
| **Current state** | [`package_catalog_overlays/README.md`](../../openhac/database/package_catalog_overlays/README.md). |
| **Target state** | Overlay objects may set `model_3d_local`, `model_3d_sha256`, `model_3d_license`, `spice_include`, `spice_subckt`. User overlays still win. |
| **Acceptance criteria** | Overlay fixture stamps those fields on `get_component()`. README lists them. |
| **Approach** | Merge keys in catalog overlay loader; docs. |

### CAT-009 — Verified subset vs warehouse

| Field | Content |
|-------|---------|
| **Severity** | P1 |
| **Problem** | No persisted tier. `--production` is expected to use verified rows but cannot query them. |
| **Current state** | `pinout_source` exists; no `catalog_tier`. |
| **Target state** | Persist `catalog_tier` (`verified` \| `warehouse`) and keep `pinout_source`. `verified` is the subset `--production` is expected to use. Sync/CSV default `warehouse`; overlay / named enrich may promote to `verified`. |
| **Acceptance criteria** | Schema migration; grade helper consults tier when set; production compile of a warehouse-only IC still fails on missing pins (existing FAB), not by silently inventing them. |
| **Approach** | Schema v10 (or next) column; set on write paths. |

### CAT-010 — Optional Nexar / Octopart aggregator

| Field | Content |
|-------|---------|
| **Severity** | P1 |
| **Problem** | Digi-Key / Mouser / TME miss parts that aggregators know. Adding Nexar as a default CI dependency would couple the toolchain to a commercial API. |
| **Current state** | `vendor_apis.py` has DigiKey, Mouser, JLCPCB, TME. No Nexar. |
| **Target state** | Optional Nexar/Octopart client behind API keys; same enrich entrypoint; **fail closed** if keys missing (do not scrape). Not a default CI dependency. |
| **Acceptance criteria** | Without keys, enrich `--vendor nexar` errors clearly. With mocked keys, named pinout maps into `pinout_json`. CI default path unchanged. |
| **Approach** | New client in `vendor_apis.py`; env keys; `network_allowed()`. |

### CAT-011 — Second PCBA catalog (PCBWay / Seeed)

| Field | Content |
|-------|---------|
| **Severity** | P2 |
| **Problem** | JLC-only offers hide second-assembler stock. A second catalog must not become a second electrical source of truth. |
| **Current state** | `part_offers` table exists. |
| **Target state** | PCBWay / Seeed as additional **offer rows** (`part_offers`), not a second pin/footprint SoT. Pin table still from overlay / Digi-Key / verified JLC. |
| **Acceptance criteria** | Offer fixture does not override `pinout_json`. BOM can list a second SKU. |
| **Approach** | Offer ingest; do not fork `get_component` identity. |

### CAT-012 — Licence-gated symbol / 3D shops

| Field | Content |
|-------|---------|
| **Severity** | P2 |
| **Problem** | SnapEDA / UltraLibrarian / SamacSys can fill symbols and 3D, but licences often forbid silent redistrib. |
| **Current state** | EasyEDA JIT only. |
| **Target state** | Optional fetch records `model_3d_license` / symbol licence; refuse to copy into git; cache locally like EasyEDA. No silent republish. |
| **Acceptance criteria** | Without an explicit licence field, do not store the file. Docs state the shop is optional. |
| **Approach** | Later client; **3D-001** provenance. |

### CAT-013 — KiCad library as pin-name oracle

| Field | Content |
|-------|---------|
| **Severity** | P1 |
| **Problem** | A real `kicad_symbol` (`Device:R`, `Regulator_Linear:AMS1117-3.3`) already has named pins in the installed KiCad lib. Warehouse rows ignore that. |
| **Current state** | `kicad_sym_pinpos` reads symbol geometry for schematic emit. Catalog pinout is separate. |
| **Target state** | When `kicad_symbol` is a **real lib id** (not `Device:IC` / `MCU_Module:Generic_MCU`), fill pin **names** from the KiCad symbol. Do **not** invent connectivity or pad maps. Still `warehouse` until footprint + 3D grades pass. |
| **Acceptance criteria** | Test: `Device:R` → pins 1/2 named. `Device:IC` → no fill. |
| **Approach** | Reuse symbol parse; call from enrich-or-grade, not from `--production` if it would HTTP (it must not; KiCad is local). |

### CAT-014 — Periodic snapshot job (maintainer)

| Field | Content |
|-------|---------|
| **Severity** | P2 |
| **Problem** | Catalog rot. Maintainers need a documented refresh, not a compile-time sync. |
| **Current state** | Manual `openhac sync`. |
| **Target state** | Documented maintainer job (script or workflow, **not** `--production`): sync + coverage JSON. Optional; not a user compile phase. |
| **Acceptance criteria** | Docs name the job. CI for users does not require live jlcsearch. |
| **Approach** | Script under `scripts/`; workflow optional / manual dispatch. |

### CAT-015 — Parametric twins via alternates

| Field | Content |
|-------|---------|
| **Severity** | P2 |
| **Problem** | Same electrical part, different SKU/assembler, needs a twin without duplicating pin tables. |
| **Current state** | `part_alternates` / `part_offers` tables exist. |
| **Target state** | Document and use those tables for parametric twins (same `generic_name` pinout, different offer). Do not clone pinout per SKU. |
| **Acceptance criteria** | Alternate fixture: compile uses primary pinout; BOM can show alternate SKU. |
| **Approach** | Docs + existing tables; no second SoT. |

---

## B. 3D as a catalog field — 3D-001…005

Leverage `model_3d_url` / `model_3d_local` (schema v9), [`easyeda_integration.py`](../../openhac/database/easyeda_integration.py), [`threed_downloader.py`](../../openhac/database/threed_downloader.py), [3D_MODELS_AND_FOOTPRINTS.md](../3D_MODELS_AND_FOOTPRINTS.md).

### 3D-001 — Provenance columns

| Field | Content |
|-------|---------|
| **Severity** | P0 |
| **Problem** | A path string is not an audit. EasyEDA vs KiCad lib vs overlay are indistinguishable. |
| **Current state** | `model_3d_url`, `model_3d_local` only. |
| **Target state** | `model_3d_sha256`, `model_3d_license`, `model_3d_source` (`kicad_lib` \| `easyeda` \| `overlay` \| `manufacturer`). Path without hash is allowed for **library** models; EasyEDA/overlay files hash when the file is present. |
| **Acceptance criteria** | Migration; EasyEDA prefetch writes source + sha256; library-passive row may omit sha256 with `source=kicad_lib`. |
| **Approach** | Schema columns next to v9; write on prefetch / overlay merge. |

### 3D-002 — Prefer KiCad library 3D for JEDEC passives

| Field | Content |
|-------|---------|
| **Severity** | P0 |
| **Problem** | EasyEDA-JIT of `R_0603` can attach a second, worse cube when KiCad already ships `${KICAD*_3DMODEL_DIR}` models. |
| **Current state** | `--auto-enrich-board` fetches EasyEDA when `model_3d_local` is missing. |
| **Target state** | JEDEC passives (`R_0603`, `C_0805`, SOIC, SOT-23, …): prefer KiCad 3dmodels. Do **not** EasyEDA-JIT a second cube when the library model exists. |
| **Acceptance criteria** | Test: 0603 resistor with stock footprint does not call EasyEDA when `KICAD*_3DMODEL_DIR` has the model (or when the path pattern is the stock one). Oddball LCSC package still may JIT. |
| **Approach** | Footprint→library-3D map in enrich; skip JIT when hit. |

### 3D-003 — Prefetch CLI (blocked under production)

| Field | Content |
|-------|---------|
| **Severity** | P0 |
| **Problem** | JIT during compile surprises `--production` (network denied) and leaves empty 3D in pcbnew. |
| **Current state** | JIT inside enrich phase / `--auto-enrich-board`. |
| **Target state** | `openhac catalog prefetch-3d` (board file or SKU list) fills `~/.kiro/openhac/easyeda_generated.3dshapes/` (and pretty). Honors `network_allowed()`. **Forbidden** under fabrication compile and `OPENHAC_NO_NETWORK`. |
| **Acceptance criteria** | Prefetch with network mocked downloads once. `--production` compile does not call EasyEDA. `OPENHAC_NO_NETWORK=1` prefetch exits non-zero. |
| **Approach** | CLI; reuse `easyeda_integration`; same cache paths. |

### 3D-004 — Missing 3D is a coverage row, not a surprise

| Field | Content |
|-------|---------|
| **Severity** | P0 |
| **Problem** | pcbnew opens with missing models; some examples already emit `*_missing3Dmodels.txt`. |
| **Current state** | Ad-hoc missing-3D text on some example compiles. |
| **Target state** | Missing 3D is a **CAT-006** coverage row (and existing example text files may remain). Fab **may warn**. Do **not** silently bind a fake / cube model. |
| **Acceptance criteria** | Coverage JSON lists refs/generic_names missing 3D. No placeholder STEP invented in-tree. |
| **Approach** | Grade helper + coverage CLI; keep example reports if present. |

### 3D-005 — Git policy for 3D binaries

| Field | Content |
|-------|---------|
| **Severity** | P0 |
| **Problem** | STEP blobs in git would explode the repo and fight EasyEDA cache. |
| **Current state** | `.gitignore` already has `**/*.step` and `**/*.wrl`. Cache is `~/.kiro/openhac/`. |
| **Target state** | Spec restates: no `.step` / `.wrl` in this repo; cache under `~/.kiro/openhac/`. Overlays store **paths and hashes**, not file bytes. |
| **Acceptance criteria** | This paragraph exists; gitignore remains. CI does not require committed STEP. |
| **Approach** | Docs only unless gitignore regresses. |

---

## C. SPICE follow-on — SPS-050…057

Does **not** reopen **SPS-010…044**. Registry, `${OPENHAC_SPICE_VENDOR_DIR}`, sha256, analog island, `--require-vendor-models` stay as implemented in [`openhac/compiler/spice_models.py`](../../openhac/compiler/spice_models.py).

[`examples/fundi_mig_spice/overlay.json`](../../examples/fundi_mig_spice/overlay.json) already points at `.cir` files that are **not** in git. This chapter closes that gap with in-repo physics decks and/or vendor-dir records — not by fetching Analog Devices / TI models.

### SPS-050 — Coverage without running ngspice

| Field | Content |
|-------|---------|
| **Severity** | P0 |
| **Problem** | Model holes are only obvious after `--spice-signoff` fails inside ngspice (or not at all in handoff). |
| **Current state** | `collect_spice_coverage` exists; used in the sign-off audit (**SPS-044**). No CLI without simulate. |
| **Target state** | `openhac spice coverage BOARD.py` lists primitive / modeled / omitted / unmodeled. Reuses `collect_spice_coverage`. Does not run ngspice. Does not fetch `.lib`. |
| **Acceptance criteria** | Divider board: resistors `primitive`. Unmodeled LDO: `unmodeled`. Header: `omitted`. Exit 0 even when unmodeled (report, not sign-off). |
| **Approach** | CLI; import board; call helper. |

### SPS-051 — Vendor-record template (human URL only)

| Field | Content |
|-------|---------|
| **Severity** | P1 |
| **Problem** | Users do not have an example of `kind=vendor` with `${OPENHAC_SPICE_VENDOR_DIR}` and sha256. Fundi overlay uses `kind=physics` + missing local `.cir`. |
| **Current state** | Bundled overlay is physics/behavioral only. |
| **Target state** | Template record: `kind=vendor`, `include` with `${OPENHAC_SPICE_VENDOR_DIR}/…`, `sha256`, `pin_map`, `physics_checks`, `license`. Optional `notes.download_page` (human URL). **Loader must ignore URLs** — never HTTP. Example overlay for one Fundi analog IC as **documentation**, not a fetched file. |
| **Acceptance criteria** | Loader test: `download_page` present does not cause a request. Missing vendor file still fails **SPS-011** under sign-off. |
| **Approach** | Example JSON under `examples/` or `spice_model_overlays/` with a `.example` suffix if sha256 cannot be known. |

### SPS-052 — `verify-vendor-dir` (local hash check)

| Field | Content |
|-------|---------|
| **Severity** | P0 |
| **Problem** | Hash mismatches surface only under sign-off, late. |
| **Current state** | `verify_record_file` / `file_sha256` in `spice_models.py`. |
| **Target state** | `openhac spice verify-vendor-dir`: every `kind=vendor` record — file exists, sha256 matches, `.subckt` arity matches `pin_map`. Exit non-zero on mismatch. **No network.** |
| **Acceptance criteria** | Tmp hashed `.lib` passes; flipped hash fails; unset vendor dir fails for vendor records (same as **SPS-011**). Physics-only registry exits 0. |
| **Approach** | CLI wrapping existing verify helpers. |

### SPS-053 — More in-repo Apache physics decks

| Field | Content |
|-------|---------|
| **Severity** | P0 |
| **Problem** | Package ships `nmos_l1.cir` and `ldo_beh.cir` (behavioral). Fundi overlay references `ad620.cir`, `pc817.cir`, `d_1n4007.cir`, … that are not in git, so analog-island CI cannot depend on them. |
| **Current state** | [`openhac/database/spice_models/`](../../openhac/database/spice_models/) + [`bundled_openhac.json`](../../openhac/database/spice_model_overlays/bundled_openhac.json). |
| **Target state** | Additional **Apache-2.0** physics decks: diode, optocoupler LED-side (or CTR stub that is honest), simple in-amp macromodel. Register in `bundled_openhac.json`. Enough that analog-island CI does not depend on missing Fundi files. **Not vendor twins**; `notes` must say so. |
| **Acceptance criteria** | `kind=physics` benches pass under `--spice-signoff` without `OPENHAC_SPICE_VENDOR_DIR`. Notes contain “not a vendor part” (or equivalent). No proprietary `.lib` in git. |
| **Approach** | Author small ngspice subckts; `physics_checks[]` as **SPS-016**. |

### SPS-054 — Refuse encrypted / LTspice-only payloads

| Field | Content |
|-------|---------|
| **Severity** | P1 |
| **Problem** | Encrypted LTspice decks will not run in ngspice even if copied into the vendor dir. Silent include wastes hours. |
| **Current state** | `simulator` field defaults to `ngspice`. No file-magic check. |
| **Target state** | `simulator` must be `ngspice` for sign-off/verify. Fail if the file looks encrypted or is `.asc`. Document: encrypted LTspice ≠ ngspice. |
| **Acceptance criteria** | `.asc` include fails verify. Binary/encrypted sniff fails. Plain ASCII `.lib` with `.subckt` still passes. |
| **Approach** | Heuristic in `verify_record_file`; docs in USER_GUIDE (**SPS-056**). |

### SPS-055 — Stamp catalog from registry

| Field | Content |
|-------|---------|
| **Severity** | P1 |
| **Problem** | `spice_include` / `spice_subckt` on the SQLite row can disagree with the SPICE overlay registry. |
| **Current state** | Columns exist (schema v2/v3). Registry is separate JSON. |
| **Target state** | On `get_component`, if `lookup_registry(generic_name, mpn)` hits, stamp `spice_include` / `spice_subckt` (and kind/sha256 fields if present) so catalog and registry cannot silently diverge. Overlay still wins for pin/footprint. |
| **Acceptance criteria** | Test: registry hit appears on `get_component` dict. `OPENHAC_NO_BUNDLED_SPICE_MODELS=1` does not stamp bundled physics. |
| **Approach** | Call registry from `get_component` after overlay merge. |

### SPS-056 — USER_GUIDE operator path

| Field | Content |
|-------|---------|
| **Severity** | P0 |
| **Problem** | Users are not told how to use vendor models without putting `.lib` in git. |
| **Current state** | USER_GUIDE mentions `b.simulate()` and 3D JIT. SPS honest claim lives in internal specs. |
| **Target state** | USER_GUIDE section: drop vendor `.lib` in `OPENHAC_SPICE_VENDOR_DIR` → overlay JSON with sha256/`pin_map` → `openhac spice verify-vendor-dir` → `--spice-signoff`. Point at analog island (**SPS-043**). Point at this spec. |
| **Acceptance criteria** | Those commands appear in USER_GUIDE. No instruction to curl a `.lib` from the compiler. |
| **Approach** | Docs only. |

### SPS-057 — Non-goals (this chapter)

| Field | Content |
|-------|---------|
| **Severity** | P0 |
| **Problem** | Easy to “finish” SPICE by fetching TI/ADI models or marking **SPS-019** done. |
| **Current state** | [SPICE_SIGN_OFF_SPEC.md](./SPICE_SIGN_OFF_SPEC.md) non-goals already forbid redistributing vendor `.lib` and auto-download. IMPLEMENTATION_STATUS out-of-scope line: HTTP fetch of vendor SPICE `.lib`. |
| **Target state** | This spec’s non-goals box (below) is the operator restatement. **SPS-019 remains reserved.** Status table must not mark HTTP fetch as in-scope. |
| **Acceptance criteria** | This section exists. IMPLEMENTATION_STATUS keeps the HTTP-fetch out-of-scope line. |
| **Approach** | Docs only. |

---

## Non-goals (this spec)

- Reopening closed **FAB / PERF / SSO / LIVE / SPS-001…044** rows
- HTTP fetch of vendor SPICE `.lib` (compile, sync, or CI). **SPS-019 stays reserved and unused**
- Scraping manufacturer model pages as a product feature
- Decrypting or translating encrypted LTspice
- Redistributing TI / ADI / other proprietary macromodels in this git repo
- Treating `import_lcsc_csv` row count or a 500k dump as catalog success
- Bundling `.step` / `.wrl` binaries in git
- Nexar / SnapEDA as P0 or as a default CI dependency
- A second electrical source of truth (assembler catalogs are **offers**)
- MCU / FPGA digital SPICE twins (omit + coverage; **SIM-003** / **SPS-043**)
- Implying SPICE sign-off from `--production`
- Unmarked behavioral E-source stubs as physics-correct (**SPS-013** / **SPS-017**)

---

## Implementation order

**P0 (first implementation wave after this spec):** CAT-001, CAT-002, CAT-004, CAT-005, CAT-006, CAT-007, 3D-001…005, SPS-050, SPS-052, SPS-053, SPS-056, SPS-057.

**P1:** CAT-003, CAT-008, CAT-009, CAT-010, CAT-013, SPS-051, SPS-054, SPS-055.

**P2:** CAT-011, CAT-012, CAT-014, CAT-015.

This document is the contract. Closing an ID means code + tests + a **Done** row in [IMPLEMENTATION_STATUS.md](./IMPLEMENTATION_STATUS.md).
