# OpenHaC — Component-agnostic library (UNF)

**Purpose:** Normative contract so OpenHaC **resolves parts from the catalog, a board overlay, or an explicit named wrapper** — never from example BOMs or “common example” MPNs hardcoded in the library. The compiler must compile **any** board whose rows are packed, not merely the in-tree demos.

**Audience:** Core maintainers implementing catalog overlays, stdlib parametric constructors, enrich/sync symbol defaults, ERC/layout policy, and CI goldens.

**Status:** Normative. Progress tracked in [IMPLEMENTATION_STATUS.md](./IMPLEMENTATION_STATUS.md) (UNF table). Product scope: [SCOPE.md](./SCOPE.md).

**Relationship:** Additive IDs (**UNF-001…013**). Does **not** reopen closed FAB/PERF/SSO/LIVE/CAT/3D/SPS-05x/workflow-gate rows except as **pointers**. **LIB-007**, **CODE-003**, **SCH-006**, **ABC-046**, and **CODE-004** stay **Done**; this spec is leftover honesty those rows did not finish. `--production` stays offline (**FAB-010**). `--require-all` stays the **2×0805 resistor** class only (**FAB-051**). HTTP fetch of vendor SPICE `.lib` stays forbidden (**SPS-019** reserved unused). Analogous to [LIVE_KICAD_SPEC.md](./LIVE_KICAD_SPEC.md) and [CATALOG_DEPTH_SPEC.md](./CATALOG_DEPTH_SPEC.md): not a rewrite of closed tables.

---

## Product lock

- **Python is the HDL.** Part identity is a catalog row (`generic_name` / MPN / SKU) plus optional overlay. KiCad stays renderer and ERC stamp.
- **The library is component-agnostic.** `openhac/compiler`, `openhac/schematic`, bundled **auto-merge** overlays, and parametric stdlib constructors must not contain a vendor MPN, LCSC C-code, or example `generic_name` (ICM-42688, STM32F407, AMS1117, MAX3485, BMP280, …).
- **Examples are allowed to be specific.** `examples/`, `tests/fixtures/vendor/`, and board sidecars ([`board_sidecars.py`](../../openhac/compiler/board_sidecars.py)) ship the demo BOM. Grid-edge RTU already does this via `complex_grid_edge_rtu.openhac.json` — that pattern is the rule, not an exception.
- **Named wrappers stay.** `ESP32_WROOM` looking up `ESP32-WROOM-32E` is the class identity. `MCU()` / `RF_Module()` / `RS485_Transceiver()` must not silently become that part.
- **JEDEC / device-class maps stay.** [`footprint_map.json`](../../openhac/database/footprint_map.json) LQFP/0402, `Device:R`, `MCU_Module:Generic_MCU`, 2-pin `1`/`2` tables, USB-C pad synonyms as a *connector family* — not a demo SKU.
- **Do not invent pinouts** (**CAT-004**). Unknown IC without named `pinout_json` is warehouse / fail-closed, never `Pin_1`…`Pin_N` or AMS1117 pad order.

```
board.py ──► Component / stdlib ctor
                │
                ├──► SQLite row (compile_ready or warehouse)
                ├──► user overlay / board sidecar overlay
                └──► named wrapper exact generic_name
                              │
                              ▼
                    packed row or fail
                parametric miss ──► raise (no MPN invented)
```

---

## Honest claims

**Catalog.** Bundled auto-merge overlays may fix **package class** (0805 is two-terminal). They must not inject ICM-42688, BMP388, W25Q128, LDL1117, or HRO USB-C pinouts onto every `get_component()`. Demo BOMs travel with the board (`--catalog-overlay`, `{stem}.openhac.json` sidecars).

**Stdlib.** `Resistor("10k", "0805")` searches the catalog. `RS485_Transceiver()` on an empty catalog **raises**. It does not become MAX3485 because that string lives in [`interface.py`](../../openhac/stdlib/interface.py).

