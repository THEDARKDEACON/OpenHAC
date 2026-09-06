# OpenHaC — Open Hardware-as-Code

Python compiler that turns declarative hardware code into **netlists**, **BOMs**, **KiCad PCB** outputs, optional **FreeRouting**, and **SPICE** — no GUI required. The native circuit graph is the compile source of truth. With `--schematic-signoff`, the generated `.kicad_sch` is the EE-stamped review artifact (library symbols or pinout boxes, KiCad ERC clean). With `--spice-signoff` on `compile` or `simulate`, SPICE is a fail-closed analog gate (Kirchhoff-correct `.cir`, vendor or physics models, ngspice operating-point windows). Fabrication (`--production`) may still omit the drawing and does not imply SPICE sign-off.

## Outputs

- `.net` / `.csv` — netlist and BOM (LCSC-oriented fields when available)
- `.kicad_pcb` — placement, pad nets; optional autoroute (FreeRouting or minimal `pcbnew` fallback)
- `.kicad_sch` / `.kicad_pro` — schematic + project (off by default under `--production`; required under `--schematic-signoff`)
- Generated symbol stubs (`*.openhac-generated.kicad_sym`) and manifest / handoff JSON when configured
- `.cir` — SPICE from `Board.simulate()`, also invoked by `openhac compile --run-ngspice` / `--spice-signoff`. With `--spice-signoff`, fail-closed Kirchhoff + vendor/physics models + ngspice OP windows ([SPICE_SIGN_OFF_SPEC.md](docs/internal/SPICE_SIGN_OFF_SPEC.md)).
- Fab bundle — Gerbers / drill / position via `openhac export fab` (after a successful PCB)
- `.dsn` — Specctra for FreeRouting. Compile writes one; after KiCad placement edits use `openhac export dsn` so IPC widths are not flattened to 0.2 mm

**Docs:** [USER_GUIDE.md](docs/USER_GUIDE.md), [API_REFERENCE.md](docs/API_REFERENCE.md), [3D_MODELS_AND_FOOTPRINTS.md](docs/3D_MODELS_AND_FOOTPRINTS.md).
**Internal/Spec:** [SCOPE.md](docs/internal/SCOPE.md), [IMPLEMENTATION_STATUS.md](docs/internal/IMPLEMENTATION_STATUS.md), [FABRICATION_READINESS_SPEC.md](docs/internal/FABRICATION_READINESS_SPEC.md) (Phase-2 code→fab gates), [SCHEMATIC_SIGN_OFF_SPEC.md](docs/internal/SCHEMATIC_SIGN_OFF_SPEC.md) (EE-stamped `.kicad_sch`), [SPICE_SIGN_OFF_SPEC.md](docs/internal/SPICE_SIGN_OFF_SPEC.md) (physics-correct analog simulate), [CATALOG_DEPTH_SPEC.md](docs/internal/CATALOG_DEPTH_SPEC.md) (catalog depth / 3D pointers / SPICE operator), [PRODUCTION_VALIDATION.md](docs/internal/PRODUCTION_VALIDATION.md) (ERC→DRC→Gerbers matrix).

Autorouting is **assistive** (not a substitute for HS/EMC review). See SCOPE for **PCB-007** / differential-pair notes. Phase-2 defines fail-closed fabrication gates — track status in IMPLEMENTATION_STATUS.

**Software production claim:** `--require-all` is proved on the **minimal 2-pin 0805 resistor class** only (`tests/fixtures/fab_golden_board.py` — two resistors). A green `scripts/ci_validate_production.py --require-all` run proves code → native ERC/DRC → place → FreeRouting → KiCad PCB DRC → Gerbers with audited pin/pad parity for **that fixture**, not for multi-IC / HS / RF boards. That is **fabrication-ready software output** for the 2R golden, not physical bring-up or RF/HS sign-off.
The active circuit is the **native** OpenHaC circuit (`openhac.core.circuit`). Legacy SKiDL `builtins.default_circuit` is opt-in via `OPENHAC_LEGACY_SKIDL=1` for migration / schematic tooling only.

