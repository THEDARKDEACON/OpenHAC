# Package catalog overlays (reference)

JSON files in this directory are **fixups** merged on `get_component()` unless
`OPENHAC_NO_BUNDLED_CATALOG_OVERLAYS=1`. Files whose name contains `reference_bom`
are **not** auto-merged (**LIB-007**); pass them with `--catalog-overlay`
(example: `00_reference_bom.json`). Pin/footprint fixups live in
`01_package_pinout_fixups.json` and **are** auto-merged.

## Your own boards (scalable)

1. Add a directory in **your** repo, e.g. `catalog_overlays/`, with one or more `*.json` files.
2. Each file is a **JSON array** of objects; each object must include `generic_name` and any fields to override
   (`kicad_footprint`, `category`, `mpn`, `supplier_sku`, `pinout` as a list of `{num, name, type}`, or `pinout_json`).
   **CAT-008** also allows 3D / SPICE pointers when implemented: `model_3d_local`, `model_3d_sha256`,
   `model_3d_license`, `spice_include`, `spice_subckt`. See [CATALOG_DEPTH_SPEC.md](../../../docs/internal/CATALOG_DEPTH_SPEC.md).
3. Compile with:

   ```bash
   python3 -m openhac compile my_board.py --catalog-overlay ./catalog_overlays
   ```

   or set `OPENHAC_CATALOG_OVERLAY=./catalog_overlays` (pathsep-separated list of files and/or directories).

**Later entries / lexicographically later filenames win** for the same `generic_name` key when merging files.

User overlays override bundled overlays.

## Parametric twins (CAT-015)

Same electrical part, different SKU or assembler: store one pin table on the primary `components` row and attach twins as `part_alternates` / `part_offers`. Do **not** clone `pinout_json` per SKU. PCBWay / Seeed stock is additional **offer** rows only (**CAT-011**), not a second pin/footprint source of truth.

Licence-gated symbol/3D shops (**CAT-012**): without an explicit licence field, OpenHaC does not store the file. Cache is `~/.kiro/openhac/` (never git).

## Pipeline

`phase_catalog_overlay_info` logs active overlay sources. PCB-002 errors append a hint to use `--catalog-overlay` when strict footprint pad checks fail.