**Proof.** A synthetic board whose parts are `IC_SYNTH_*` / `R_SYNTH_0805` (names that do not appear in `examples/`) either compiles from *its* overlay or fails missing-row. It never emits `STM32F407VETx`, ICM-42688 pinouts, or Maxim transceivers.

**Examples.** Grid-edge RTU, satcom, RS-485 node, and the 2R fab golden keep compiling. They do so via sidecars / overlays / the documented 2R class — not because `openhac/` remembers their SKUs.

**Named wrappers.** `ESP32_WROOM`, `Teensy41`, `BNO055_IMU`, `W5500Ethernet` remain exact lookups and raise if the row is missing. They are not the default for `MCU()` / `IMU()` / `Ethernet_PHY()`.

---

## Modes and severity

| Mode | Network | Catalog / overlay | Parametric miss | Named wrapper miss |
|------|---------|-------------------|-----------------|--------------------|
| **handoff** | Allowed unless `OPENHAC_NO_NETWORK` | User overlay + sidecars; bundled auto-merge is package-class only | Raise (no vendor MPN) | Raise |
| **`--production` / fabrication** | **Denied** | Offline packed rows only (**FAB-010**, **CAT-001**) | Raise | Raise |
| **example compile** | Per flags | Board sidecar / `--catalog-overlay` supplies demo parts | n/a if overlay packed | n/a if row present |
| **catalog maintainer** (`sync` / `enrich`) | Allowed | Device-class symbols on warehouse rows; MPN symbols only from vendor/overlay | n/a | n/a |

| Severity | Meaning |
|----------|---------|
| **P0** | Silent wrong part for a stranger board (demo overlay auto-merge, category → STM32/AMS1117, parametric miss → Maxim) |
| **P1** | Pin-order / enrich-SKU / name-token policy / seed personality / tests locking the demo BOM |
| **P2** | 3D matcher keys, placement profile name, SPICE omit list, physics-deck aliases |

Each requirement includes: **problem**, **current state**, **target state**, **acceptance criteria**, and **approach**.

---

## Why LIB-007 / CODE-003 are not enough

**LIB-007** stopped auto-merging files whose name contains `reference_bom`. [`00_reference_bom.json`](../../openhac/database/package_catalog_overlays/00_reference_bom.json) is now a sentinel. The same satcom / IoT parts moved into [`01_package_pinout_fixups.json`](../../openhac/database/package_catalog_overlays/01_package_pinout_fixups.json), which **is** auto-merged. [`tests/test_sep2026_job_spec.py`](../../tests/test_sep2026_job_spec.py) `test_lib007_reference_bom_not_auto_merged` asserts `"IMU_ICM42688P" in idx` — the “fixed” overlay still **requires** the demo IMU in the bundled index.

**CODE-003** fail-closed [`RF_Module`](../../openhac/stdlib/interface.py) and SwitchingRegulator family pin maps. [`PressureSensor`](../../openhac/stdlib/sensors.py) still defaults to BMP280. [`RS485_Transceiver`](../../openhac/stdlib/interface.py) still picks MAX3485. [`VoltageRegulator`](../../openhac/stdlib/power.py) still wires pins `1/2/3` as GND/OUT/IN.

**SCH-006** gated schematic *name* tokens behind `OPENHAC_SCHEMATIC_FLOW_NAME_TOKENS`. ERC/layout still key off `imu` / `ldo` / `xt60` in [`rule_check.py`](../../openhac/compiler/rule_check.py) and [`layout_heuristics.py`](../../openhac/compiler/layout_heuristics.py).

**ABC-046** RF policy is `board_class=rf` + `RF_Module:` prefix. That stays. This spec does not reopen it.

---

## Allowed vs forbidden in `openhac/`