---

## Requirements

- **Python** 3.11+
- **KiCad** with **Python bindings** (`import pcbnew`) for layout/schematic — not only `kicad-cli` on `PATH`
- **Footprint libraries:** set `KICAD8_FOOTPRINT_DIR`, `KICAD9_FOOTPRINT_DIR`, or `KICAD_FOOTPRINT_DIR` to the directory that contains `*.pretty` trees (e.g. `/usr/share/kicad/footprints` on Linux)
- **ngspice (optional):** on `PATH` for `--run-ngspice` (`simulate` or `compile`) and required for `--spice-signoff`
- **FreeRouting (optional):** JRE + `FREEROUTING_JAR`. KiCad **9** has no `kicad-cli pcb export-dsn`; OpenHaC falls back to `pcbnew.ExportSpecctraDSN` / `ImportSpecctraSES` for the DSN/SES round trip.

---

## Install

From the repo root:

```bash
pip install -r requirements.txt
pip install -e .
pip install -e ".[dev]"   # optional: tests, ruff, mypy
```

`pip install -e .` installs the `openhac` console script (often into `~/.local/bin` on Linux). If the shell says `openhac: command not found`, add that directory to `PATH` **or** use the module form (works from the repo without the script):

```bash
export PATH="$HOME/.local/bin:$PATH"
python3 -m openhac --help
```

`python3 -m openhac …` is equivalent to `openhac …` everywhere below.

Runtime deps: **`requirements.txt`**. Package metadata / extras: **`pyproject.toml`**. CI pins: **`requirements.lock`**. Copy **`.env.example`** → **`.env`** for vendor keys, DB path, and FreeRouting (loaded automatically by the CLI).

---

## Environment (quick reference)

| Variable | Purpose |
|----------|---------|
| `OPENHAC_DB_PATH` | SQLite catalog path (default under `openhac/database/`) |
| `OPENHAC_API_CACHE_PATH` / `OPENHAC_CACHE_DB` | Vendor API cache SQLite path (default `~/.cache/openhac/`; not in-repo) |
| `OPENHAC_SKIP_LAYOUT` | Skip PCB layout + autoroute (netlist/BOM/manifest only) |
| `OPENHAC_COMPILE_GOAL` | `handoff` vs stricter `fabrication` |
| `OPENHAC_NO_NETWORK` | `1` = deny vendor/network enrich (CI / fabrication default under `--production`) |
| `OPENHAC_ALLOW_NETWORK` | `1` = allow network even under `fabrication` (escape hatch) |
| `OPENHAC_LEGACY_SKIDL` | `1` = use SKiDL `builtins.default_circuit` instead of native SoT |
| `OPENHAC_DETERMINISTIC` | More stable outputs for CI/golden tests |
| `FREEROUTING_JAR` | Path to FreeRouting `.jar` |
| `KICAD9_FOOTPRINT_DIR` / `KICAD8_FOOTPRINT_DIR` | Footprint search roots |
| `OPENHAC_STRICT_FOOTPRINT_PIN_PAD` | `1` = fail compile when a netted pin has no matching footprint pad (PCB-002); same idea as `--strict-footprint-pads` |
| `OPENHAC_ENRICH_STRICT_PINOUT_PADS` | `1` = when merging enriched pinouts, require pad names to line up with the KiCad footprint (stricter than default) |
| `OPENHAC_CATALOG_OVERLAY` | Pathsep-separated files/dirs of JSON catalog overrides (see `openhac/database/package_catalog_overlays/README.md`) |
| `OPENHAC_NO_BUNDLED_CATALOG_OVERLAYS` | `1` = do not merge bundled `package_catalog_overlays/*.json` (use your own overlays only) |
| `OPENHAC_PRODUCTION_SCHEMATIC` | `1` = keep schematic export when using `--production` (default off) |
| `OPENHAC_SCHEMATIC_SIGNOFF` | `1` = same as CLI `--schematic-signoff` (export + KiCad ERC + SSO gates) |
| `OPENHAC_SPICE_SIGNOFF` | `1` = same as CLI `--spice-signoff` (Kirchhoff deck + ngspice + probes/benches) |
| `OPENHAC_SPICE_VENDOR_DIR` | Directory of vendor `.lib` / `.subckt` files (not shipped in git) |
| `OPENHAC_ALLOW_BEHAVIORAL_SPICE_MODELS` | `1` = allow `kind=behavioral` models under spice sign-off (not physics-correct) |

