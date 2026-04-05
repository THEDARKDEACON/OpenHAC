# Schematic hierarchy authoring (SCH-002)

OpenHaC emits a **single flat** `.kicad_sch`. To mirror your Python `Module` tree in KiCad:

1. Run `Board.compile(..., export_schematic=True)` and open the generated project.
2. Read **`logical_modules`** and **`schematic_hierarchy_handoff`** in `{project}.openhac-manifest.json`: each entry lists the module name and SKiDL **references** that belong to that subtree.
3. In KiCad, create hierarchical sheets (one per logical module or per subsystem), move or re-instantiate symbols so refs match the manifest partition, and connect sheet pins to match your `declare_interface` / `connect` intent.

OpenHaC does not auto-generate multi-sheet `.kicad_sch` files yet; the manifest is the contract between code structure and manual sheet breakdown.