| Allowed | Forbidden |
|---------|-----------|
| Named wrapper class whose *type name* is the part (`ESP32_WROOM` → `ESP32-WROOM-32E`) | Parametric ctor miss → that same MPN |
| JEDEC package → KiCad footprint (`0402`, `LQFP-64`) | Category → `STM32F407VETx` / `W25Q128JV` / `AMS1117-3.3` / `BMI160` / `BSS138` |
| Device-class symbols (`Device:R`, `Device:IC`, `MCU_Module:Generic_MCU`) | Auto-merged overlay rows named `IMU_ICM42688P`, `BARO_BMP388`, … |
| 2-pin `1`/`2` (or A/K) for two-terminal passives (**CAT-004**) | Numeric-only IC pinouts; AMS1117 pad order assumed in Python |
| USB-C pad synonyms as a connector *family* (`D+` ↔ `A6`) | Per-SKU synonym tables in the compiler |
| Example/test fixtures with real MPNs under `examples/` and `tests/fixtures/` | Those strings in bundled auto-merge JSON or `openhac/compiler` / `openhac/schematic` |
| Board sidecars (`{stem}.openhac.json`, `catalog_overlays/`) | `get_component()` mutating strangers from a demo BOM |

---

## A. P0 — fail closed / stop mutating strangers

### UNF-001 — Agnostic proof (synthetic board, not an example)

| Field | Content |
|-------|---------|
| **Severity** | P0 |
| **Problem** | CI and goldens prove the library against ICM-42688, STM32, AMS1117, MAX3485, and the 2R fab golden. A board that is none of those can still “work” by inheriting those identities. |
| **Current state** | No tracked board whose `generic_name`s are absent from `examples/`. Overlay tests lock `IMU_ICM42688P` / `FLASH_W25Q128JV`. Complex-board tests instantiate named demos. |
| **Target state** | Isolated catalog + overlay rows named `IC_SYNTH_*` / `R_SYNTH_0805` (names that **do not** appear in `examples/`). Handoff compile succeeds. Coverage grade `compile_ready` (**CAT-001**). Resolved symbol, footprint, and pinout come from the overlay. Second case: parametric `RS485_Transceiver()` / `ADC()` / `PMIC()` with no matching row **raises** (no Maxim/TI substitution). |
| **Acceptance criteria** | Test fixture under `tests/fixtures/` (not `examples/`): overlay `IC_SYNTH_QFN16` with a named pin table + real footprint; compile handoff; BOM/symbol/footprint match the overlay; assert resolved fields contain none of `STM32`, `AMS1117`, `ICM`, `MAX3485`. Test: empty catalog + `RS485_Transceiver()` / analog `ADC()` / `PMIC()` raises `ValueError` (or the stdlib not-found type) and does not call `get_component("MAX3485")` / `ADS1115` / `TPS65217`. |
| **Approach** | Small board module + overlay JSON in `tests/fixtures/agnostic/`. Pytest with `OPENHAC_NO_BUNDLED_CATALOG_OVERLAYS=1` and a temp SQLite. Implement after **UNF-002…004** so the golden is not fighting auto-merge. |

### UNF-002 — Bundled auto-merge is package-class only

| Field | Content |
|-------|---------|
| **Severity** | P0 |
| **Problem** | LIB-007 emptied `00_reference_bom.json` but the same BOM auto-merges from `01_package_pinout_fixups.json`. Every `get_component()` can inherit ICM-42688 / BMP388 / QMC5883L / W25Q128 / LDL1117 / HRO USB-C / microSD pinouts. |
| **Current state** | [`catalog_overlay.py`](../../openhac/database/catalog_overlay.py) skips files whose name contains `reference_bom`. [`01_package_pinout_fixups.json`](../../openhac/database/package_catalog_overlays/01_package_pinout_fixups.json) is **8** demo rows, auto-merged. `test_lib007_reference_bom_not_auto_merged` asserts `"IMU_ICM42688P" in idx`. [`tests/test_catalog_fixups.py`](../../tests/test_catalog_fixups.py) locks those generic_names. |
| **Target state** | Bundled auto-merge JSON contains **package-class** fixups only (or is empty). Demo pinouts live under `examples/` (or board sidecars) and load via `--catalog-overlay` / sidecar discovery. `IMU_ICM42688P` is **absent** from `load_bundled_overlay_index()` and **present** only when that overlay path is passed. Optional: skip overlays tagged `"auto_merge": false` even if they sit in the package directory. |
| **Acceptance criteria** | `load_bundled_overlay_index()` does not contain `IMU_ICM42688P`, `BARO_BMP388`, `MAG_QMC5883L`, `FLASH_W25Q128JV`, `LDO_LDL1117S33R`, `USB_C_HRO_TYPE_C_31_M_12`, `MICROSD_SLOT`. `--catalog-overlay` (or sidecar) pointing at the moved file **does**. Existing example compiles that need those pinouts pass via sidecar/overlay, not bundled merge. Flip `test_lib007_*` accordingly. |
| **Approach** | Move the eight rows to `examples/` (shared overlay or per-board sidecar). Keep bundled file empty or JEDEC-only. Extend skip logic if a `reference_bom`-style filename is not enough. |