Vendor API variables (DigiKey, Mouser, TME, JLC) are documented in **`.env.example`**. Fabrication export also uses KiCad env vars as usual.

---

## Quick start

**1. Optional — sync JLC/LCSC-oriented parts into SQLite** (one-time or periodic):

```bash
python3 -m openhac.database.sync_jlc
```

**2. Optional — seed a small baseline** (`python3 -m openhac.database.seed_data`).

**3. Compile** a design that defines a top-level `board`:

```bash
python3 -m openhac doctor --strict-layout   # optional preflight
openhac compile my_design.py --name my_board -o out/
```

See **`openhac compile` flags and examples** below. The authoritative list is `openhac compile --help`.

**FreeRouting:**

```bash
export FREEROUTING_JAR=/path/to/freerouting.jar
```

**Fabrication (Gerbers / drill / position)** after you have a `.kicad_pcb`:

```bash
openhac export fab my_board.kicad_pcb -o ./gerbers --zip

# After moving footprints in KiCad: re-export DSN with IPC widths (does not re-place)
openhac export dsn my_board.kicad_pcb
```

**Phase-2 fab gate check** (unit gates + FAB-001/003 negatives + known-good place/Gerbers when KiCad is present):

```bash
OPENHAC_NO_NETWORK=1 python3 scripts/ci_validate_fab_gates.py
# CI layout job:
OPENHAC_NO_NETWORK=1 python3 scripts/ci_validate_fab_gates.py --require-layout
```

**Full software production validation** (native ERC/DRC → schematic ERC → place → FreeRouting → PCB DRC → Gerbers):

```bash
# Logic-only (no pcbnew)
OPENHAC_NO_NETWORK=1 python3 scripts/ci_validate_production.py --logic-only

# Full claim (needs KiCad + Java + FreeRouting JAR)
export FREEROUTING_JAR=/path/to/freerouting-2.2.4.jar   # or:
OPENHAC_NO_NETWORK=1 python3 scripts/ci_validate_production.py --require-all --fetch-freerouting
```

Matrix: [docs/internal/PRODUCTION_VALIDATION.md](docs/internal/PRODUCTION_VALIDATION.md).  
Golden board: `tests/fixtures/fab_golden_board.py` (also mirrored at `examples/fab_golden_resistor_bridge.py`).

**Complex multi-IC stress boards** (7 fab examples + optional LCSC live-API board):

```bash
OPENHAC_NO_NETWORK=1 python3 scripts/ci_validate_complex_boards.py --place
python3 scripts/ci_validate_complex_boards.py --api --only lcsc_api_mixed   # live jlcsearch
```

Examples: `complex_esp32_devkit_node.py`, `complex_stm32_can_node.py`, `complex_rs485_node.py`, `complex_esp32c3_usb_node.py`, `complex_sensor_hub.py`, `complex_industrial_mesh_gateway.py`, `complex_amr_compute_brick.py`, `complex_lcsc_api_mixed_node.py`, `complex_grid_edge_rtu.py` (`openhac compile examples/complex_grid_edge_rtu.py` — catalog from `complex_grid_edge_rtu.openhac.json`, not `_offline_parts`, not in the default `--production` matrix).  
See the “Complex multi-IC boards” section in PRODUCTION_VALIDATION.md.

### JLC / LCSC boards — simple workflow

Use this when your design uses LCSC/JLC parts.

