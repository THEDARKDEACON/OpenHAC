# 3D Models and Footprint Automation

OpenHaC provides an automated pipeline to ensure every component in your design has a physical footprint and a 3D model, even if they aren't present in your local KiCad libraries or the baseline SQLite catalog.

Normative catalog-depth IDs (**3D-001…006**, **CAT-***): treat STEP/WRL as a first-class catalog field (path, hash, licence, source), prefer KiCad library models for JEDEC passives, prefetch into `~/.kiro/openhac/3d_models/<Lib>/<Footprint>.step` **before** `--production`, and keep binaries out of git. See [internal/CATALOG_DEPTH_SPEC.md](internal/CATALOG_DEPTH_SPEC.md). This page remains the operator how-to.

**Git policy (3D-005):** this repo does not commit `.step` / `.wrl` (`**/*.step` and `**/*.wrl` in `.gitignore`). Overlays and `3d_fillin_map.json` store **paths, LCSC ids, and hashes**, not file bytes. Missing 3D is a `openhac catalog coverage` row (**3D-004**); OpenHaC does not silently bind a fake cube.

Prefetch before fabrication (network; forbidden under `OPENHAC_NO_NETWORK` / `--production`):

```bash
openhac catalog coverage
openhac catalog prefetch-3d board.py
openhac catalog prefetch-3d --skus C165948,C164170
openhac compile board.py -o /tmp/out --no-route
```

`--auto-enrich-board` is not how 3D gets onto stock KiCad footprints. Compile stays offline: it attaches a KiCad pack file, or a fill-in STEP already on disk.

## Overview

The automation pipeline bridges the gap between declarative code and physical manufacturing by fetching assets from the **EasyEDA/LCSC ecosystem**. When a part is identified by a JLC SKU (e.g., `C6396158`), OpenHaC can JIT-generate the necessary KiCad files.

## How it Works

The process is integrated into the **Enrichment Phase** of the compiler.

### 1. Discovery
When you run `openhac compile --auto-enrich-board`, the compiler crawls your board's component graph. For each component, it checks the local database for:
- A valid KiCad footprint path.
- A valid 3D model path (and verifies the file exists on disk).

### 2. Just-In-Time Generation
If the part lacks a footprint or its 3D model is missing, OpenHaC triggers the `easyeda_integration` module:
- **API Fetch**: It uses `easyeda2kicad` to pull the component JSON from EasyEDA.
- **Footprint Conversion**: The EasyEDA JSON is converted into a standard KiCad `.kicad_mod` file.
- **3D Model Export**: The STEP model is downloaded and exported.
- **Normalization**: Filenames are normalized to match the component's safe name (e.g., `SENSOR-TH_ACS758LCB-100B-PFF-T.step`).

### 3. Asset Storage
Generated assets are stored in a persistent cache directory:
- **Footprints**: `~/.kiro/openhac/easyeda_generated.pretty/`
- **3D Models**: `~/.kiro/openhac/easyeda_generated.3dshapes/`

This ensures that once a part is generated, it is available offline for all future projects.

### 4. Project Integration
During the synthesis of the KiCad project (`.kicad_pcb` and `.kicad_pro`):
- **Library Table**: The `easyeda_generated` library is automatically added to the project's `fp-lib-table`.
- **Absolute Pathing**: OpenHaC uses absolute paths to the STEP files when attaching them to footprints. This bypasses KiCad's environment variable limitations and ensures the 3D viewer works immediately upon opening the board.

## Troubleshooting

### Missing 3D Models in KiCad
Stock KiCad footprints (0805, VSSOP/MSOP, SOIC, LQFP, …) use the KiCad 3D pack under
`/usr/share/kicad/3dmodels` (or the macOS/Windows equivalent). Compile detects that
directory and writes `${KICAD9_3DMODEL_DIR}` into the footprint and `.kicad_pro`.
Open the `.kicad_pro` from the KiCad project manager, then View → 3D Viewer.

Connectors with **no** pack body (HRO USB-C, Molex microSD) use the footprint
fill-in cache (**3D-006**):

`~/.kiro/openhac/3d_models/<Lib>/<FootprintName>.step`

The map is `openhac/database/3d_fillin_map.json` (`lcsc:C…` or `file:/path`).
Prefetch also **discovers** an LCSC id by manufacturer part number (jlcsearch
`mfr` match, never the first unrelated hit) and remembers it in
`~/.kiro/openhac/3d_fillin_discovered.json` (not git). Compile does **not** glob
`easyeda_generated.3dshapes` or pick `R0805.step` from a JLC folder. Leftover
JEDEC cubes are never attached to those footprints. Test pads / mounting holes
are skipped. `--production` never fetches.

If a stock body is still empty:
1. Check compile logs for `Attached 3D model to U*` with a `${KICAD*_3DMODEL_DIR}` path, or an absolute fill-in `.step`.
2. Confirm the 3D pack is installed (`*.3dshapes` under the 3D directory).
3. VSSOP-10 is aliased to MSOP-10 when that is the file KiCad shipped. QFN
   exposed-pad names within 0.2 mm of the pack file also alias (same body/pitch).
4. Run `openhac catalog prefetch-3d board.py` then recompile. Prefetch uses the
   fill-in map, a catalog `C…` SKU, or jlcsearch by MPN for **any** stock
   footprint whose pack file is missing. It **audits** cache files: a QFN/SOP
   chip STEP on a breakout or connector footprint is deleted, the LCSC id is
   remembered as rejected, and compile will not attach it. `--force` re-fetches
   a *valid* cache; it still refuses a chip-on-module body.

Do not map an IC MPN (`nRF24L01+`) onto `RF_Module:nRF24L01_Breakout`. Missing
module 3D is a coverage hole (**3D-004**), not a 4 mm QFN on the header.

### Footprint Resolution Failures
If KiCad complains it can't find a footprint in `easyeda_generated`:
- Ensure the `fp-lib-table` in your project folder contains the entry for `easyeda_generated`.
- OpenHaC generates this automatically, but if you moved the project folder, the `${HOME}` relative path might need checking (though it is designed to be portable).

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENHAC_3D_FILLIN_DIR` | `~/.kiro/openhac/3d_models` | Footprint-keyed STEP cache root |
| `OPENHAC_3D_FILLIN_MAP` | bundled `3d_fillin_map.json` | Extra JSON file or directory of maps (overrides bundled) |
| `OPENHAC_3D_FILLIN_DISCOVERED` | next to fill-in dir / `~/.kiro/openhac/3d_fillin_discovered.json` | Prefetch-discovered LCSC hits (does not override bundled) |
| `OPENHAC_ENRICH_STRICT_PINOUT_PADS` | `0` | If `1`, requires pad names to match the footprint exactly. |
| `OPENHAC_STRICT_FOOTPRINT_PIN_PAD` | `0` | If `1`, fails compile if any netted pin lacks a matching pad. |

## Dependencies
- `easyeda2kicad`: Used for the heavy lifting of API interaction and conversion.
- `pcbnew`: Required for the final synthesis and 3D model attachment.