### UNF-003 — Category default symbols are device-class

| Field | Content |
|-------|---------|
| **Severity** | P0 |
| **Problem** | JIT / sync / LCSC CSV rows without a real symbol inherit a **specific IC’s** KiCad id. A PIC or nRF52 can emit as `STM32F407VETx`; all memory CSV rows look like W25Q128. |
| **Current state** | [`api_fallback.py`](../../openhac/database/api_fallback.py) `_SYMBOL_MAP`: `microcontrollers` → `MCU_ST_STM32:STM32F407VETx`, `accelerometers` → `Sensor:BMI160`, `voltage_regulators` → `Regulator_Linear:AMS1117-3.3`. [`sync_jlc.py`](../../openhac/database/sync_jlc.py) `KICAD_SYMBOL_MAP`: `mosfets` → `Transistor_FET:BSS138`, `bjts` → `Transistor_BJT:BC847`, `voltage_regulators` → `Regulator_Linear:AMS1117-5.0` (MCU/accel already generic). [`import_lcsc_csv.py`](../../openhac/database/import_lcsc_csv.py) `CATEGORY_TO_KICAD`: `Memory` → `Memory_Flash:W25Q128JV`, `Transistors` → `Transistor_BJT:BC817`, MOSFETs BSS138, regs AMS1117-5.0. |
| **Target state** | Category defaults are **device-class** only: `Device:R` / `C` / `L` / `D` / `LED` / `Fuse`, `Device:IC`, `MCU_Module:Generic_MCU`, `Sensor_Motion:Generic_Accelerometer`, `Device:Q` (or `Device:Q_NMOS_GDS` for the FET *category*, not BSS138). MPN-specific symbols come from vendor data, overlay, or a named wrapper — never from the category map. |
| **Acceptance criteria** | Test: warehouse MCU row inserted via fallback/sync/CSV path without overlay → `kicad_symbol` does **not** contain `STM32`. Memory CSV fixture → not `W25Q128`. Regulator category default → not `AMS1117`. MOSFET/BJT defaults → not `BSS138` / `BC847` / `BC817`. Overlay or vendor field can still set a real symbol. |
| **Approach** | One shared device-class map (or three identical dicts). Do not reuse MPN lib ids as category placeholders. |

### UNF-004 — Parametric miss never picks a vendor MPN