1. **Compile** — `openhac compile my_design.py -o build`. If the board ships `{stem}.openhac-seed.json` or `{stem}.openhac.json` (seed / vendor cassettes / overlays), those files load before `Component()` runs. That is the default path.
2. **Footprints** — Set `KICAD*_FOOTPRINT_DIR` so every `*.kicad_mod` your BOM references can be found (see Requirements above).
3. **Warehouse catalog (optional)** — `openhac sync` fills passives/ICs you did not seed. Not required for boards that ship a sidecar. Depth report: `openhac catalog coverage`.
4. **3D / EasyEDA (optional, needs network)** — `--auto-enrich-board` after the board already constructed. Forbidden under `--production`.
5. **Catalog overlays** — Bundled JSON under `openhac/database/package_catalog_overlays/` merges on read. Project extras: `catalog_overlays/` next to the script, `--catalog-overlay`, or `OPENHAC_CATALOG_OVERLAY`.

Example:

```bash
openhac compile my_design.py -o build
```

### 3D Model & Footprint Automation

OpenHaC can automatically download 3D models and generate footprints for LCSC parts that lack them in the local database.

- **Prefetch (before `--production`)**: `openhac catalog prefetch-3d board.py` (forbidden under `OPENHAC_NO_NETWORK`). STEP/WRL stay out of git. KiCad pack meshes stay `${KICAD9_3DMODEL_DIR}`; missing pack bodies are `~/.kiro/openhac/3d_models/<Lib>/<Footprint>.step` (bundled map, catalog LCSC, or jlcsearch by MPN).
- **Trigger**: Run with `--auto-enrich-board`. If a part has a JLC SKU (e.g., `C6396158`) but no verified footprint or missing 3D model, OpenHaC will:
    1.  Fetch the footprint and 3D model from EasyEDA.
    2.  Convert them to KiCad formats (`.kicad_mod`, `.step`).
    3.  Store them in `~/.kiro/openhac/easyeda_generated.pretty/` and `~/.kiro/openhac/easyeda_generated.3dshapes/`.
    4.  Update the project's `fp-lib-table` to include the `easyeda_generated` library.
    5.  Link the absolute path of the `.step` model to the component in the `.kicad_pcb`.

- **Persistence**: Assets are cached in your home directory (`~/.kiro/openhac/`) and reused across projects. If a cached 3D model file is deleted, OpenHaC will re-download it on the next compile.

Detailed documentation: [docs/3D_MODELS_AND_FOOTPRINTS.md](docs/3D_MODELS_AND_FOOTPRINTS.md).

### Offline demo (no vendor APIs required)

If JLC/vendor APIs are blocked/rejected, you can still compile a “presentable” design by **seeding** the SQLite catalog from a JSON file and compiling with layout disabled.

```bash
OPENHAC_SKIP_LAYOUT=1 openhac compile examples/complex_iot_edge_node_jlc_only.py \
  -o build --name iot_edge --no-route --no-schematic \
  --pre-seed-file seeds/demo_components.json
```

**Schematic appearance:** Auto-generated schematics can look crowded (overlapping text, `C?`/`U?` until you run **Tools → Annotate Schematic** in KiCad). That is mostly layout and annotation in KiCad, not the same problem as footprint pad mismatches. The steps above address **correctness** (nets ↔ pads ↔ DB); cleaning the drawing is a separate KiCad editing step.

---

## `openhac compile` flags

Run `openhac compile --help` for the full list. Common flags:

