# Package catalog overlays (reference)

JSON files in this directory are **bundled defaults** merged on every `DatabaseManager.get_component()` call
(unless `OPENHAC_NO_BUNDLED_CATALOG_OVERLAYS=1`). They correct known-bad distributor metadata and supply
**footprint-aligned** `pinout` tables (`num` must match KiCad `.kicad_mod` pad names).

## Your own boards (scalable)

1. Add a directory in **your** repo, e.g. `catalog_overlays/`, with one or more `*.json` files.
2. Each file is a **JSON array** of objects; each object must include `generic_name` and any fields to override
   (`kicad_footprint`, `category`, `mpn`, `supplier_sku`, `pinout` as a list of `{num, name, type}`, or `pinout_json`).
3. Compile with:

   ```bash
   python3 -m openhac compile my_board.py --catalog-overlay ./catalog_overlays
   ```

   or set `OPENHAC_CATALOG_OVERLAY=./catalog_overlays` (pathsep-separated list of files and/or directories).

**Later entries / lexicographically later filenames win** for the same `generic_name` key when merging files.

User overlays override bundled overlays.

## Pipeline

`phase_catalog_overlay_info` logs active overlay sources. PCB-002 errors append a hint to use `--catalog-overlay` when strict footprint pad checks fail.