| Field | Content |
|-------|---------|
| **Severity** | P0 |
| **Problem** | CODE-003 closed `RF_Module()` and SwitchingRegulator *pin maps*. About twenty other constructors still do `generic_name = "MAX3485"  # common example` (or BMP280-only `PressureSensor`) when parametric search is empty, then `get_component` / live lookup of that MPN. |
| **Current state** | Miss-fallbacks include: [`interface.py`](../../openhac/stdlib/interface.py) MAX3485/MAX485, SN65HVD230/TJA1050, CP2102, LAN8720A; [`analog.py`](../../openhac/stdlib/analog.py) ADS1115/MCP3008, AD8221, 74HC4051/TS5A3159, LM393/TLV3201; [`power.py`](../../openhac/stdlib/power.py) TPS65217, MAX17048; [`sensors.py`](../../openhac/stdlib/sensors.py) TMP102/LM35, BMP280, ACS758/INA219; [`protection.py`](../../openhac/stdlib/protection.py) LM74700, TMP302; [`opto.py`](../../openhac/stdlib/opto.py) ITR9608-F, PT4115, TLP172A, TSOP38238; [`electromechanical.py`](../../openhac/stdlib/electromechanical.py) DRV8833; [`discretes.py`](../../openhac/stdlib/discretes.py) MMBT2222/MMBT2907; [`audio.py`](../../openhac/stdlib/audio.py) LM4871; [`clock.py`](../../openhac/stdlib/clock.py) SIT8008, POS-100. Storage [`storage.py`](../../openhac/stdlib/storage.py) builds `W25Q{size}` / `24LC{size}` as the search key. Named wrappers (`ESP32_WROOM`, `Teensy41`, `BNO055_IMU`, `W5500`) are exact lookups — keep those. |
| **Target state** | Every `_ParametricMixin` constructor: parametric search → optional live lookup of the **requested query** (family/protocol/value, not a baked MPN) → else `_raise_not_found`. Delete “common example” MPN strings. Named wrappers remain exact `get_component` and raise if missing. `Flash(size_mb=128)` searches catalog by density/category or requires `mpn=`; it must not imply Winbond. |
| **Acceptance criteria** | Tests (empty DB, no network): `RS485_Transceiver()`, `ADC()`, `PMIC()`, `PressureSensor()`, `CAN_Transceiver()` raise; spy/assert no `get_component("MAX3485")` / `"BMP280"` / `"TPS65217"`. `ESP32_WROOM()` with missing row raises (does not search a different MCU). `RF_Module()` remains CODE-003 fail-closed. |
| **Approach** | Shared miss path on `_ParametricMixin`. Grep stdlib for `generic_name = "` and `# common example`. Live lookup may use the **operator’s** query string only. |

---

## B. P1 — pin geometry, enrich, policy, seed, tests

### UNF-005 — Pins and footprints from the row

| Field | Content |
|-------|---------|
| **Severity** | P1 |
| **Problem** | `VoltageRegulator` wires pad numbers 1/2/3 as GND/OUT/IN (AMS1117 SOT-223). `SwitchingRegulator` hardcodes `Capacitor_SMD:C_0805_2012Metric` and `Inductor_SMD:L_Bourns_SRN6045TA` after CODE-003 removed magic L values. [`packages.py`](../../openhac/templates/packages.py) SOT-23 = G/S/D and SOT-223 = IN/GND/OUT for every part in that package. |
| **Current state** | [`power.py`](../../openhac/stdlib/power.py) `VoltageRegulator` ~90–92; SwitchingRegulator ~508–518 (`l_value` required — keep that). Package templates SOT-23 / SOT-23-5 / SOT-223 named as FET/LDO. |
| **Target state** | Connect by catalog pin **names** (VIN/IN, VOUT/OUT, GND aliases), not pad numbers, unless the overlay’s pin table *is* that numbering. Passives on a switching regulator take package/footprint from catalog or author constraints, not Bourns/0805 literals. SOT-23/SOT-223 templates are numeric placeholders unless category is FET/LDO per [`pin_policy.py`](../../openhac/database/pin_policy.py). |
| **Acceptance criteria** | Test: overlay LDO with swapped pad names (1=IN, 2=GND, 3=OUT vs AMS1117) wires nets to the named pins. Test: AMS1117-order overlay still works. Test: SwitchingRegulator without a catalog inductor footprint does not emit `L_Bourns_SRN6045TA`. Test: SOT-23 BJT does not inherit G/S/D from the FET template. |
| **Approach** | Name-alias helper (VIN/IN/VCC, VOUT/OUT, GND). Footprint from `part_data` / constraints. Split package templates by category the same way pin_policy already does. |