| Flag | Purpose |
|------|---------|
| `script` | Path to the hardware `.py` file (required). |
| `-o`, `--output-dir` | Directory for netlist, BOM, PCB, manifest, schematic, project. |
| `--name` | Project basename (default: script stem). |
| `--no-route`, `--no-autoroute`, `--skip-autoroute` | Same behavior: skip FreeRouting / autorouter. PCB placement still runs (unless `--skip-layout`) and writes `{name}.dsn` with IPC-2152 widths for KiCad or an external router. |
| `--freerouting-gui` | Show the FreeRouting Java GUI while routing (default is headless). Same as `OPENHAC_FREEROUTING_GUI=1`. |
| `--no-freerouting-gui` | Force headless FreeRouting for this run (overrides `.env`). |
| `--skip-layout` | Skip `pcbnew` PCB generation and autoroute (sets `OPENHAC_SKIP_LAYOUT=1` for the run). |
| `--no-schematic` | Skip `.kicad_sch` / `.kicad_pro` export. |
| `--schematic-strict` | Documentation-grade schematics: forbid implicit pins (sets `OPENHAC_SCHEMATIC_STRICT=1`). |
| `--compile-goal` | `handoff` or `fabrication` (stricter gates). |
| `--bbox-padding-mm` | Extra mm around footprint bboxes for clamp, de-overlap, and fit checks (default `0.5`). |
| `--deoverlap-iters`, `--deoverlap-step-mm` | De-overlap post-process knobs (defaults `200` and `0.75`). |
| `--strict-footprint-pads` | Fail compile if any netted pin has no matching pad on the KiCad footprint (PCB-002); same as `Board(strict_footprint_pin_pad_match=True)` or `OPENHAC_STRICT_FOOTPRINT_PIN_PAD=1`. |
| `--allow-risky-parts` | Allow low-confidence JIT symbol/footprint guesses. |
| `--strict-kicad` | Fail if KiCad symbols cannot load. |
| `--strict-jit` | Stricter JIT unless combined with `--allow-risky-parts`. |
| `--production`, `--strict` | Fabrication-oriented umbrella: fab compile goal, pad-strict, verified parts, `OPENHAC_NO_NETWORK`, schematic off unless `OPENHAC_PRODUCTION_SCHEMATIC=1`. |
| `--require-verified-parts` | Fail if unverified JIT parts are present. |
| `--kicad-erc` | After schematic export, run `kicad-cli sch erc`. |
| `--schematic-signoff` | SSO: EE-stamped `.kicad_sch` (library/pinout symbols, graph parity, `kicad-cli sch erc`). Forces schematic export even under `--production`. |
| `--spice-signoff` | After compile, write a Kirchhoff `.cir` and fail-closed ngspice sign-off (same as `openhac simulate --spice-signoff`). Implies `--run-ngspice`. Does **not** follow from `--production`. Digital cores and connectors are omitted; analog ICs still need models. |
| `--spice-island MODULE` | Repeatable. Restrict sign-off to these module names (power/analog island). |
| `--run-ngspice` | After compile, write `{name}.cir` and run ngspice (handoff deck; not physics-correct for unmodeled ICs). |
| `--spice-vendor-dir` | Vendor `.lib` directory for this run (`OPENHAC_SPICE_VENDOR_DIR`). |
| `--kicad-erc-json` | With `--kicad-erc`, ERC report as JSON. |
| `--kicad-symbol-dir`, `--kicad-symbol-dirs`, `--kicad-footprint-dir` | Override KiCad search paths for this run. |
| `--release-tag`, `--build-profile`, `--bom-profile` | Manifest metadata. |
| `--zip-release`, `--zip-release-path` | Bundle outputs into a zip. |
| `--deterministic` | Set `OPENHAC_DETERMINISTIC=1` for more stable artifacts. |
| `--manifest-sha256-sidecar` | Write manifest `.sha256` sidecar. |
| `--sync-jlc-before`, `--sync-jlc-categories` | Run JLC catalog sync before compile. |
| `--pre-seed-file` | Seed the DB from JSON before compile. |
| `--pre-enrich-json`, `--pre-enrich-vendor`, `--pre-enrich-limit` | Batch enrich from JSON before compile. |
| `--auto-enrich-board`, `--auto-enrich-vendor`, `--auto-enrich-limit` | Discover missing DB metadata and enrich after loading the board. |

**Environment (not on the CLI):** placement (`OPENHAC_PLACEMENT_*`), PCB overlap checks (`OPENHAC_PCB_CHECK_FP_OVERLAP`, `OPENHAC_FP_OVERLAP_CLEARANCE_MM`), strict pin↔pad (`OPENHAC_STRICT_FOOTPRINT_PIN_PAD`), schematic spacing / embed (`OPENHAC_SCHEMATIC_*`), FreeRouting timeout (`OPENHAC_FREEROUTING_TIMEOUT_S`). See **`.env.example`**. Compile also writes **`*.openhac-pin-pad-report.json`** (preflight pin keys vs `.kicad_mod` pads) when layout runs.

