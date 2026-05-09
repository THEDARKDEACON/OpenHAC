# 3D Models and Footprint Automation

OpenHaC provides an automated pipeline to ensure every component in your design has a physical footprint and a 3D model, even if they aren't present in your local KiCad libraries or the baseline SQLite catalog.

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
If you open the PCB and don't see 3D models:
1.  **Check Logs**: Look for `Attached 3D model to U*` in the compilation output.
2.  **Verify Files**: Ensure the `.step` files exist in `~/.kiro/openhac/easyeda_generated.3dshapes/`.
3.  **Regenerate**: If the DB has a path but the file is gone, simply re-running the compile with `--auto-enrich-board` will trigger a re-download.

### Footprint Resolution Failures
If KiCad complains it can't find a footprint in `easyeda_generated`:
- Ensure the `fp-lib-table` in your project folder contains the entry for `easyeda_generated`.
- OpenHaC generates this automatically, but if you moved the project folder, the `${HOME}` relative path might need checking (though it is designed to be portable).

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENHAC_ENRICH_STRICT_PINOUT_PADS` | `0` | If `1`, requires pad names to match the footprint exactly. |
| `OPENHAC_STRICT_FOOTPRINT_PIN_PAD` | `0` | If `1`, fails compile if any netted pin lacks a matching pad. |

## Dependencies
- `easyeda2kicad`: Used for the heavy lifting of API interaction and conversion.
- `pcbnew`: Required for the final synthesis and 3D model attachment.