### UNF-006 — No Python SKU tables in enrich

| Field | Content |
|-------|---------|
| **Severity** | P1 |
| **Problem** | [`enrich.py`](../../openhac/database/enrich.py) `PHYSICAL_ASSET_OVERRIDES` / `SEMANTIC_PINOUTS` hard-wire Raspberry Pi 5 (`C2114620`), Teensy 4.1 (`C2344710`), XT90 (`C2991758`) footprints and 40-pin tables. Name-contains checks apply them during online enrich. |
| **Current state** | Dicts at enrich.py ~23–97; apply at ~571–577 (`if "Raspberry_Pi_5" in gn`). Other `C\d{5,}` in `openhac/**/*.py` are mostly docstrings plus [`seed_data.py`](../../openhac/database/seed_data.py) (**UNF-008**). |
| **Target state** | Those tables live in JSON overlay (opt-in, like any board overlay). Enrich merges overlay / vendor fields only. `openhac/**/*.py` has no `C\d{5,}` literals except docstrings/comments. |
| **Acceptance criteria** | Grep test: `openhac/**/*.py` excluding tests — no `C[0-9]{5,}` outside `#` / docstring / `e.g.` comments. Test: enrich of an unrelated SKU does not gain a Pi header pinout. Overlay file can still pack Pi/Teensy when the operator passes it. |
| **Approach** | Move dicts to `examples/` or `package_catalog_overlays/` with auto-merge **off**. Enrich reads overlay merge already in `get_component`. |

### UNF-007 — Policy from declared roles, not name archaeology

| Field | Content |
|-------|---------|
| **Severity** | P1 |
| **Problem** | ERC and layout still substring-match `imu` / `baro` / `mag` / `ldo` / `buck` / `xt60` / `8mhz`. Rename a module and the warning or edge-pin disappears. [`db_manager`](../../openhac/database/db_manager.py) poison-footprint audit keys `raspberry` / `teensy` / `esp32` / `stm32`. |
| **Current state** | [`rule_check.py`](../../openhac/compiler/rule_check.py) `_check_power_sequencing` ~1123–1148; `_check_crystal_loading` ~1095–1119 (`8mhz` / `18pf` in the name). [`layout_heuristics.py`](../../openhac/compiler/layout_heuristics.py) ~30–39 (`xt60`, `ldo`, `buck`). Schematic flow name tokens already gated (**SCH-006**). Poison keywords ~669–674. |
| **Target state** | Policy from `Module.role` / `schematic_flow` / component `category` / power-tree metadata (same direction as SCH-006). Crystal load-cap check uses attributes or parametric value, not `8mhz` in the name. Poison audit: IC/module **category** vs chip-R **package class** — drop the demo MCU keyword list. `xt60` is not a connector class. |
| **Acceptance criteria** | Test: module named `PSU1` with `role`/`schematic_flow`/`category` of regulator still participates in the power check; module named `imu_demo` that is a connector does not. Test: crystal with `frequency_hz` / value in attributes, name `Y1`, still requests two load caps. Test: `GENERIC_MCU` on 0805 footprint is poisoned; `R_10k_0805` is not; no dependency on the string `esp32`. |
| **Approach** | Reuse `schematic_flow` and interface kinds; add a small `role` field if missing. Category already on `comp_data`. |

### UNF-008 — Seed is a tutorial pack