Schematic readability defaults:

- **Multi-sheet**: auto-enabled when part count ≥ `OPENHAC_SCHEMATIC_MULTI_SHEET_MIN_PARTS` (default 25). Force on with `OPENHAC_SCHEMATIC_MULTI_SHEET=1`, or force single-sheet with `OPENHAC_SCHEMATIC_SINGLE_SHEET=1`.
- **Strict schematic pinout**: set `OPENHAC_SCHEMATIC_STRICT=1` (or `--schematic-strict`) to block implicit pins (recommended for documentation builds).

Auto board sizing (when `Board(size_mm=None)`):

- OpenHaC will attempt a **tight deterministic pack** using pcbnew footprint bounding boxes, then set the board outline to the packed extents plus margin.
- If pcbnew/footprints are unavailable, it falls back to a conservative module-area heuristic.
- Knobs:
  - `OPENHAC_AUTO_BOARD_PACK_COLS`: optional fixed column count for packing (default: `ceil(sqrt(N_parts))`)
  - `OPENHAC_AUTO_BOARD_MARGIN_FACTOR`: default `1.15`
  - `OPENHAC_AUTO_BOARD_MIN_EDGE_MARGIN_MM`: default `5.0`
  - `OPENHAC_PLACEMENT_FP_GAP_MM`: gap between packed footprints (default `1.0`)

### Examples

```bash
# Default-style compile with outputs under ./build
openhac compile my_design.py -o build --name my_board

# Fast iteration: place PCB + schematic, skip autorouting
openhac compile my_design.py -o build --no-autoroute

# Autoroute with the FreeRouting Java window (default is headless)
openhac compile my_design.py -o build --freerouting-gui

# Same as above (aliases)
openhac compile my_design.py -o build --skip-autoroute

# Netlist / BOM / manifest only (no PCB, no route)
openhac compile my_design.py -o build --skip-layout

# Stricter fabrication pipeline (offline + pad-strict + verified parts; no schematic by default)
openhac compile my_design.py -o build --compile-goal fabrication --production --no-route

# Fail on pin↔footprint pad mismatches before pcbnew (fix DB pinout vs footprint)
openhac compile my_design.py -o build --strict-footprint-pads

# De-overlap and padding when footprints still crowd
openhac compile my_design.py -o build --bbox-padding-mm 1.0 --deoverlap-iters 400 --deoverlap-step-mm 1.0

# Schematic ERC, then optional JSON report
openhac compile my_design.py -o build --kicad-erc --kicad-erc-json

# After PCB compile, analog-island SPICE into the same -o dir
openhac compile my_design.py -o build --spice-signoff --spice-island Ldo3V3 --spice-vendor-dir spice_vendor/

# Release bundle
openhac compile my_design.py -o dist --zip-release --release-tag v1.0.0

# Deterministic artifacts + manifest sha256 sidecar
openhac compile my_design.py -o out --deterministic --manifest-sha256-sidecar
```

---

## `openhac simulate` and ngspice

`openhac simulate board.py` writes a SPICE deck (`{name}.cir`). `openhac compile … --run-ngspice` / `--spice-signoff` does the same after a successful compile, into the compile `-o` directory. That handoff deck may be unsolvable; generic IC value lines are not physics-correct. Add `--run-ngspice` to execute it, or `--spice-signoff` for the fail-closed analog gate (implies ngspice). See [SPICE_SIGN_OFF_SPEC.md](docs/internal/SPICE_SIGN_OFF_SPEC.md).

```bash
# Handoff deck + batch ngspice (log next to the .cir)
python3 -m openhac simulate examples/sso041_signoff_node.py --run-ngspice -o build --name myboard

# Fail-closed sign-off (ngspice required; writes audit JSON)
python3 -m openhac simulate examples/sso041_signoff_node.py --spice-signoff -o build --name myboard
```

