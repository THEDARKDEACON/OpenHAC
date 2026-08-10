# OpenHaC — Open Hardware-as-Code

Python compiler that turns declarative hardware code into **netlists**, **BOMs**, **KiCad PCB** outputs, optional **FreeRouting**, and **SPICE** — no GUI required. Connectivity and ERC are first-class; pretty `.kicad_sch` drawings are optional handoff aids, not the fabrication source of truth.

## Outputs

- `.net` / `.csv` — netlist and BOM (LCSC-oriented fields when available)
- `.kicad_pcb` — placement, pad nets; optional autoroute (FreeRouting or minimal `pcbnew` fallback)
- `.kicad_sch` / `.kicad_pro` — optional schematic + project (off by default under `--production`)
- Generated symbol stubs (`*.openhac-generated.kicad_sym`) and manifest / handoff JSON when configured
- `.cir` — SPICE from `Board.simulate()`
- Fab bundle — Gerbers / drill / position via `openhac export fab` (after a successful PCB)

**Docs:** [USER_GUIDE.md](docs/USER_GUIDE.md), [API_REFERENCE.md](docs/API_REFERENCE.md), [3D_MODELS_AND_FOOTPRINTS.md](docs/3D_MODELS_AND_FOOTPRINTS.md).
**Internal/Spec:** [SCOPE.md](docs/internal/SCOPE.md), [IMPLEMENTATION_STATUS.md](docs/internal/IMPLEMENTATION_STATUS.md), [FABRICATION_READINESS_SPEC.md](docs/internal/FABRICATION_READINESS_SPEC.md) (Phase-2 code→fab gates).

Autorouting is **assistive** (not a substitute for HS/EMC review). See SCOPE for **PCB-007** / differential-pair notes. Phase-2 defines fail-closed fabrication gates — track status in IMPLEMENTATION_STATUS; do not treat Alpha handoff builds as production-ready copper.

The active circuit is the **native** OpenHaC circuit (`openhac.core.circuit`). Legacy SKiDL `builtins.default_circuit` is opt-in via `OPENHAC_LEGACY_SKIDL=1` for migration / schematic tooling only.

---

## Requirements

- **Python** 3.11+
- **KiCad** with **Python bindings** (`import pcbnew`) for layout/schematic — not only `kicad-cli` on `PATH`
- **Footprint libraries:** set `KICAD8_FOOTPRINT_DIR`, `KICAD9_FOOTPRINT_DIR`, or `KICAD_FOOTPRINT_DIR` to the directory that contains `*.pretty` trees (e.g. `/usr/share/kicad/footprints` on Linux)
- **FreeRouting (optional):** JRE + `FREEROUTING_JAR`. KiCad **9** has no `kicad-cli pcb export-dsn`; OpenHaC falls back to `pcbnew.ExportSpecctraDSN` / `ImportSpecctraSES` for the DSN/SES round trip.

---

## Install

```bash
pip install -e .
pip install -e ".[dev]"   # optional: tests, ruff, mypy
```

Dependencies live in **`pyproject.toml`**. Copy **`.env.example`** → **`.env`** for vendor keys, DB path, and FreeRouting (loaded automatically by the CLI).

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
```

**Phase-2 fab gate check** (unit gates + FAB-001/003 negatives + known-good place/Gerbers when KiCad is present):

```bash
OPENHAC_NO_NETWORK=1 python3 scripts/ci_validate_fab_gates.py
# CI layout job:
OPENHAC_NO_NETWORK=1 python3 scripts/ci_validate_fab_gates.py --require-layout
```

Golden board: `tests/fixtures/fab_golden_board.py` (also mirrored at `examples/fab_golden_resistor_bridge.py`).

### JLC / LCSC boards — simple workflow

Use this when your design uses LCSC/JLC parts and you want the catalog, enrich, and optional pad checks to line up.

1. **Footprints** — Set `KICAD*_FOOTPRINT_DIR` so every `*.kicad_mod` your BOM references can be found (see Requirements above).
2. **Catalog in SQLite** — Refresh occasionally: `python3 -m openhac.database.sync_jlc`, or add `--sync-jlc-before` on `openhac compile` so sync runs automatically before the board loads.
3. **Fill gaps after load** — Add `--auto-enrich-board` so OpenHaC can discover missing DB rows and enrich symbol/pinout data for the parts on your board.
4. **Stricter fab check (optional)** — When you are ready to fail on bad pin↔pad pairing: `--strict-footprint-pads` (or `OPENHAC_STRICT_FOOTPRINT_PIN_PAD=1`). For stricter merge rules during enrich, set `OPENHAC_ENRICH_STRICT_PINOUT_PADS=1`.
5. **Catalog overlays** — Bundled JSON fixes live under `openhac/database/package_catalog_overlays/` and merge automatically unless `OPENHAC_NO_BUNDLED_CATALOG_OVERLAYS=1`. For **extra** project-specific overrides, use `--catalog-overlay /path/to/dir-or-file` or `OPENHAC_CATALOG_OVERLAY`. Details: `openhac/database/package_catalog_overlays/README.md`.

Example (sync + enrich in one compile):

```bash
openhac compile my_design.py -o build --sync-jlc-before --auto-enrich-board
```

### 3D Model & Footprint Automation

OpenHaC can automatically download 3D models and generate footprints for LCSC parts that lack them in the local database.

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
| `--no-route`, `--no-autoroute`, `--skip-autoroute` | Same behavior: skip FreeRouting / autorouter (PCB placement still runs unless layout is skipped). |
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

# Release bundle
openhac compile my_design.py -o dist --zip-release --release-tag v1.0.0

# Deterministic artifacts + manifest sha256 sidecar
openhac compile my_design.py -o out --deterministic --manifest-sha256-sidecar
```

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
# Hard gate (FAB-050): core + PCB placement/layout only
mypy openhac/core openhac/compiler/pcb_placement.py openhac/compiler/layout_gen.py \
  --ignore-missing-imports --follow-imports=silent
OPENHAC_NO_NETWORK=1 pytest tests/ -q
OPENHAC_NO_NETWORK=1 python3 scripts/ci_validate_fab_gates.py   # optional locally; required in kicad-fab-golden job
```

GitHub Actions runs the above plus KiCad schematic ERC and layout/fab golden jobs. See `.github/workflows/ci.yml`.

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