| Field | Content |
|-------|---------|
| **Severity** | P1 |
| **Problem** | [`seed_data.py`](../../openhac/database/seed_data.py) early-out comment: “already seeded with production flight-controller parts.” Inserts STM32F407 `C28730`, ESP32-WROOM `C529596`, USB-C `C165948`, fake XT60 `C123456`, AMS1117s. That becomes the implied catalog personality for offline `openhac seed`. |
| **Current state** | `seed_database()` inserts a curated flight-controller BOM; idempotent `part_offers` for `R_10k_0805`. |
| **Target state** | Default seed is empty or **passives-only** (enough for the 2R golden). STM32/ESP32/USB-C/XT60 list is opt-in: `openhac seed --pack flight_controller` and/or files under `examples/`. Docs say seed is a tutorial pack, not the catalog SoT. |
| **Acceptance criteria** | Test: default `seed_database()` on empty DB does not insert `MCU_STM32F407VET6` / `ESP32_WROOM`. Test: opt-in pack (or example seed file) does. 2R golden still compiles with passives seed or its own fixture. |
| **Approach** | Split packs; CLI flag; keep `_seed_idempotent_part_offers` or move those LIB-001 samples to the passives pack. |

### UNF-009 — Tests prove the mechanism, not the demo BOM

| Field | Content |
|-------|---------|
| **Severity** | P1 |
| **Problem** | Overlay mechanism tests freeze ICM/W25Q/LDL1117/USB_C_HRO as a library contract. Closing UNF-002 without retargeting tests either fails CI or preserves the leak. |
| **Current state** | [`tests/test_catalog_fixups.py`](../../tests/test_catalog_fixups.py) asserts `IMU_ICM42688P` footprint/SKU, `FLASH_W25Q128JV` pads, `LDO_LDL1117S33R`, HRO USB-C. `test_lib007_reference_bom_not_auto_merged` requires `IMU_ICM42688P` in the bundled index. Example boards belong in `test_complex_*` / live artwork tests — those may keep real MPNs. |
| **Target state** | Mechanism tests use synthetic `generic_name`s (`IC_SYNTH_*`). Example boards stay in example/complex tests. CI grep: `openhac/compiler` + `openhac/schematic` have no example MPN tokens; bundled **auto-merge** JSON has none of `ICM42688|BMP388|QMC5883|LDL1117|W25Q128`. |
| **Acceptance criteria** | `test_catalog_fixups.py` passes with synthetic rows only. Grep job (pytest or `scripts/`) fails if bundled auto-merge JSON regains those tokens or if compiler/schematic gain `ICM-42688` / `STM32F407VETx` / `MAX3485` as literals (docstrings excluded). `test_complex_grid_edge_rtu.py` and satcom examples still allowed to name parts. |
| **Approach** | Pair with UNF-002. Shared forbidden-token list in one test module. |

---

## C. P2 — hygiene

### UNF-010 — 3D fill-in matcher from map keys

| Field | Content |
|-------|---------|
| **Severity** | P2 |
| **Problem** | [`kicad_3d.py`](../../openhac/database/kicad_3d.py) `footprint_3d_match_keys` (~760–791) regexes `TYPE-C-31-M-12`, `47219-2001`, `MICROSD`, `TF-CARD` — the same two connectors as [`3d_fillin_map.json`](../../openhac/database/3d_fillin_map.json). |
| **Current state** | Map has two `lcsc:C…` entries (data, not a Python fork). Python duplicates those keys. |
| **Target state** | Match keys derived from fill-in map footprint ids (and generic package-class rules). Map may stay sparse. No Python regex pair for HRO/Molex specifically. |
| **Acceptance criteria** | Test: adding a third map entry produces match keys without a kicad_3d.py edit. Test: existing HRO/microSD behaviour still holds when those keys remain in the JSON map. |
| **Approach** | Parse `3d_fillin_map.json` in `footprint_3d_match_keys`; keep alnum stem compare. |

### UNF-011 — Placement profile name is a packing class

| Field | Content |
|-------|---------|
| **Severity** | P2 |
| **Problem** | [`placement_profile.py`](../../openhac/compiler/placement_profile.py) profile `complex_ci` encodes “the complex demos” in the name. CODE-004 named knobs are correct; the name is not. |
| **Current state** | `PROFILES["complex_ci"]` plus `for_route` extra knobs. Complex validator sets `OPENHAC_PLACEMENT_PROFILE=complex_ci`. |
| **Target state** | Canonical name `dense_ci` (clearance / inflate / margin packing class). Keep `complex_ci` as a one-release alias. Docs/CI use `dense_ci`. |
| **Acceptance criteria** | Test: `apply_named_placement_profile(name="dense_ci")` sets the same knobs as today’s `complex_ci`. Alias still applies. CI script/docs mention `dense_ci`. |
| **Approach** | Duplicate dict key or alias map; update `ci_validate_complex_boards.py` and CODE-004 comments. |