**Where the solver output is:**

| Artifact | Default path |
|----------|----------------|
| Deck | `build/myboard.cir` |
| ngspice batch log | `build/myboard.cir.ngspice.log` (`--ngspice-log PATH` to override) |
| Sign-off audit | `build/myboard.openhac-spice-signoff-audit.json` (`op_voltages`, probes, `coverage`, `ngspice_log`) |

Read the log with `less build/myboard.cir.ngspice.log`. Run the solver yourself:

```bash
ngspice -b -o out.log build/myboard.cir    # batch
ngspice build/myboard.cir                  # interactive
```

Vendor macromodels stay on disk under `OPENHAC_SPICE_VENDOR_DIR` (or `--spice-vendor-dir`); git does not ship proprietary `.lib` files. Operator path: drop the `.lib` in that directory → overlay JSON with sha256/`pin_map` → `openhac spice verify-vendor-dir` → `--spice-signoff`. Coverage without ngspice: `openhac spice coverage board.py`. Analog island: `examples/spice_island_golden.py`. Do not curl a `.lib` from the compiler.

---

## Usage sketch

```python
from openhac.core import Board
from openhac.stdlib.power import XT60_Input, LDO_5V
from openhac.stdlib.mcu import ESP32_WROOM

board = Board(size_mm=(60, 40), layers=2)
power, ldo, mcu = XT60_Input(), LDO_5V(), ESP32_WROOM()
board.add_module(power)
board.add_module(ldo)
board.add_module(mcu)
board.connect(power.v_out, ldo.v_in)
board.connect(ldo.v_out, mcu.power)

board.compile(project_name="my_board", generate_bom=True, auto_route=True, export_schematic=True)
```

Preflight: `openhac doctor --json` (add `--strict-layout`, `--strict-routing`, etc. as needed).

---

## LaTeX report

Long-form write-up: `docs/internal/report/`. Build PDF: `python3 scripts/build_latex_report.py` (needs a LaTeX engine).

---

## Development / CI

```bash
pip install -e ".[dev]"
ruff check openhac tests
# Hard gate (FAB-050): core + placement/layout + schematic IR + spice_gen + compile_pipeline
mypy openhac/core openhac/compiler/pcb_placement.py openhac/compiler/layout_gen.py \
  openhac/schematic/ir.py openhac/compiler/spice_gen.py openhac/compiler/compile_pipeline.py \
  --ignore-missing-imports --follow-imports=silent
OPENHAC_NO_NETWORK=1 pytest tests/ -q
OPENHAC_NO_NETWORK=1 python3 scripts/ci_validate_fab_gates.py   # optional locally; required in kicad-fab-golden job
OPENHAC_NO_NETWORK=1 python3 scripts/ci_validate_production.py --require-all --fetch-freerouting  # full ERC→DRC→Gerbers
```

GitHub Actions runs the above plus KiCad schematic ERC, layout smoke, fab golden, and **kicad-production-validation** jobs. See `.github/workflows/ci.yml`.

---

## Errors

Common compiler exceptions live in `openhac.core.base` and `openhac.compiler.rule_check` — e.g. floating/unconnected nets, interface not wired, power budget, FreeRouting missing/failed, layout/schematic failures, DRC violations, risky JIT lookups, fabrication pin/footprint refusals (FAB-001/003). See docstrings and tests for details.

---

## Layout

```
openhac/
  core/           # Component, Module, Board (native circuit SoT)
  stdlib/         # Reusable modules
  compiler/       # Netlist, layout, PCB, schematic, SPICE, export, manifest
  database/       # SQLite catalog, sync_jlc, seed (vendor cache under ~/.cache/openhac/)
tests/            # Unit tests + fab fixtures (tests/fixtures/fab_*.py)
scripts/          # CI smoke, fab gate validator, report build
examples/         # Sample boards (incl. fab golden mirror)
```

---

## License

Open source — see **LICENSE**.