### UNF-012 — SPICE digital-core omit by category

| Field | Content |
|-------|---------|
| **Severity** | P2 |
| **Problem** | [`spice_models.py`](../../openhac/compiler/spice_models.py) `_DIGITAL_CORE_NAME_MARKERS` lists ESP32, STM32, RP2040, NRF52, CH340, … A digital core whose name is none of those can demand a macromodel; an analog part whose MPN contains `STM32` as a substring could be omitted wrongly. |
| **Current state** | Category substrings `microcontroller` / `fpga` / `cpld` already exist beside the name list. |
| **Target state** | Category is SoT for digital-core omit. Name markers are an optional extra, documented as heuristic, or removed. |
| **Acceptance criteria** | Test: part category `microcontrollers`, generic_name `IC_SYNTH_MCU`, omitted as digital core. Test: analog category + name containing `STM32` as a false friend is **not** omitted by name-only (if markers remain, require category too). |
| **Approach** | Gate name markers behind category ∈ digital-core set, or delete the tuple. |

### UNF-013 — Bundled SPICE physics aliases, not vendor twins

| Field | Content |
|-------|---------|
| **Severity** | P2 |
| **Problem** | [`bundled_openhac.json`](../../openhac/database/spice_model_overlays/bundled_openhac.json) `NMOS_L1` / `LDO_BEH` already use `OPENHAC-*` MPNs. `D_1N4007`, `OPTO_PC817`, `AD620` are named like vendor parts (**SPS-053** in-repo physics, not twins) and can look like a board BOM in the compiler. |
| **Current state** | GLD-001 / SPS-053 decks; spice-island golden references those generic_names. No `if generic_name == "AD620"` in the compiler. |
| **Target state** | Keep in-repo Apache physics. Document `D_1N4007` / `OPTO_PC817` / `AD620` as physics **aliases**, not vendor twins. Prefer `OPENHAC-*` MPNs on those records where it does not break the golden. **No** compiler branch on those names. |
| **Acceptance criteria** | Docs (this spec + SPICE overlay notes) state alias vs twin. Test: compiler/schematic grep has no special case on `AD620` / `PC817`. Golden still instantiates the physics decks (**GLD-001**). |
| **Approach** | Documentation first; optional MPN field `OPENHAC-D-1N4007` with `generic_name` unchanged so the golden keeps working. |

---

## Out of scope

- Expanding `--require-all` to a multi-IC class (**FAB-051** stays 2R).
- Deleting named wrappers (`ESP32_WROOM`, `Teensy41`, …) or in-tree examples.
- Making grid-edge RTU, satcom, RS-485, or other examples fail — they must pass via **sidecars / `--catalog-overlay` / vendor cassettes**.
- HTTP datasheet scrape; inventing pin names from pin count (**CAT-004**, **PIN-001**).
- Replacing `kicad-cli sch erc`; language rewrite; HTTP vendor SPICE `.lib` (**SPS-019**).
- Reopening **ABC-046** (RF prefix), **SCH-006** (schematic name tokens gated), **CODE-004** (named placement knobs — only the profile *name* is UNF-011).

---

## Execution order (implement batch, not this spec landing)

**UNF-002** + **UNF-009** (stop shipping/testing the demo overlay as SoT) → **UNF-003** → **UNF-004** → **UNF-001** golden → **UNF-005** → **UNF-006** → **UNF-007** → **UNF-008** → P2 (**UNF-010…013**).

Examples keep a green compile at each step by pointing sidecars at the moved overlay.
